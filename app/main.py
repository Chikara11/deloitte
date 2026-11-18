"""FastAPI application for the Zero-Trust M&A Forensic War Room."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from app.agents.models import DealReport
from app.agents.orchestrator import run_due_diligence
from app.data.audit_logger import audit_logger
from app.data.ingest import ingest_csv_bytes, ingest_path, ingest_pdf_bytes
from app.data.vector_store import vector_store
from app.security.dlp_tokenizer import dlp_tokenizer
from app.security.iam_impersonator import probe_cross_scope_access
from scripts.generate_data import generate_data_room

app = FastAPI(title="Deloitte x GCP Zero-Trust M&A Forensic War Room", version="0.1.0")

_REPORTS: dict[str, DealReport] = {}
_STATIC_INDEX = Path(__file__).parent / "static" / "index.html"
_SAMPLE_DIR = Path(__file__).resolve().parent.parent / "sample_data_room"


class BreakGlassRequest(BaseModel):
    partner_id: str
    reason: str = "Partner sign-off for final M&A Executive Memo"


@app.get("/", response_class=HTMLResponse)
async def serve_ui() -> HTMLResponse:
    """Serve the 2-column War Room & Governance HUD."""
    return HTMLResponse(_STATIC_INDEX.read_text(encoding="utf-8"))


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/deals/{deal_id}/load-sample")
async def load_sample_data_room(deal_id: str, include_poisoned: bool = False) -> dict[str, Any]:
    """Generate (if needed) and ingest the synthetic NovaLogistics Data Room."""
    vector_store.clear_deal(deal_id)
    _REPORTS.pop(deal_id, None)

    files = generate_data_room(_SAMPLE_DIR)
    results = []
    for fp in sorted(files):
        if not include_poisoned and "Poisoned" in fp.name:
            continue
        results.append(ingest_path(deal_id, fp))
    return {"deal_id": deal_id, "ingested": results}


@app.post("/api/deals/{deal_id}/upload")
async def upload_file(deal_id: str, file: UploadFile = File(...)) -> dict[str, Any]:
    """Ingest a live uploaded PDF or CSV into the quarantine shield."""
    data = await file.read()
    name = file.filename or "uploaded.pdf"
    if name.lower().endswith(".csv"):
        res = ingest_csv_bytes(deal_id, name, data)
    else:
        res = ingest_pdf_bytes(deal_id, name, data)
    return {"deal_id": deal_id, "ingested": res}


@app.post("/api/deals/{deal_id}/analyze", response_model=DealReport)
async def analyze_deal(deal_id: str) -> DealReport:
    """Run the 3 IAM-scoped agents in parallel, verify with Skeptic, and price risks."""
    report = await run_due_diligence(deal_id)
    _REPORTS[deal_id] = report
    return report


@app.post("/api/deals/{deal_id}/break-glass")
async def break_glass_unmask(deal_id: str, req: BreakGlassRequest) -> dict[str, Any]:
    """Partner HITL approval: unmask deterministic DLP tokens and log attribution."""
    report = _REPORTS.get(deal_id)
    if report is None:
        raise HTTPException(status_code=404, detail="Run /analyze before Break-Glass unmasking.")

    for f in report.findings:
        f.title = dlp_tokenizer.unmask(f.title)
        f.summary = dlp_tokenizer.unmask(f.summary)
        if f.exact_quote:
            f.exact_quote = dlp_tokenizer.unmask(f.exact_quote)

    for node in report.entity_graph.nodes:
        node.label = dlp_tokenizer.unmask(node.label)

    report.pii_unmasked = True
    report.partner_signoff = {
        "partner_id": req.partner_id,
        "reason": req.reason,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    audit_logger.log(
        deal_id=deal_id,
        agent_name="partner_hitl",
        event_type="BREAK_GLASS_UNMASK",
        severity="WARNING",
        details={"partner_id": req.partner_id, "reason": req.reason, "tokens_revealed": len(dlp_tokenizer.reveal_vault())},
    )
    return {"report": report.model_dump(), "unmasked_vault": dlp_tokenizer.reveal_vault()}


@app.post("/api/security/iam-probe")
async def run_iam_probe(deal_id: str = "nova_logistics_2025") -> dict[str, Any]:
    """Trigger intentional cross-scope BigQuery access from sa-legal to prove 403 enforcement."""
    res = probe_cross_scope_access()
    audit_logger.log(
        deal_id=deal_id,
        agent_name="sa-legal",
        event_type="IAM_403_BLOCK" if not res.allowed else "IAM_VIOLATION",
        severity="CRITICAL" if not res.allowed else "ERROR",
        details={
            "actor_sa": res.actor_sa,
            "target": res.target_resource,
            "status_code": res.status_code,
            "message": res.message,
            "real_gcp": res.real_gcp,
        },
    )
    return res.__dict__


@app.get("/api/deals/{deal_id}/audit")
async def get_audit_logs(deal_id: str) -> list[dict[str, Any]]:
    """Return all governance events for the deal."""
    return [e.model_dump() for e in audit_logger.list_events(deal_id)]


@app.get("/api/deals/{deal_id}/events")
async def stream_events(deal_id: str) -> EventSourceResponse:
    """Server-Sent Events stream of live security & agent governance events."""
    q = audit_logger.subscribe()

    async def event_gen():
        try:
            for existing in audit_logger.list_events(deal_id)[-25:]:
                yield {"event": "audit", "data": json.dumps(existing.model_dump())}
            while True:
                try:
                    evt = await asyncio.wait_for(q.get(), timeout=15.0)
                    if evt.deal_id == deal_id:
                        yield {"event": "audit", "data": json.dumps(evt.model_dump())}
                except asyncio.TimeoutError:
                    yield {"event": "ping", "data": "{}"}
        finally:
            audit_logger.unsubscribe(q)

    return EventSourceResponse(event_gen())
