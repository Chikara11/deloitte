"""FastAPI backend for AuditBridge (Deloitte x Google Cloud)."""

from __future__ import annotations

import asyncio
import csv
import io
import json
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.responses import HTMLResponse, PlainTextResponse, Response
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from app.agents.exporter import render_control_sheet_docx
from app.agents.harness import execute_audit_harness, resume_gate2_expert, resume_gate3_auditor
from app.agents.models import AuditCase, CanonicalInvoice, LedgerEntry
from app.data.audit_logger import audit_logger
from app.data.normalizer import DATA_ROOT, Gate1BlockError, load_passport, normalize_csv_file, normalize_txt_file

_CASES: dict[str, AuditCase] = {}
_STATIC_INDEX = Path(__file__).parent / "static" / "index.html"
_QUARANTINE_LOCATORS: dict[str, dict[str, Any]] = {}


class Gate2Payload(BaseModel):
    role: str
    decision: str
    comment: str = ""
    responder: str = "expert@deloitte.fr"


class Gate3Payload(BaseModel):
    decision: str  # Valider | Rejeter
    validator: str = "auditeur.senior@deloitte.fr"
    comment: str = ""


def _ingest_path(tenant_id: str, path: Path) -> list[AuditCase]:
    sid = f"sess-{uuid.uuid4().hex[:8]}"
    rel = str(path.relative_to(DATA_ROOT.parent))
    try:
        if path.suffix.lower() == ".csv":
            items = normalize_csv_file(tenant_id, sid, path)
        else:
            items = [normalize_txt_file(tenant_id, sid, path)]
        created: list[AuditCase] = []
        for canon, loc in items:
            case = execute_audit_harness(canon, loc, session_id=sid)
            _CASES[case.case_id] = case
            created.append(case)
        return created
    except Gate1BlockError as err:
        q_inv = CanonicalInvoice(
            tenant_id=tenant_id,
            invoice_id=f"QUARANTINE-{path.stem}",
            supplier="[BLOQUE GATE 1]",
            customer=tenant_id,
            is_intercompany=False,
            amount_ht=0.0,
            vat_rate=0.0,
            amount_ttc=0.0,
            invoice_date="2026-12-31",
            service_date="2026-12-31",
            ledger_entry=LedgerEntry(account="N/A", amount=0.0, period="2026-12"),
            description=err.reason,
            source_file=err.file_rel,
        )
        q_case = AuditCase(
            case_id=f"{tenant_id}:QUARANTINE:{path.name}",
            session_id=sid,
            tenant_id=tenant_id,
            status="Quarantaine",
            invoice=q_inv,
            auditor_explanation=err.reason,
            confidence_score=0,
            score_color="red",
            recommendation=f"Document mis en quarantaine à la Gate 1 ({err.action}). Ne jamais transmettre au LLM.",
            harness_step="QUARANTINED",
            last_action=f"Quarantaine ({err.action})",
            quarantine_reason=err.reason,
            control_sheet_md=f"# QUARANTAINE GATE 1 — {rel}\n\n- **Action :** `{err.action}`\n- **Raison :** {err.reason}\n- **Localisation :** `{err.locator}`\n",
        )
        _CASES[q_case.case_id] = q_case
        _QUARANTINE_LOCATORS[q_case.case_id] = {"file": err.file_rel, "locator": err.locator, "reason": err.reason}
        return [q_case]


def seed_demo_cases() -> None:
    """Seed the 3 required demo cases: normal (green), 2M€ interco (anomaly), poisoned (quarantined)."""
    _CASES.clear()
    _QUARANTINE_LOCATORS.clear()
    audit_logger.clear()

    _ingest_path("CLIENT_A", DATA_ROOT / "inputs" / "CLIENT_A" / "erp_export.csv")
    _ingest_path("CLIENT_B", DATA_ROOT / "inputs" / "CLIENT_B" / "facture_0412.txt")
    _ingest_path("CLIENT_B", DATA_ROOT / "inputs" / "CLIENT_B" / "facture_poison.txt")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    seed_demo_cases()
    yield


app = FastAPI(title="AuditBridge — Deloitte x Google Cloud", version="2.0.0", lifespan=lifespan)


@app.get("/", response_class=HTMLResponse)
async def serve_ui() -> HTMLResponse:
    return HTMLResponse(_STATIC_INDEX.read_text(encoding="utf-8"))


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/seed")
async def reseed_demo() -> dict[str, Any]:
    seed_demo_cases()
    return {"seeded": len(_CASES), "cases": [c.model_dump() for c in _CASES.values()]}


@app.get("/api/clients")
async def get_clients() -> dict[str, Any]:
    return {
        "CLIENT_A": load_passport("CLIENT_A"),
        "CLIENT_B": load_passport("CLIENT_B"),
    }


