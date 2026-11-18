"""SynthesisAgent: confidence score formula + actionable audit recommendation."""

from __future__ import annotations

from typing import Literal

from app.agents.models import ExpertResponse, Finding


def run_synthesis(
    findings: list[Finding],
    expert_responses: dict[str, ExpertResponse],
) -> tuple[int, Literal["green", "amber", "red"], str]:
    """Confidence score = 100 - 20 per failed rule - 30 if lawyer non-compliant - 30 if consultant not delivered."""
    score = 100
    failed_count = sum(1 for f in findings if not f.passed)
    score -= 20 * failed_count

    lawyer = expert_responses.get("AVOCAT")
    if lawyer and lawyer.decision == "Non conforme":
        score -= 30

    consultant = expert_responses.get("CONSULTANT")
    if consultant and consultant.decision in ("Non livré", "Livré en 2027"):
        score -= 30

    score = max(0, score)

    if score >= 70:
        return score, "green", "Valider le contrôle — aucune anomalie significative subsistante."
    if score >= 40:
        return score, "amber", "Ajuster / Provisionner — documentation complémentaire requise avant clôture."
    return (
        score,
        "red",
        "Rejeter / Reclasser — extourner la charge sur 2027 (cut-off), régulariser la TVA et documenter le flux intercompagnie.",
    )
