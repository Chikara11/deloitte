"""FastAPI application for AuditBridge (Deloitte x Google Cloud)."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import HTMLResponse, PlainTextResponse
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from app.agents.models import AuditCase, CanonicalInvoice, LedgerEntry, SecurityMeta
from app.agents.orchestrator import apply_auditor_gate3, apply_expert_response, evaluate_invoice
from app.data.audit_logger import audit_logger
from app.data.governance_refs import PLATFORM_GOVERNANCE_REFS, RULE_REFERENCES
from app.data.ingest import QuarantineError, ingest_csv_to_canonical, ingest_file, ingest_pdf_to_canonical
from app.data.passports import PASSPORTS
from app.security.iam_impersonator import probe_cross_scope_access
from scripts.generate_data import generate_demo_files

app = FastAPI(title="AuditBridge — Deloitte x Google Cloud", version="1.0.0")

_CASES: dict[str, AuditCase] = {}
_STATIC_INDEX = Path(__file__).parent / "static" / "index.html"
_SAMPLE_DIR = Path(__file__).resolve().parent.parent / "sample_data_room"


class Gate2Request(BaseModel):
    role: str  # AVOCAT | CONSULTANT
    decision: str
    comment: str = ""
    responder_id: str = "expert@deloitte.fr"


class Gate3Request(BaseModel):
    decision: str  # VALIDER | REJETER
    auditor_id: str = "auditeur.senior@deloitte.fr"
    comment: str = ""


@app.get("/", response_class=HTMLResponse)
async def serve_ui() -> HTMLResponse:
    return HTMLResponse(_STATIC_INDEX.read_text(encoding="utf-8"))


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/passports")
async def list_passports() -> dict[str, Any]:
    return {k: v.model_dump() for k, v in PASSPORTS.items()}


@app.get("/api/governance/references")
async def list_governance_references() -> dict[str, Any]:
    """Return all public EU AI Act, RGPD, and Audit/Accounting references."""
    return {
        "platform": [r.model_dump() for r in PLATFORM_GOVERNANCE_REFS],
        "rules": {k: v.model_dump() for k, v in RULE_REFERENCES.items()},
    }


def _ingest_and_evaluate(tenant_id: str, path: Path) -> list[AuditCase]:
    try:
        invoices = ingest_file(tenant_id, path)
        out: list[AuditCase] = []
        for inv in invoices:
            case = evaluate_invoice(inv)
            _CASES[case.case_id] = case
            out.append(case)
        return out
    except QuarantineError as qerr:
        q_inv = CanonicalInvoice(
            tenant_id=tenant_id,
            invoice_id="QUARANTINE",
            supplier="[BLOQUÉ GATE 1]",
            customer=tenant_id,
            is_intercompany=False,
            amount_ht=0.0,
            vat_rate=0.0,
            amount_ttc=0.0,
            invoice_date="2026-12-31",
            service_date="2026-12-31",
            ledger_entry=LedgerEntry(account="N/A", amount=0.0, period="2026-12"),
            description=qerr.reason,
            source_file=path.name,
            security=SecurityMeta(model_armor="blocked", pii_masked=0, tenant_verified=qerr.event_type != "TENANT_ISOLATION_BLOCK"),
        )
        q_case = AuditCase(
            case_id=f"{tenant_id}:QUARANTINE:{path.name}",
            tenant_id=tenant_id,
            invoice=q_inv,
            status="QUARANTINE",
            auditor_explanation=qerr.reason,
            confidence_score=0,
            score_color="RED",
            recommendation=f"BLOQUÉ À LA GATE 1 ({qerr.event_type}) : Document mis en quarantaine.",
            governance_references=[r.model_dump() for r in PLATFORM_GOVERNANCE_REFS],
            fiche_controle_md=(
                f"# QUARANTAINE SÉCURITÉ — {path.name}\n\n"
                f"- **Raison :** {qerr.reason}\n"
                "- **Référence :** Règlement (UE) 2024/1689 (EU AI Act) Art. 9 & Art. 15 • RGPD Art. 32\n"
            ),
        )
        _CASES[q_case.case_id] = q_case
        return [q_case]


@app.post("/api/tenants/{tenant_id}/load-demo")
async def load_demo(tenant_id: str, case_type: str = "all") -> dict[str, Any]:
    """Generate and run demo cases (normal | interco | poisoned | all)."""
    files = {p.name: p for p in generate_demo_files(_SAMPLE_DIR)}
    # Clear previous cases for this tenant
    for k in [cid for cid, c in _CASES.items() if c.tenant_id == tenant_id]:
        del _CASES[k]

    targets: list[Path] = []
    if tenant_id == "CLIENT_A" or case_type == "normal":
        targets = [files["CLIENT_A_export_erp.csv"]]
    elif case_type == "interco":
        targets = [files["CLIENT_B_facture_0412.pdf"]]
    elif case_type == "poisoned":
        targets = [files["CLIENT_B_facture_0412.pdf"], files["CLIENT_B_facture_piegee_0999.pdf"]]
    else:
        targets = [files["CLIENT_B_facture_0412.pdf"], files["CLIENT_B_facture_piegee_0999.pdf"]]

    created: list[dict[str, Any]] = []
    for p in targets:
        for c in _ingest_and_evaluate(tenant_id, p):
            created.append(c.model_dump())
    return {"tenant_id": tenant_id, "cases": created}


@app.post("/api/tenants/{tenant_id}/upload")
async def upload_invoice(tenant_id: str, file: UploadFile = File(...)) -> dict[str, Any]:
    data = await file.read()
    name = file.filename or "facture.pdf"
    try:
        invs = (
            ingest_csv_to_canonical(tenant_id, name, data)
            if name.lower().endswith(".csv")
            else ingest_pdf_to_canonical(tenant_id, name, data)
        )
        cases = []
        for inv in invs:
            c = evaluate_invoice(inv)
            _CASES[c.case_id] = c
            cases.append(c.model_dump())
        return {"tenant_id": tenant_id, "cases": cases}
    except QuarantineError as qerr:
        raise HTTPException(status_code=403, detail={"event_type": qerr.event_type, "reason": qerr.reason})


@app.post("/api/tenants/{tenant_id}/test-isolation")
async def test_tenant_isolation(tenant_id: str) -> dict[str, Any]:
    """Intentionally feed a CLIENT_A file into CLIENT_B to prove Gate 1 isolation."""
    files = {p.name: p for p in generate_demo_files(_SAMPLE_DIR)}
    wrong_file = files["CLIENT_A_export_erp.csv"] if tenant_id == "CLIENT_B" else files["CLIENT_B_facture_0412.pdf"]
    cases = _ingest_and_evaluate(tenant_id, wrong_file)
    return {"tenant_id": tenant_id, "blocked": True, "cases": [c.model_dump() for c in cases]}


@app.get("/api/tenants/{tenant_id}/cases")
async def list_cases(tenant_id: str) -> list[dict[str, Any]]:
    return [c.model_dump() for c in _CASES.values() if c.tenant_id == tenant_id]


@app.post("/api/cases/{case_id:path}/gate2")
async def submit_gate2(case_id: str, req: Gate2Request) -> dict[str, Any]:
    case = _CASES.get(case_id)
    if case is None:
        raise HTTPException(status_code=404, detail="Case not found")
    updated = apply_expert_response(case, req.role, req.decision, req.comment, req.responder_id)
    _CASES[case_id] = updated
    return updated.model_dump()


@app.post("/api/cases/{case_id:path}/gate3")
async def submit_gate3(case_id: str, req: Gate3Request) -> dict[str, Any]:
    case = _CASES.get(case_id)
    if case is None:
        raise HTTPException(status_code=404, detail="Case not found")
    updated = apply_auditor_gate3(case, req.decision, req.auditor_id, req.comment)
    _CASES[case_id] = updated
    return updated.model_dump()


@app.get("/api/cases/{case_id:path}/fiche", response_class=PlainTextResponse)
async def export_fiche(case_id: str) -> PlainTextResponse:
    case = _CASES.get(case_id)
    if case is None:
        raise HTTPException(status_code=404, detail="Case not found")
    return PlainTextResponse(case.fiche_controle_md, media_type="text/markdown")


@app.post("/api/security/iam-probe")
async def run_iam_probe(tenant_id: str = "CLIENT_B") -> dict[str, Any]:
    res = probe_cross_scope_access()
    audit_logger.log(
        deal_id=tenant_id,
        agent_name="sa-legal",
        event_type="IAM_403_BLOCK" if not res.allowed else "IAM_VIOLATION",
        severity="CRITICAL" if not res.allowed else "ERROR",
        details={"actor_sa": res.actor_sa, "target": res.target_resource, "status_code": res.status_code, "message": res.message},
    )
    return res.__dict__


@app.get("/api/tenants/{tenant_id}/events")
async def stream_events(tenant_id: str) -> EventSourceResponse:
    q = audit_logger.subscribe()

    async def event_gen():
        try:
            for existing in audit_logger.list_events(tenant_id)[-25:]:
                yield {"event": "audit", "data": json.dumps(existing.model_dump())}
            while True:
                try:
                    evt = await asyncio.wait_for(q.get(), timeout=15.0)
                    if evt.deal_id == tenant_id:
                        yield {"event": "audit", "data": json.dumps(evt.model_dump())}
                except asyncio.TimeoutError:
                    yield {"event": "ping", "data": "{}"}
        finally:
            audit_logger.unsubscribe(q)

    return EventSourceResponse(event_gen())
