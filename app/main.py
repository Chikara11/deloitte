"""FastAPI application for AuditBridge (Deloitte x Google Cloud)."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Header, HTTPException, UploadFile
from fastapi.responses import HTMLResponse, PlainTextResponse
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from app.agents.models import AuditCase, CanonicalInvoice, LedgerEntry, SecurityMeta
from app.agents.orchestrator import apply_auditor_gate3, apply_expert_response, evaluate_invoice
from app.data.audit_logger import audit_logger
from app.data.ingest import QuarantineError, ingest_csv_to_canonical, ingest_file, ingest_pdf_to_canonical
from app.data.passports import PASSPORTS
from app.infra.pubsub import publish_case_evaluated
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


_MAX_UPLOAD_BYTES = 5 * 1024 * 1024
_ALLOWED_EXT = (".pdf", ".csv")
_GATE2_ROLES = ("AVOCAT", "CONSULTANT")
_GATE3_DECISIONS = ("VALIDER", "REJETER")


def _require_tenant(tenant_id: str) -> None:
    """Gate 1: refuse any tenant without a Client Passport (no implicit tenants)."""
    if tenant_id not in PASSPORTS:
        audit_logger.log(tenant_id, "gate1_cyber", "UNKNOWN_TENANT_BLOCK", "CRITICAL", {"tenant_id": tenant_id})
        raise HTTPException(status_code=404, detail=f"Unknown tenant '{tenant_id}'.")


def _get_case_for_tenant(case_id: str, x_tenant_id: str) -> AuditCase:
    """Zero-Trust: a case is only reachable by the tenant that owns it (X-Tenant-Id header)."""
    case = _CASES.get(case_id)
    if case is None:
        raise HTTPException(status_code=404, detail="Case not found")
    if x_tenant_id != case.tenant_id:
        audit_logger.log(
            case.tenant_id,
            "gate1_cyber",
            "TENANT_ISOLATION_BLOCK",
            "CRITICAL",
            {"case_id": case_id, "caller_tenant": x_tenant_id, "owner_tenant": case.tenant_id},
        )
        raise HTTPException(status_code=403, detail="Tenant isolation: this case belongs to another client.")
    return case


@app.get("/", response_class=HTMLResponse)
async def serve_ui() -> HTMLResponse:
    return HTMLResponse(_STATIC_INDEX.read_text(encoding="utf-8"))


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/passports")
async def list_passports() -> dict[str, Any]:
    return {k: v.model_dump() for k, v in PASSPORTS.items()}


def _ingest_and_evaluate(tenant_id: str, path: Path) -> list[AuditCase]:
    try:
        invoices = ingest_file(tenant_id, path)
        out: list[AuditCase] = []
        for inv in invoices:
            case = evaluate_invoice(inv)
            _CASES[case.case_id] = case
            publish_case_evaluated(case)
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
            fiche_controle_md=f"# QUARANTAINE SÉCURITÉ — {path.name}\n\n- **Raison :** {qerr.reason}\n",
        )
        _CASES[q_case.case_id] = q_case
        publish_case_evaluated(q_case)
        return [q_case]


@app.post("/api/tenants/{tenant_id}/load-demo")
async def load_demo(tenant_id: str, case_type: str = "all") -> dict[str, Any]:
    """Generate and run demo cases (normal | interco | poisoned | all)."""
    _require_tenant(tenant_id)
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
    _require_tenant(tenant_id)
    name = Path(file.filename or "facture.pdf").name
    data = await file.read(_MAX_UPLOAD_BYTES + 1)

    def _reject(status: int, reason: str) -> HTTPException:
        audit_logger.log(tenant_id, "gate1_cyber", "UPLOAD_REJECTED", "WARNING", {"source_file": name, "reason": reason})
        return HTTPException(status_code=status, detail={"event_type": "UPLOAD_REJECTED", "reason": reason})

    if len(data) > _MAX_UPLOAD_BYTES:
        raise _reject(413, "Fichier > 5 Mo refusé.")
    if not name.lower().endswith(_ALLOWED_EXT):
        raise _reject(415, "Seuls les fichiers .pdf et .csv sont acceptés.")
    if name.lower().endswith(".pdf") and not data.startswith(b"%PDF"):
        raise _reject(415, "Signature PDF invalide (fichier déguisé).")
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
            publish_case_evaluated(c)
            cases.append(c.model_dump())
        return {"tenant_id": tenant_id, "cases": cases}
    except QuarantineError as qerr:
        raise HTTPException(status_code=403, detail={"event_type": qerr.event_type, "reason": qerr.reason})
    except (ValueError, UnicodeDecodeError, KeyError) as exc:
        raise _reject(422, f"Document illisible ou non conforme au Passeport Client : {type(exc).__name__}")


@app.post("/api/tenants/{tenant_id}/test-isolation")
async def test_tenant_isolation(tenant_id: str) -> dict[str, Any]:
    """Intentionally feed a CLIENT_A file into CLIENT_B to prove Gate 1 isolation."""
    _require_tenant(tenant_id)
    files = {p.name: p for p in generate_demo_files(_SAMPLE_DIR)}
    wrong_file = files["CLIENT_A_export_erp.csv"] if tenant_id == "CLIENT_B" else files["CLIENT_B_facture_0412.pdf"]
    cases = _ingest_and_evaluate(tenant_id, wrong_file)
    return {"tenant_id": tenant_id, "blocked": True, "cases": [c.model_dump() for c in cases]}


@app.get("/api/tenants/{tenant_id}/cases")
async def list_cases(tenant_id: str) -> list[dict[str, Any]]:
    _require_tenant(tenant_id)
    return [c.model_dump() for c in _CASES.values() if c.tenant_id == tenant_id]


@app.post("/api/cases/{case_id:path}/gate2")
async def submit_gate2(case_id: str, req: Gate2Request, x_tenant_id: str = Header(...)) -> dict[str, Any]:
    case = _get_case_for_tenant(case_id, x_tenant_id)
    role = req.role.upper()
    if role not in _GATE2_ROLES:
        raise HTTPException(status_code=422, detail=f"Role must be one of {_GATE2_ROLES}.")
    if case.status != "ANOMALIE":
        raise HTTPException(status_code=409, detail=f"Gate 2 not open for a case in status {case.status}.")
    brief = next((b for b in case.micro_briefs if b.role == role), None)
    if brief is None or req.decision not in brief.options:
        raise HTTPException(status_code=422, detail=f"Decision must be one of {brief.options if brief else []}.")
    updated = apply_expert_response(case, req.role, req.decision, req.comment, req.responder_id)
    _CASES[case_id] = updated
    return updated.model_dump()


@app.post("/api/cases/{case_id:path}/gate3")
async def submit_gate3(case_id: str, req: Gate3Request, x_tenant_id: str = Header(...)) -> dict[str, Any]:
    case = _get_case_for_tenant(case_id, x_tenant_id)
    if req.decision.upper() not in _GATE3_DECISIONS:
        raise HTTPException(status_code=422, detail=f"Decision must be one of {_GATE3_DECISIONS}.")
    if case.status == "QUARANTINE":
        raise HTTPException(status_code=409, detail="Document en quarantaine Gate 1 : aucune conclusion possible.")
    if case.auditor_gate3 is not None:
        raise HTTPException(status_code=409, detail="Gate 3 déjà signée : la conclusion est immuable.")
    missing = [b.role for b in case.micro_briefs if b.role not in case.expert_responses]
    if missing:
        audit_logger.log(case.tenant_id, "gate3_auditeur", "GATE3_PREMATURE_BLOCK", "WARNING",
                         {"invoice_id": case.invoice.invoice_id, "missing_experts": missing})
        raise HTTPException(status_code=409, detail=f"Gate 2 incomplète : en attente de {', '.join(missing)}.")
    updated = apply_auditor_gate3(case, req.decision, req.auditor_id, req.comment)
    _CASES[case_id] = updated
    return updated.model_dump()


@app.get("/api/cases/{case_id:path}/fiche", response_class=PlainTextResponse)
async def export_fiche(case_id: str, tenant: str = "") -> PlainTextResponse:
    case = _get_case_for_tenant(case_id, tenant)
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


@app.get("/api/tenants/{tenant_id}/audit/verify")
async def verify_audit_chain(tenant_id: str, simulate_tamper: bool = False) -> dict[str, Any]:
    """Governance: recompute the SHA-256 hash chain of the tenant's audit trail."""
    _require_tenant(tenant_id)
    res = audit_logger.verify(tenant_id, simulate_tamper=simulate_tamper)
    if not simulate_tamper:
        audit_logger.log(
            tenant_id,
            "governance",
            "AUDIT_CHAIN_VERIFIED" if res["valid"] else "AUDIT_CHAIN_BROKEN",
            "INFO" if res["valid"] else "CRITICAL",
            {"events_checked": res["events_checked"], "broken_at": res["broken_at"]},
        )
    return res


@app.get("/api/tenants/{tenant_id}/events")
async def stream_events(tenant_id: str) -> EventSourceResponse:
    _require_tenant(tenant_id)
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
