"""Multi-agent orchestrator: parallel IAM-scoped fan-out -> Skeptic Gate -> Price Chip."""

from __future__ import annotations

import asyncio

from app.agents.forensic_agent import run_forensic_agent
from app.agents.legal_agent import run_legal_agent
from app.agents.models import DealReport, Finding
from app.agents.price_chip import compute_price_chips
from app.agents.quant_agent import run_quant_agent
from app.agents.skeptic_agent import verify_findings
from app.data.audit_logger import audit_logger


async def run_due_diligence(deal_id: str) -> DealReport:
    """Execute the 3 specialist agents in parallel, verify with Skeptic, and price risks."""
    legal_task = asyncio.to_thread(run_legal_agent, deal_id)
    quant_task = asyncio.to_thread(run_quant_agent, deal_id)
    forensic_task = asyncio.to_thread(run_forensic_agent, deal_id)

    legal_findings, quant_findings, (forensic_findings, graph) = await asyncio.gather(
        legal_task, quant_task, forensic_task
    )

    # Convert any Model Armor quarantine events for this deal into a Cyber/Forensic finding
    tamper_events = [
        e
        for e in audit_logger.list_events(deal_id)
        if e.event_type == "MODEL_ARMOR_BLOCK"
    ]
    cyber_findings: list[Finding] = []
    if tamper_events:
        first = tamper_events[0].details
        cyber_findings.append(
            Finding(
                finding_id="CYB-01",
                agent="model-armor",
                category="CYBER_TAMPERING",
                severity="CRITICAL",
                title="Active Seller Document Tampering (Indirect Prompt Injection Blocked)",
                summary=(
                    f"Model Armor intercepted and quarantined {len(tamper_events)} malicious instruction "
                    f"chunk(s) in {first.get('doc_name', 'uploaded PDF')} (p.{first.get('page_num', 1)})."
                ),
                doc_name=first.get("doc_name"),
                page_num=first.get("page_num"),
                exact_quote=first.get("snippet_preview"),
            )
        )

    all_candidates = legal_findings + quant_findings + forensic_findings + cyber_findings
    verified = verify_findings(deal_id, all_candidates, max_retries=2)
    status, total_chip, adjusted_price, chips = compute_price_chips(verified)

    return DealReport(
        deal_id=deal_id,
        deal_status=status,
        proposed_price_eur=200_000_000.0,
        adjusted_price_eur=adjusted_price,
        total_price_chip_eur=total_chip,
        price_chips=chips,
        findings=verified,
        entity_graph=graph,
        tampering_detected=bool(tamper_events),
        pii_unmasked=False,
    )
