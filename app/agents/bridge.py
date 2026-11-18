"""BridgeAgent: generates closed Micro-Briefs for Tax & Legal Lawyer and Consultant."""

from __future__ import annotations

from app.agents.models import CanonicalInvoice, Finding, MicroBrief


def generate_micro_briefs(invoice: CanonicalInvoice, findings: list[Finding]) -> list[MicroBrief]:
    """Produce two role-specific Micro-Briefs with closed questions when anomalies exist."""
    failed = [f.rule_id for f in findings if not f.passed]
    if not failed:
        return []

    return [
        MicroBrief(
            role="AVOCAT",
            title="Avis Tax & Legal — TVA & Structure Intercompagnie",
            question="Le montage intercompagnie et le taux de TVA (0 %) sont-ils conformes ?",
            options=["Conforme", "Non conforme"],
            context_summary=(
                f"Facture {invoice.invoice_id} de {invoice.amount_ht:,.0f} € HT entre {invoice.supplier} et "
                f"{invoice.customer}. TVA facturée : {invoice.vat_rate * 100:.0f}%. Anomalies détectées : {', '.join(failed)}."
            ),
        ),
        MicroBrief(
            role="CONSULTANT",
            title="Avis Consulting — Réalité de la Prestation & Date de Livraison",
            question="La prestation « " + invoice.description + " » a-t-elle été livrée, et sur quel exercice ?",
            options=["Livré en 2026", "Livré en 2027", "Non livré"],
            context_summary=(
                f"Facture émise le {invoice.invoice_date}, date de prestation déclarée : {invoice.service_date}, "
                f"comptabilisée sur la période {invoice.ledger_entry.period}."
            ),
        ),
    ]
