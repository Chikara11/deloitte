"""FastAPI backend for AuditBridge — 5-Gate HITL & Hash-Chained Firestore Audit Log."""

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
from app.agents.harness import (
    HarnessPermissionError,
    HarnessSecurityError,
    bulk_approve_green,
    execute_audit_harness,
    gate1_decide,
    gate2_decide,
    gate3_decide,
    gate4_expert_answer,
    gate5_decide,
)
from app.agents.models import AuditCase, CanonicalInvoice, LedgerEntry
from app.data.audit_logger import audit_logger
from app.data.normalizer import DATA_ROOT, Gate1BlockError, load_passport, normalize_csv_file, normalize_txt_file

_STATIC_INDEX = Path(__file__).parent / "static" / "index.html"
_STATIC_PRESENTATION = Path(__file__).parent / "static" / "presentation.html"
_QUARANTINE_LOCATORS: dict[str, dict[str, Any]] = {}


class Gate1Payload(BaseModel):
    decision: str  # Release | Confirm block
    actor_id: str = "soc.analyst@deloitte.fr"
    actor_role: str = "Analyste sécurité"
    comment: str


class Gate2Payload(BaseModel):
    decision: str  # Approve | Edit | Reject
    actor_id: str = "auditeur.senior@deloitte.fr"
    actor_role: str = "Auditeur"
    comment: str = ""
    scope_files: list[str] | None = None
    rule_overrides: list[dict[str, Any]] | None = None
    evidence_additions: list[dict[str, Any]] | None = None


class Gate3Payload(BaseModel):
    decision: str  # Approve | Edit | Reject
    actor_id: str = "auditeur.senior@deloitte.fr"
    actor_role: str = "Auditeur"
    comment: str = ""
    edited_briefs: list[dict[str, Any]] | None = None


class Gate4Payload(BaseModel):
    expert_slot: str  # AVOCAT | CONSULTANT
    decision: str
    comment: str = ""
    actor_id: str = "expert@deloitte.fr"
    actor_role: str = "Avocat"


class Gate5Payload(BaseModel):
    decision: str  # Approve | Edit | Reject
    actor_id: str = "auditeur.senior@deloitte.fr"
    actor_role: str = "Auditeur"
    comment: str = ""
    edited_conclusion: str | None = None


class BulkApprovePayload(BaseModel):
    gate: str = "GATE_2"
    actor_id: str = "auditeur.senior@deloitte.fr"
    actor_role: str = "Auditeur"


def _ingest_path(tenant_id: str, path: Path) -> list[AuditCase]:
    sid = f"sess-{uuid.uuid4().hex[:8]}"
    rel = str(path.relative_to(DATA_ROOT.parent))
    try:
        items = normalize_csv_file(tenant_id, sid, path) if path.suffix.lower() == ".csv" else [normalize_txt_file(tenant_id, sid, path)]
        created: list[AuditCase] = []
        for canon, loc in items:
            case = execute_audit_harness(canon, loc, session_id=sid)
            audit_logger.save_case(case)
            created.append(case)
        return created
    except Gate1BlockError as exc:
        cid = f"{tenant_id}:QUARANTINE:{path.name}"
        raw_text = path.read_text(encoding="utf-8", errors="replace")
        q_case = AuditCase(
            case_id=cid,
            session_id=sid,
            tenant_id=tenant_id,
            status="QUARANTINED",
            invoice=CanonicalInvoice(
                tenant_id=tenant_id,
                invoice_id=f"QUARANTINE:{path.name}",
                supplier="BLOQUÉ (Gate 1)",
                customer=tenant_id,
                is_intercompany=False,
                amount_ht=0.0,
                vat_rate=0.0,
                amount_ttc=0.0,
                invoice_date="",
                service_date="",
                ledger_entry=LedgerEntry(account="-", amount=0.0, period="-"),
                description=f"Quarantaine Model Armor : {exc.reason}",
                source_file=rel,
            ),
            scope_files=[rel],
            confidence_score=0,
            score_color="red",
            harness_step="QUARANTINED",
            last_action=f"Bloqué par Model Armor ({exc.action})",
            quarantine_reason=exc.reason,
            quarantine_raw_text=raw_text,
        )
        _QUARANTINE_LOCATORS[cid] = {"file": rel, "locator": exc.locator, "reason": exc.reason}
        audit_logger.record_event(
            session_id=sid,
            tenant_id=tenant_id,
            case_id=cid,
            gate="GATE_1",
            actor_type="system",
            actor_id="ModelArmor",
            actor_role="System",
            action="MODEL_ARMOR_BLOCK",
            decision="BLOCK",
            comment=q_case.quarantine_reason,
            after={"status": "QUARANTINED", "file": rel, "locator": exc.locator},
        )
        audit_logger.save_case(q_case)
        return [q_case]