@app.get("/api/cases")
async def list_cases(tenant_id: str | None = None) -> list[dict[str, Any]]:
    items = list(_CASES.values())
    if tenant_id:
        items = [c for c in items if c.tenant_id == tenant_id]
    return [c.model_dump() for c in items]


@app.post("/api/tenants/{tenant_id}/upload")
async def upload_input(tenant_id: str, file: UploadFile = File(...)) -> dict[str, Any]:
    name = Path(file.filename or "uploaded.txt").name
    dest_dir = DATA_ROOT / "inputs" / tenant_id
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / name
    dest.write_bytes(await file.read())
    created = _ingest_path(tenant_id, dest)
    return {"cases": [c.model_dump() for c in created]}


@app.post("/api/cases/{case_id:path}/gate2")
async def gate2_submit(case_id: str, payload: Gate2Payload) -> dict[str, Any]:
    case = _CASES.get(case_id)
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")
    updated = resume_gate2_expert(case, payload.role, payload.decision, payload.comment, payload.responder)
    _CASES[case_id] = updated
    return updated.model_dump()


@app.post("/api/cases/{case_id:path}/gate3")
async def gate3_submit(case_id: str, payload: Gate3Payload) -> dict[str, Any]:
    case = _CASES.get(case_id)
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")
    updated = resume_gate3_auditor(case, payload.decision, payload.validator, payload.comment)
    _CASES[case_id] = updated
    return updated.model_dump()


@app.post("/api/tenants/{tenant_id}/bulk-validate")
async def bulk_validate_green(tenant_id: str, validator: str = "auditeur.senior@deloitte.fr") -> dict[str, Any]:
    count = 0
    for cid, case in list(_CASES.items()):
        if case.tenant_id == tenant_id and case.status == "Conforme" and case.score_color == "green":
            _CASES[cid] = resume_gate3_auditor(case, "Valider", validator, "Validation en masse (score vert)")
            count += 1
    return {"validated_count": count}


@app.get("/api/cases/{case_id:path}/export/md", response_class=PlainTextResponse)
async def export_md(case_id: str) -> PlainTextResponse:
    case = _CASES.get(case_id)
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")
    return PlainTextResponse(
        case.control_sheet_md,
        media_type="text/markdown",
        headers={"Content-Disposition": f'attachment; filename="fiche_{case.invoice.invoice_id}.md"'},
    )


@app.get("/api/cases/{case_id:path}/export/docx")
async def export_docx(case_id: str) -> Response:
    case = _CASES.get(case_id)
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")
    data = render_control_sheet_docx(case)
    return Response(
        content=data,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f'attachment; filename="fiche_{case.invoice.invoice_id}.docx"'},
    )


@app.get("/api/files")
async def read_source_file(path: str = Query(..., description="Relative path inside data/")) -> dict[str, Any]:
    """Serve source files (txt, md, csv, json) safely for the Evidence Viewer."""
    repo_root = DATA_ROOT.parent.resolve()
    target = (repo_root / path).resolve()
    if not str(target).startswith(str(DATA_ROOT.resolve())) or not target.exists():
        raise HTTPException(status_code=404, detail="File not found")

    raw = target.read_text(encoding="utf-8")
    ext = target.suffix.lower()
    if ext == ".csv":
        rows = list(csv.reader(io.StringIO(raw)))
        return {"path": path, "kind": "csv", "headers": rows[0] if rows else [], "rows": rows[1:] if len(rows) > 1 else []}
    if ext == ".json":
        return {"path": path, "kind": "json", "raw": json.dumps(json.loads(raw), indent=2, ensure_ascii=False)}
    return {"path": path, "kind": "text", "lines": raw.splitlines()}


@app.get("/api/quarantine/{case_id:path}")
async def get_quarantine_detail(case_id: str) -> dict[str, Any]:
    detail = _QUARANTINE_LOCATORS.get(case_id)
    if not detail:
        raise HTTPException(status_code=404, detail="Quarantine detail not found")
    return detail


@app.get("/api/trust")
async def get_trust_state() -> dict[str, Any]:
    return {
        "metrics": audit_logger.metrics,
        "logs": [l.model_dump() for l in audit_logger.list_logs()[-50:]],
    }


@app.get("/api/logs/stream")
async def stream_logs() -> EventSourceResponse:
    q = audit_logger.subscribe()

    async def gen():
        try:
            for evt in audit_logger.list_logs()[-30:]:
                yield {"event": "log", "data": json.dumps(evt.model_dump())}
            while True:
                try:
                    evt = await asyncio.wait_for(q.get(), timeout=15.0)
                    yield {"event": "log", "data": json.dumps(evt.model_dump())}
                except asyncio.TimeoutError:
                    yield {"event": "ping", "data": "{}"}
        finally:
            audit_logger.unsubscribe(q)

    return EventSourceResponse(gen())
