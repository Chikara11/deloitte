"""AuditorAgent: deterministic Python rules + exact Evidence Traceability + Gemini explanation."""

from __future__ import annotations

from typing import Any

from app.agents.models import CanonicalInvoice, Evidence, Finding
from app.data.normalizer import DATA_ROOT, load_passport


def _reg_excerpt(filename: str, line_start: int, line_end: int) -> str:
    lines = (DATA_ROOT / "regulations" / filename).read_text(encoding="utf-8").splitlines()
    return "\n".join(lines[line_start - 1 : line_end])


def _input_evidence(
    invoice: CanonicalInvoice,
    locators: dict[str, Any],
    field_key: str,
    explanation: str,
) -> Evidence:
    if locators["kind"] == "csv":
        col = locators["inv_map"][field_key]
        row_num = locators["row"]
        val = getattr(invoice, field_key)
        return Evidence(
            source_type="input",
            file=invoice.source_file,
            locator={"row": row_num, "column": col},
            excerpt=f"{col}={val}",
            explanation=explanation,
        )
    raw_key = locators["inv_map"][field_key]
    val, ln = locators["kv"].get(raw_key, ("", 1))
    return Evidence(
        source_type="input",
        file=invoice.source_file,
        locator={"line_start": ln, "line_end": ln},
        excerpt=f"{raw_key}: {val}",
        explanation=explanation,
    )