def seed_demo_cases() -> None:
    audit_logger.reset_memory()
    _QUARANTINE_LOCATORS.clear()
    _ingest_path("CLIENT_A", DATA_ROOT / "inputs" / "CLIENT_A" / "erp_export.csv")
    _ingest_path("CLIENT_B", DATA_ROOT / "inputs" / "CLIENT_B" / "facture_0412.txt")
    _ingest_path("CLIENT_B", DATA_ROOT / "inputs" / "CLIENT_B" / "facture_poison.txt")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    seed_demo_cases()
    yield


app = FastAPI(title="AuditBridge — Deloitte x Google Cloud", version="3.0.0", lifespan=lifespan)


@app.get("/", response_class=HTMLResponse)
async def serve_ui() -> HTMLResponse:
    return HTMLResponse(_STATIC_INDEX.read_text(encoding="utf-8"))


@app.get("/presentation", response_class=HTMLResponse)
async def serve_presentation() -> HTMLResponse:
    return HTMLResponse(_STATIC_PRESENTATION.read_text(encoding="utf-8"))


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "storage": audit_logger.metrics.get("storage_backend", "memory")}


@app.post("/api/seed")
async def reseed_demo() -> dict[str, Any]:
    seed_demo_cases()
    cases = audit_logger.list_cases()
    return {"seeded": len(cases), "cases": [c.model_dump() for c in cases]}


@app.get("/api/clients")
async def get_clients() -> dict[str, Any]:
    return {"CLIENT_A": load_passport("CLIENT_A"), "CLIENT_B": load_passport("CLIENT_B")}


@app.get("/api/cases")
async def list_cases(tenant_id: str | None = None) -> list[dict[str, Any]]:
    return [c.model_dump() for c in audit_logger.list_cases(tenant_id=tenant_id)]


@app.post("/api/tenants/{tenant_id}/upload")
async def upload_input(tenant_id: str, file: UploadFile = File(...)) -> dict[str, Any]:
    name = Path(file.filename or "uploaded.txt").name
    dest_dir = DATA_ROOT / "inputs" / tenant_id
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / name
    dest.write_bytes(await file.read())
    created = _ingest_path(tenant_id, dest)
    return {"cases": [c.model_dump() for c in created]}


def _get_case_or_404(case_id: str) -> AuditCase:
    case = audit_logger.get_case(case_id)
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")
    return case


@app.post("/api/cases/{case_id:path}/gate1")
async def gate1_submit(case_id: str, payload: Gate1Payload) -> dict[str, Any]:
    case = _get_case_or_404(case_id)
    try:
        return gate1_decide(case, payload.decision, payload.actor_id, payload.actor_role, payload.comment).model_dump()
    except HarnessPermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/cases/{case_id:path}/gate2")
async def gate2_submit(case_id: str, payload: Gate2Payload) -> dict[str, Any]:
    case = _get_case_or_404(case_id)
    try:
        return gate2_decide(
            case,
            payload.decision,
            payload.actor_id,
            payload.actor_role,
            payload.comment,
            scope_files=payload.scope_files,
            rule_overrides=payload.rule_overrides,
            evidence_additions=payload.evidence_additions,
        ).model_dump()
    except HarnessPermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/cases/{case_id:path}/gate3")
