"""Agent Synthèse: deterministic Confidence Score + Recommendation."""

from __future__ import annotations

from app.agents.models import ExpertResponse, RuleCheckResult
from app.data.audit_logger import audit_logger


def compute_synthesis(
    tenant_id: str,
    invoice_id: str,
    rules: list[RuleCheckResult],
    expert_responses: dict[str, ExpertResponse],
) -> tuple[int, str, str]:
    """Compute Confidence Score:
    Start = 100
    -20 per failed rule
    -30 if Avocat == 'Non conforme'
    -30 if Consultant in ('Non livré', 'Livré en 2027')
    """
    score = 100
    failed_count = sum(1 for r in rules if not r.passed)
    score -= 20 * failed_count

    avocat = expert_responses.get("AVOCAT")
    if avocat and avocat.decision == "Non conforme":
        score -= 30

    consultant = expert_responses.get("CONSULTANT")
    if consultant and consultant.decision in ("Non livré", "Livré en 2027"):
        score -= 30

    score = max(0, score)

    if score >= 70:
        color = "GREEN"
        rec = "VALIDER — Contrôle conforme, aucune écriture corrective requise."
    elif score >= 40:
        color = "ORANGE"
        rec = "AJUSTER / PROVISIONNER — Risque modéré nécessitant une écriture de régularisation."
    else:
        color = "RED"
        rec = (
            "REJETER / SIGNALER — Reclasser la prestation sur l'exercice 2027 (cut-off), "
            "régulariser la TVA et ouvrir une revue fraude inter-compagnies."
        )

    audit_logger.log(
        deal_id=tenant_id,
        agent_name="agent_synthese",
        event_type="CONFIDENCE_SCORED",
        severity="CRITICAL" if color == "RED" else ("WARNING" if color == "ORANGE" else "INFO"),
        details={"invoice_id": invoice_id, "score": score, "color": color},
    )
    return score, color, rec
