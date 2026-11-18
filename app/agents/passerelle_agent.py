"""Agent Passerelle: translates audit anomalies into closed Micro-Briefs for Avocat & Consultant."""

from __future__ import annotations

from app.agents.models import CanonicalInvoice, MicroBrief, RuleCheckResult
from app.data.audit_logger import audit_logger


def run_passerelle_agent(invoice: CanonicalInvoice, rules: list[RuleCheckResult]) -> list[MicroBrief]:
    """Generate role-specific closed Micro-Briefs for Gate 2."""
    failed_ids = {r.rule_id for r in rules if not r.passed}
    briefs: list[MicroBrief] = [
        MicroBrief(
            role="AVOCAT",
            title="⚖️ Micro-Brief Tax & Legal — TVA & Prix de Transfert",
            question="Le montage inter-compagnies et le taux de TVA appliqué sont-ils conformes ?",
            options=["Conforme", "Non conforme"],
            context_summary=(
                f"Facture {invoice.invoice_id} de {invoice.amount_ht:,.0f} € HT entre {invoice.supplier} et "
                f"{invoice.customer}. TVA appliquée : {invoice.vat_rate * 100:.1f}%. "
                f"Règles signalées : {', '.join(sorted(failed_ids))}."
            ),
        ),
        MicroBrief(
            role="CONSULTANT",
            title="💼 Micro-Brief Consulting — Réalité de la Prestation & Cut-off",
            question="La prestation décrite a-t-elle vraiment été livrée, et sur quel exercice ?",
            options=["Livré", "Non livré", "Livré en 2027"],
            context_summary=(
                f"Objet : « {invoice.description} ». Date facture : {invoice.invoice_date} | "
                f"Date prestation annoncée : {invoice.service_date} | Période comptable : {invoice.ledger_entry.period}."
            ),
        ),
    ]

    audit_logger.log(
        deal_id=invoice.tenant_id,
        agent_name="agent_passerelle",
        event_type="MICRO_BRIEFS_SENT",
        severity="INFO",
        details={"invoice_id": invoice.invoice_id, "targets": ["AVOCAT", "CONSULTANT"]},
    )
    return briefs