async def gate3_submit(case_id: str, payload: Gate3Payload) -> dict[str, Any]:
    case = _get_case_or_404(case_id)
    try:
        return gate3_decide(
            case,
            payload.decision,
            payload.actor_id,
            payload.actor_role,
            payload.comment,
            edited_briefs=payload.edited_briefs,
        ).model_dump()
    except HarnessPermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except (ValueError, HarnessSecurityError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/cases/{case_id:path}/gate4")
async def gate4_submit(case_id: str, payload: Gate4Payload) -> dict[str, Any]:
    case = _get_case_or_404(case_id)
    try:
        return gate4_expert_answer(
            case,
            payload.expert_slot,
            payload.decision,
            payload.comment,
            payload.actor_id,
            payload.actor_role,
        ).model_dump()
    except HarnessPermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/cases/{case_id:path}/gate5")
async def gate5_submit(case_id: str, payload: Gate5Payload) -> dict[str, Any]:
    case = _get_case_or_404(case_id)
    try:
        return gate5_decide(
            case,
            payload.decision,
            payload.actor_id,
            payload.actor_role,
            payload.comment,
            edited_conclusion=payload.edited_conclusion,
        ).model_dump()
    except HarnessPermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/tenants/{tenant_id}/bulk-approve")
async def bulk_approve_endpoint(tenant_id: str, payload: BulkApprovePayload) -> dict[str, Any]:
    try:
        count = bulk_approve_green(tenant_id, payload.gate, payload.actor_id, payload.actor_role)
        return {"approved_count": count, "gate": payload.gate}
    except HarnessPermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/cases/{case_id:path}/verify-chain")
async def verify_case_chain(case_id: str) -> dict[str, Any]:
    _get_case_or_404(case_id)
    return audit_logger.verify_chain(case_id)


@app.get("/api/cases/{case_id:path}/export/md", response_class=PlainTextResponse)
async def export_md(case_id: str) -> PlainTextResponse:
    case = _get_case_or_404(case_id)
    if case.status != "DOCUMENTED":
        raise HTTPException(status_code=409, detail="La fiche de contrôle n'est disponible qu'après validation Gate 5 (DOCUMENTED).")
    return PlainTextResponse(
        case.control_sheet_md,
        media_type="text/markdown",
        headers={"Content-Disposition": f'attachment; filename="fiche_{case.invoice.invoice_id}.md"'},
    )


@app.get("/api/cases/{case_id:path}/export/docx")
async def export_docx(case_id: str) -> Response:
    case = _get_case_or_404(case_id)
    if case.status != "DOCUMENTED":
        raise HTTPException(status_code=409, detail="La fiche de contrôle n'est disponible qu'après validation Gate 5 (DOCUMENTED).")
    data = render_control_sheet_docx(case)
    return Response(
        content=data,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f'attachment; filename="fiche_{case.invoice.invoice_id}.docx"'},
    )


@app.get("/api/events")
async def get_events(
    case_id: str | None = None,
    actor_id: str | None = None,
    actor_role: str | None = None,
    gate: str | None = None,
    action: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
) -> list[dict[str, Any]]:
    events = audit_logger.list_events(
        case_id=case_id,
        actor_id=actor_id,
        actor_role=actor_role,
        gate=gate,
        action=action,
        date_from=date_from,
        date_to=date_to,
    )
    return [e.model_dump() for e in events]


@app.get("/api/events/export/csv")
async def export_events_csv_endpoint(
    case_id: str | None = None,
    actor_id: str | None = None,
    actor_role: str | None = None,
    gate: str | None = None,
    action: str | None = None,
) -> PlainTextResponse:
    csv_text = audit_logger.export_events_csv(
        case_id=case_id,
        actor_id=actor_id,
        actor_role=actor_role,
        gate=gate,
        action=action,
    )
    return PlainTextResponse(
        csv_text,
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="audit_events.csv"'},
    )


@app.get("/api/events/stream")
@app.get("/api/logs/stream")
async def stream_events() -> EventSourceResponse:
    q = audit_logger.subscribe()

    async def gen():
        try:
            for evt in audit_logger.list_events()[-40:]:
                yield {"event": "audit_event", "data": json.dumps(evt.model_dump())}
            while True:
                try:
                    evt = await asyncio.wait_for(q.get(), timeout=15.0)
                    yield {"event": "audit_event", "data": json.dumps(evt.model_dump())}
                except asyncio.TimeoutError:
                    yield {"event": "ping", "data": "{}"}
        finally:
            audit_logger.unsubscribe(q)

    return EventSourceResponse(gen())


@app.get("/api/files")
async def read_source_file(path: str = Query(..., description="Relative path inside data/")) -> dict[str, Any]:
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
        "logs": [e.model_dump() for e in audit_logger.list_events()[-50:]],
    }