def run_auditor_rules(
    invoice: CanonicalInvoice,
    locators: dict[str, Any],
) -> tuple[list[Finding], str]:
    """Run all 5 deterministic rules and attach mandatory Input + Regulation/Passport evidence."""
    passport = load_passport(invoice.tenant_id)
    passport_file = f"data/passports/{invoice.tenant_id}.json"
    closing_year = int(passport["closing_date"][:4])
    service_year = int(invoice.service_date[:4])
    ledger_year = int(invoice.ledger_entry.period[:4])

    findings: list[Finding] = []

    # 1. CUT_OFF
    cutoff_ok = not (service_year > closing_year and ledger_year <= closing_year)
    findings.append(
        Finding(
            rule_id="CUT_OFF",
            label="Séparation des exercices (Cut-off)",
            passed=cutoff_ok,
            summary=(
                f"Prestation ({invoice.service_date}) et période comptable ({invoice.ledger_entry.period}) cohérentes."
                if cutoff_ok
                else f"Prestation réalisée en {invoice.service_date} mais comptabilisée en {invoice.ledger_entry.period} (clôture {passport['closing_date']})."
            ),
            evidences=[
                _input_evidence(
                    invoice,
                    locators,
                    "service_date",
                    f"La date de prestation ({invoice.service_date}) est postérieure à la clôture {passport['closing_date']}."
                    if not cutoff_ok
                    else f"La date de prestation ({invoice.service_date}) est bien dans l'exercice.",
                ),
                Evidence(
                    source_type="input",
                    file=locators["ledger_file"],
                    locator={"row": locators["ledger_row"], "column": "period"},
                    excerpt=f"period={invoice.ledger_entry.period}, amount={invoice.ledger_entry.amount}",
                    explanation=f"L'écriture comptable est enregistrée sur la période {invoice.ledger_entry.period}.",
                ),
                Evidence(
                    source_type="regulation",
                    file="data/regulations/cutoff_rules.md",
                    locator={"line_start": 6, "line_end": 7},
                    excerpt=_reg_excerpt("cutoff_rules.md", 6, 7),
                    explanation="Article 1.2 impose le reclassement sur l'exercice de réalisation effective.",
                ),
                Evidence(
                    source_type="passport",
                    file=passport_file,
                    locator={"json_path": "$.closing_date"},
                    excerpt=f'"closing_date": "{passport["closing_date"]}"',
                    explanation="Date de clôture de l'exercice définie dans le passeport client.",
                ),
            ],
        )
    )

    # 2. CONCORDANCE
    conc_ok = abs(invoice.amount_ht - invoice.ledger_entry.amount) < 0.01
    findings.append(
        Finding(
            rule_id="CONCORDANCE",
            label="Concordance Facture / Grand Livre",
            passed=conc_ok,
            summary=f"Montant facture ({invoice.amount_ht:,.0f} €) vs Grand Livre ({invoice.ledger_entry.amount:,.0f} €).",
            evidences=[
                _input_evidence(invoice, locators, "amount_ht", "Montant HT indiqué sur la pièce justificative."),
                Evidence(
                    source_type="input",
                    file=locators["ledger_file"],
                    locator={"row": locators["ledger_row"], "column": "amount"},
                    excerpt=f"amount={invoice.ledger_entry.amount}",
                    explanation="Montant comptabilisé dans le Grand Livre.",
                ),
                Evidence(
                    source_type="regulation",
                    file="data/regulations/intercompany_rules.md",
                    locator={"line_start": 6, "line_end": 7},
                    excerpt=_reg_excerpt("intercompany_rules.md", 6, 7),
                    explanation="Article 3.2 exige la concordance exacte entre facture HT et Grand Livre.",
                ),
            ],
        )
    )

    # 3. TVA
    vat_ok = not (invoice.vat_rate == 0.0 and float(passport["vat_rate"]) > 0.0)
    findings.append(
        Finding(
            rule_id="TVA",
            label="Conformité TVA B2B",
            passed=vat_ok,
            summary=(
                f"Taux de TVA appliqué ({invoice.vat_rate * 100:.0f}%) conforme au passeport."
                if vat_ok
                else f"TVA à 0 % appliquée vs taux standard {float(passport['vat_rate']) * 100:.0f}% — justification d'autoliquidation requise."
            ),
            evidences=[
                _input_evidence(
                    invoice,
                    locators,
                    "vat_rate",
                    "Taux de TVA facturé égal à 0.0 sans mention explicite d'autoliquidation."
                    if not vat_ok
                    else "Taux de TVA standard appliqué.",
                ),
                Evidence(
                    source_type="regulation",
                    file="data/regulations/vat_services_b2b.md",
                    locator={"line_start": 6, "line_end": 7},
                    excerpt=_reg_excerpt("vat_services_b2b.md", 6, 7),
                    explanation="Article 2.2 impose la validation Tax & Legal pour toute facture à 0 % sans mention complète.",
                ),
            ],
        )
    )

    # 4. INTERCOMPAGNIE
    interco_ok = not invoice.is_intercompany
    findings.append(
        Finding(
            rule_id="INTERCOMPAGNIE",
            label="Flux Intercompagnie & Réciprocité",
            passed=interco_ok,
            summary=(
                "Tiers externe : pas de flux intercompagnie."
                if interco_ok
                else f"Flux intra-groupe ({invoice.supplier} -> {invoice.customer}) : réciprocité et réalité des services à documenter."
            ),
            evidences=[
                _input_evidence(
                    invoice,
                    locators,
                    "is_intercompany",
                    "Transaction marquée intercompagnie entre deux entités du groupe."
                    if not interco_ok
                    else "Transaction externe hors groupe.",
                ),
                Evidence(
                    source_type="passport",
                    file=passport_file,
                    locator={"json_path": "$.group_entities"},
                    excerpt=f'"group_entities": {passport["group_entities"]}',
                    explanation="Les deux parties appartiennent au périmètre de consolidation du groupe.",
                ),
                Evidence(
                    source_type="regulation",
                    file="data/regulations/intercompany_rules.md",
                    locator={"line_start": 3, "line_end": 4},
                    excerpt=_reg_excerpt("intercompany_rules.md", 3, 4),
                    explanation="Article 3.1 exige la réciprocité et la documentation probante des services.",
                ),
            ],
        )
    )

    # 5. SEUIL
    threshold = float(passport["approval_threshold"])
    seuil_ok = invoice.amount_ht <= threshold
    findings.append(
        Finding(
            rule_id="SEUIL",
            label="Seuil d'approbation client",
            passed=seuil_ok,
            summary=f"Montant {invoice.amount_ht:,.0f} € vs seuil passeport {threshold:,.0f} €.",
            evidences=[
                _input_evidence(
                    invoice,
                    locators,
                    "amount_ht",
                    f"Le montant ({invoice.amount_ht:,.0f} €) dépasse le seuil d'approbation ({threshold:,.0f} €)."
                    if not seuil_ok
                    else "Montant inférieur au seuil d'approbation.",
                ),
                Evidence(
                    source_type="passport",
                    file=passport_file,
                    locator={"json_path": "$.approval_threshold"},
                    excerpt=f'"approval_threshold": {int(threshold)}',
                    explanation="Seuil d'examen renforcé fixé dans le passeport client.",
                ),
                Evidence(
                    source_type="regulation",
                    file="data/regulations/intercompany_rules.md",
                    locator={"line_start": 6, "line_end": 7},
                    excerpt=_reg_excerpt("intercompany_rules.md", 6, 7),
                    explanation="Article 3.2 impose un examen renforcé au-delà du seuil passeport.",
                ),
            ],
        )
    )

    failed = [f for f in findings if not f.passed]
    explanation = (
        f"Contrôle conforme : toutes les règles ({len(findings)}/{len(findings)}) sont validées selon le passeport {invoice.tenant_id}."
        if not failed
        else f"{len(failed)} anomalie(s) détectée(s) ({', '.join(f.rule_id for f in failed)}). Escalade vers BridgeAgent pour avis Tax & Legal et Consulting."
    )
    return findings, explanation
