"""Agent Auditeur: 5 deterministic Python audit rules + Gemini explanation."""

from __future__ import annotations

from app.agents.models import CanonicalInvoice, RuleCheckResult
from app.config import settings
from app.data.audit_logger import audit_logger
from app.data.governance_refs import get_rule_reference
from app.data.passports import get_passport


def run_auditeur_agent(invoice: CanonicalInvoice) -> tuple[str, list[RuleCheckResult], str]:
    """Run the 5 deterministic Python rules against the Client Passport.

    Returns (status: 'OK' | 'ANOMALIE', rules, explanation).
    """
    passport = get_passport(invoice.tenant_id)
    cloture_year = int(passport.regles.date_cloture[:4])
    service_year = int(invoice.service_date[:4])
    ledger_year = int(invoice.ledger_entry.period[:4])

    rules: list[RuleCheckResult] = []

    # 1. CUT_OFF: service performed after closing year but booked in closing year
    cutoff_ok = not (service_year > cloture_year and ledger_year <= cloture_year)
    rules.append(
        RuleCheckResult(
            rule_id="CUT_OFF",
            label="Séparation des exercices (Cut-off)",
            passed=cutoff_ok,
            evidence=(
                f"Prestation {invoice.service_date} vs période comptable {invoice.ledger_entry.period} "
                f"(clôture {passport.regles.date_cloture})."
            ),
        )
    )

    # 2. CONCORDANCE: invoice amount matches ledger entry amount
    conc_ok = abs(invoice.amount_ht - invoice.ledger_entry.amount) < 0.01
    rules.append(
        RuleCheckResult(
            rule_id="CONCORDANCE",
            label="Concordance Facture / Grand Livre",
            passed=conc_ok,
            evidence=f"Facture HT {invoice.amount_ht:,.0f} € vs Écriture {invoice.ledger_entry.amount:,.0f} € (compte {invoice.ledger_entry.account}).",
        )
    )

    # 3. TVA: 0% VAT rate triggers verification if passport expects standard VAT
    vat_ok = not (invoice.vat_rate == 0.0 and passport.regles.taux_tva > 0.0)
    rules.append(
        RuleCheckResult(
            rule_id="TVA",
            label="Conformité Taux de TVA",
            passed=vat_ok,
            evidence=f"TVA facturée {invoice.vat_rate * 100:.1f}% vs taux attendu {passport.regles.taux_tva * 100:.1f}%.",
        )
    )

    # 4. INTERCOMPAGNIE: intercompany flows require reciprocity check
    interco_ok = not invoice.is_intercompany
    rules.append(
        RuleCheckResult(
            rule_id="INTERCOMPAGNIE",
            label="Flux Inter-compagnies (Réciprocité)",
            passed=interco_ok,
            evidence=(
                f"Flux intra-groupe ({invoice.supplier} -> {invoice.customer}) : vérification de réciprocité requise."
                if invoice.is_intercompany
                else "Tiers externe : pas de flux inter-compagnies."
            ),
        )
    )

    # 5. SEUIL: amount exceeds Client Passport materiality threshold
    seuil_ok = invoice.amount_ht <= passport.regles.seuil_validation
    rules.append(
        RuleCheckResult(
            rule_id="SEUIL",
            label=f"Seuil de matérialité ({passport.norme})",
            passed=seuil_ok,
            evidence=f"Montant {invoice.amount_ht:,.0f} € vs seuil client {passport.regles.seuil_validation:,.0f} €.",
        )
    )

    for r in rules:
        r.reference = get_rule_reference(r.rule_id).citation

    failed = [r for r in rules if not r.passed]
    status = "OK" if not failed else "ANOMALIE"

    explanation = (
        f"Contrôle conforme : 5/5 règles validées selon le Passeport {passport.tenant_id} ({passport.norme})."
        if not failed
        else f"{len(failed)}/5 règle(s) en anomalie ({', '.join(r.rule_id for r in failed)}). Escalade vers Agent Passerelle."
    )

    if failed and settings.use_real_gcp_data:
        try:
            from google import genai

            client = genai.Client(vertexai=True, project=settings.gcp_project_id, location=settings.gcp_region)
            prompt = (
                f"En 2 phrases courtes en français, résume pour un auditeur Deloitte pourquoi la facture "
                f"{invoice.invoice_id} ({invoice.amount_ht:,.0f} €) présente les anomalies suivantes : "
                + "; ".join(f"{r.rule_id}: {r.evidence}" for r in failed)
            )
            resp = client.models.generate_content(model=settings.gemini_fast_model, contents=prompt)
            if resp.text:
                explanation = resp.text.strip()
        except Exception:
            pass

    audit_logger.log(
        deal_id=invoice.tenant_id,
        agent_name="agent_auditeur",
        event_type="AUDITEUR_RULES_EVALUATED",
        severity="WARNING" if failed else "INFO",
        details={
            "invoice_id": invoice.invoice_id,
            "status": status,
            "failed_rules": [r.rule_id for r in failed],
        },
    )
    return status, rules, explanation
