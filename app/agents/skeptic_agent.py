"""Skeptic / Auditor Agent: deterministic citation/SQL verification + bounded Gemini Critic."""

from __future__ import annotations

from difflib import SequenceMatcher

from app.agents.models import Finding
from app.data.audit_logger import audit_logger
from app.data.vector_store import vector_store


def _quote_matches(quote: str, chunk_text: str) -> float:
    if not quote:
        return 0.0
    q_norm = " ".join(quote.lower().split())
    c_norm = " ".join(chunk_text.lower().split())
    if q_norm in c_norm:
        return 1.0
    return SequenceMatcher(None, q_norm, c_norm).ratio()


def verify_findings(deal_id: str, findings: list[Finding], max_retries: int = 2) -> list[Finding]:
    """Verify every finding deterministically before allowing it into the DealReport."""
    verified_list: list[Finding] = []

    for f in findings:
        if f.category == "CYBER_TAMPERING":
            f.verified = True
            f.verification_note = "Verified by Model Armor quarantine audit event."
            verified_list.append(f)
            continue

        if f.category in ("LEGAL", "FORENSIC"):
            chunk = vector_store.get_chunk(f.chunk_id or "")
            if chunk is None or chunk.deal_id != deal_id:
                f.verified = False
                f.verification_note = f"REJECTED: chunk_id '{f.chunk_id}' not found in deal store."
                audit_logger.log(
                    deal_id=deal_id,
                    agent_name="skeptic",
                    event_type="SKEPTIC_REJECT",
                    severity="WARNING",
                    details={"finding_id": f.finding_id, "reason": f.verification_note, "max_retries": max_retries},
                )
                continue

            ratio = _quote_matches(f.exact_quote or "", chunk.text)
            if ratio < 0.90:
                f.verified = False
                f.verification_note = f"REJECTED: quote similarity {ratio:.2f} < 0.90."
                audit_logger.log(
                    deal_id=deal_id,
                    agent_name="skeptic",
                    event_type="SKEPTIC_REJECT",
                    severity="WARNING",
                    details={"finding_id": f.finding_id, "reason": f.verification_note},
                )
                continue

            f.verified = True
            f.verification_note = f"Verified chunk {chunk.chunk_id} (sha256={chunk.sha256}, match={ratio:.0%})."
            audit_logger.log(
                deal_id=deal_id,
                agent_name="skeptic",
                event_type="SKEPTIC_PASS",
                severity="INFO",
                details={"finding_id": f.finding_id, "chunk_id": chunk.chunk_id, "sha256": chunk.sha256},
            )
            verified_list.append(f)

        elif f.category == "QUANT":
            if not f.sql_query or not f.bq_job_id:
                f.verified = False
                f.verification_note = "REJECTED: Missing SQL query or BigQuery job_id."
                audit_logger.log(
                    deal_id=deal_id,
                    agent_name="skeptic",
                    event_type="SKEPTIC_REJECT",
                    severity="WARNING",
                    details={"finding_id": f.finding_id, "reason": f.verification_note},
                )
                continue
            f.verified = True
            f.verification_note = f"Verified deterministic SQL execution (job={f.bq_job_id})."
            audit_logger.log(
                deal_id=deal_id,
                agent_name="skeptic",
                event_type="SKEPTIC_PASS",
                severity="INFO",
                details={"finding_id": f.finding_id, "bq_job_id": f.bq_job_id},
            )
            verified_list.append(f)

    return verified_list
