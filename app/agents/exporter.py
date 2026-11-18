"""Control Documentation Sheet exporter (.md and .docx via python-docx)."""

from __future__ import annotations

import io
from datetime import datetime, timezone

from docx import Document

from app.agents.models import AuditCase


def render_control_sheet_md(case: AuditCase) -> str:
    """Render a complete Control Documentation Sheet in Markdown."""
    inv = case.invoice
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = [
        f"# FICHE DE CONTRÔLE INTERNE — {inv.invoice_id}",
        f"**Dossier / Tenant :** `{case.tenant_id}` | **Session :** `{case.session_id}` | **Date :** {now}",
        "",
        "## 1. Objectif du contrôle",
        "Vérification de la séparation des exercices (cut-off), de la concordance facture/Grand Livre, de la conformité TVA B2B, de la réciprocité intercompagnie et du seuil d'approbation client.",
        "",
        "## 2. Pièce contrôlée (JSON Canonique)",
        f"- **Source :** `{inv.source_file}`",
        f"- **Fournisseur $\\rightarrow$ Client :** `{inv.supplier}` $\\rightarrow$ `{inv.customer}` (Intercompagnie : `{inv.is_intercompany}`)",
        f"- **Montant HT :** `{inv.amount_ht:,.0f} €` | **TVA :** `{inv.vat_rate * 100:.0f}%` | **Date prestation :** `{inv.service_date}` | **Période GL :** `{inv.ledger_entry.period}`",
        "",
        "## 3. Règles testées & Preuves tracées",
        "| Règle | Statut | Résumé | Sources / Preuves |",
        "| :--- | :---: | :--- | :--- |",
    ]
    for f in case.findings:
        st = "CONFORME" if f.passed else "ANOMALIE"
        srcs = "; ".join(f"[{e.source_type}] `{e.file}` ({e.locator})" for e in f.evidences)
        lines.append(f"| **{f.label}** (`{f.rule_id}`) | {st} | {f.summary} | {srcs} |")

    lines.extend(["", "## 4. Avis des experts (Gate 2)"])
    if not case.expert_responses:
        lines.append("- Aucune escalade requise.")
    else:
        for role, resp in case.expert_responses.items():
            lines.append(f"- **{role}** ({resp.responder}, {resp.timestamp}) : **{resp.decision}** — {resp.comment or 'Sans commentaire'}")

    val_info = (
        f"{case.validator_decision['validator']} — {case.validator_decision['decision']} ({case.validator_decision['timestamp']})"
        if case.validator_decision
        else "En attente de validation Auditeur (Gate 3)"
    )
    lines.extend(
        [
            "",
            "## 5. Conclusion & Validation",
            f"- **Score de confiance :** `{case.confidence_score}/100` (`{case.score_color.upper()}`)",
            f"- **Conclusion / Recommandation :** {case.recommendation}",
            f"- **Valideur (Gate 3) :** {val_info}",
            "",
            "*Brouillon généré par IA — validation humaine requise — données fictives.*",
        ]
    )
    return "\n".join(lines)


def render_control_sheet_docx(case: AuditCase) -> bytes:
    """Export the Control Documentation Sheet as a formatted .docx document."""
    doc = Document()
    inv = case.invoice
    doc.add_heading(f"Fiche de Contrôle Interne — {inv.invoice_id}", level=1)
    doc.add_paragraph(
        f"Client : {case.tenant_id} | Session : {case.session_id} | Statut : {case.status} | Score : {case.confidence_score}/100"
    )

    doc.add_heading("1. Objectif & Pièce contrôlée", level=2)
    doc.add_paragraph(
        f"Source : {inv.source_file}\n"
        f"Fournisseur -> Client : {inv.supplier} -> {inv.customer}\n"
        f"Montant HT : {inv.amount_ht:,.0f} EUR | TVA : {inv.vat_rate * 100:.0f}% | Date prestation : {inv.service_date} | Période GL : {inv.ledger_entry.period}"
    )

    doc.add_heading("2. Règles testées & Preuves", level=2)
    table = doc.add_table(rows=1, cols=4)
    hdr = table.rows[0].cells
    hdr[0].text = "Règle"
    hdr[1].text = "Statut"
    hdr[2].text = "Résumé"
    hdr[3].text = "Sources"
    for f in case.findings:
        row = table.add_row().cells
        row[0].text = f"{f.label} ({f.rule_id})"
        row[1].text = "CONFORME" if f.passed else "ANOMALIE"
        row[2].text = f.summary
        row[3].text = "\n".join(f"[{e.source_type}] {e.file} {e.locator}" for e in f.evidences)

    doc.add_heading("3. Avis des Experts (Gate 2)", level=2)
    if not case.expert_responses:
        doc.add_paragraph("Aucune escalade requise.")
    else:
        for role, resp in case.expert_responses.items():
            doc.add_paragraph(f"{role} ({resp.responder}, {resp.timestamp}) : {resp.decision} — {resp.comment}")

    doc.add_heading("4. Conclusion & Validation (Gate 3)", level=2)
    doc.add_paragraph(f"Recommandation : {case.recommendation}")
    if case.validator_decision:
        vd = case.validator_decision
        doc.add_paragraph(f"Valideur : {vd['validator']} | Décision : {vd['decision']} | Date : {vd['timestamp']}")
    else:
        doc.add_paragraph("Valideur : En attente de validation Auditeur.")

    doc.add_paragraph("Brouillon généré par IA — validation humaine requise — données fictives.")

    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()
