"""AuditBridge orchestrator: Gate 1 -> Auditeur -> Passerelle -> Gate 2 -> Synthèse -> Gate 3."""

from __future__ import annotations

from datetime import datetime, timezone

from app.agents.auditeur_agent import run_auditeur_agent
from app.agents.fiche_controle import generate_fiche_controle
from app.agents.models import AuditCase, CanonicalInvoice, ExpertResponse
from app.agents.passerelle_agent import run_passerelle_agent
from app.agents.synthese_agent import compute_synthesis
from app.data.audit_logger import audit_logger


def evaluate_invoice(invoice: CanonicalInvoice) -> AuditCase:
    """Run Agent Auditeur + Agent Passerelle (if anomaly) + initial Synthèse & Fiche."""
    status, rules, explanation = run_auditeur_agent(invoice)
    briefs = run_passerelle_agent(invoice, rules) if status == "ANOMALIE" else []

    case = AuditCase(
        case_id=f"{invoice.tenant_id}:{invoice.invoice_id}",
        tenant_id=invoice.tenant_id,
        invoice=invoice,
        status=status,
        rules=rules,
        auditor_explanation=explanation,
        micro_briefs=briefs,
    )
    score, color, rec = compute_synthesis(invoice.tenant_id, invoice.invoice_id, rules, {})
    case.confidence_score = score
    case.score_color = color
    case.recommendation = rec
    case.fiche_controle_md = generate_fiche_controle(case)
    return case


def apply_expert_response(case: AuditCase, role: str, decision: str, comment: str, responder_id: str) -> AuditCase:
    """Gate 2: record Avocat or Consultant validation and recompute Synthèse + Fiche."""
    case.expert_responses[role.upper()] = ExpertResponse(
        role=role.upper(),
        decision=decision,
        comment=comment,
        responder_id=responder_id,
        timestamp=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
    )
    audit_logger.log(
        deal_id=case.tenant_id,
        agent_name=f"gate2_{role.lower()}",
        event_type="EXPERT_GATE2_RESPONSE",
        severity="INFO",
        details={"invoice_id": case.invoice.invoice_id, "role": role.upper(), "decision": decision},
    )
    score, color, rec = compute_synthesis(case.tenant_id, case.invoice.invoice_id, case.rules, case.expert_responses)
    case.confidence_score = score
    case.score_color = color
    case.recommendation = rec
    case.fiche_controle_md = generate_fiche_controle(case)
    return case


def apply_auditor_gate3(case: AuditCase, decision: str, auditor_id: str, comment: str = "") -> AuditCase:
    """Gate 3: final Auditor sign-off or rejection."""
    case.status = "VALIDATED" if decision.upper() == "VALIDER" else "REJECTED"
    case.auditor_gate3 = {
        "decision": decision.upper(),
        "auditor_id": auditor_id,
        "comment": comment,
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
    }
    audit_logger.log(
        deal_id=case.tenant_id,
        agent_name="gate3_auditeur",
        event_type="AUDITOR_GATE3_DECISION",
        severity="INFO",
        details={"invoice_id": case.invoice.invoice_id, "decision": decision.upper(), "auditor_id": auditor_id},
    )
    case.fiche_controle_md = generate_fiche_controle(case)
    return case
