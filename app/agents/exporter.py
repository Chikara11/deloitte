"""Control Documentation Sheet exporter (.md and .docx via python-docx)."""

from __future__ import annotations

import io
from datetime import datetime, timezone
from typing import Any

from docx import Document

from app.agents.models import AuditCase, AuditEvent
from app.data.audit_logger import audit_logger


def render_control_sheet_md(
    case: AuditCase,
    events: list[AuditEvent] | None = None,
    chain_status: dict[str, Any] | None = None,
) -> str:
    """Render a complete Control Documentation Sheet in Markdown with decision trail and chain status."""
    inv = case.invoice
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    evts = events if events is not None else audit_logger.list_events(case_id=case.case_id)
    chain = chain_status if chain_status is not None else audit_logger.verify_chain(case.case_id)
    chain_badge = (
        f"Intègre (SHA-256 vérifié, {chain.get('event_count', 0)} événements)"
        if chain.get("valid", False)
        else f"ROMPUE ({chain.get('first_broken_event_id')})"
    )

    lines = [
        f"# FICHE DE CONTRÔLE INTERNE — {inv.invoice_id}",
        f"**Dossier / Tenant :** `{case.tenant_id}` | **Session :** `{case.session_id}` | **Date :** {now}",
        f"**Intégrité du journal :** `{chain_badge}`",
        "",
        "## 1. Objectif du contrôle",
        "Vérification de la séparation des exercices (cut-off), de la concordance facture/Grand Livre, de la conformité TVA B2B, de la réciprocité intercompagnie et du seuil d'approbation client.",
        "",
        "## 2. Pièce contrôlée (JSON Canonique)",
        f"- **Source :** `{inv.source_file}`",
        f"- **Fournisseur -> Client :** `{inv.supplier}` -> `{inv.customer}` (Intercompagnie : `{inv.is_intercompany}`)",
        f"- **Montant HT :** `{inv.amount_ht:,.0f} EUR` | **TVA :** `{inv.vat_rate * 100:.0f}%` | **Date prestation :** `{inv.service_date}` | **Période GL :** `{inv.ledger_entry.period}`",
        "",
        "## 3. Règles testées & Preuves tracées",
        "| Règle | Statut | Résumé | Sources / Preuves |",
        "| :--- | :---: | :--- | :--- |",
    ]
    for f in case.findings:
        st = "CONFORME" if f.passed else "ANOMALIE"
        if f.overridden_by:
            st += f" (Surchargé par {f.overridden_by})"
        srcs = "; ".join(f"[{e.source_type}] `{e.file}` ({e.locator})" for e in f.evidences)
        lines.append(f"| **{f.label}** (`{f.rule_id}`) | {st} | {f.summary} | {srcs} |")

    lines.extend(["", "## 4. Avis des experts (Gate 4)"])
    if not case.expert_responses:
        lines.append("- Aucune escalade requise.")
    else:
        for role, resp in case.expert_responses.items():
            lines.append(
                f"- **{role}** ({resp.responder}, {resp.timestamp}) : **{resp.decision}** — {resp.comment or 'Sans commentaire'}"
            )

    val_info = (
        f"{case.validator_decision['validator']} ({case.validator_decision.get('role', 'Auditeur')}) — "
        f"{case.validator_decision['decision']} ({case.validator_decision['timestamp']})"
        if case.validator_decision
        else "En attente de validation (Gate 5)"
    )
    lines.extend(
        [
            "",
            "## 5. Conclusion & Validation (Gate 5)",
            f"- **Score de confiance :** `{case.confidence_score}/100` (`{case.score_color.upper()}`)",
            f"- **Conclusion :** {case.conclusion or case.recommendation}",
            f"- **Valideur (Gate 5) :** {val_info}",
            "",
            "## 6. Piste d'audit chronologique (Chaîne SHA-256)",
            "| Horodatage UTC | Gate | Acteur (Rôle) | Action / Décision | Commentaire |",
            "| :--- | :--- | :--- | :--- | :--- |",
        ]
    )
    for e in evts:
        lines.append(
            f"| `{e.timestamp_utc[:19]}` | `{e.gate}` | `{e.actor_id}` ({e.actor_role}) | **{e.action}** / `{e.decision}` | {e.comment or '-'} |"
        )

    lines.extend(["", "*Brouillon généré par IA — validation humaine requise — données fictives.*"])
    return "\n".join(lines)


def render_control_sheet_docx(
    case: AuditCase,
    events: list[AuditEvent] | None = None,
    chain_status: dict[str, Any] | None = None,
) -> bytes:
    """Export the Control Documentation Sheet as a formatted .docx document."""
    doc = Document()
    inv = case.invoice
    evts = events if events is not None else audit_logger.list_events(case_id=case.case_id)
    chain = chain_status if chain_status is not None else audit_logger.verify_chain(case.case_id)
    chain_label = (
        f"Journal intègre (SHA-256 OK, {chain.get('event_count', 0)} événements)"
        if chain.get("valid", False)
        else f"ALERTE: Chaîne rompue ({chain.get('first_broken_event_id')})"
    )

    doc.add_heading(f"Fiche de Contrôle Interne — {inv.invoice_id}", level=1)
    doc.add_paragraph(
        f"Client : {case.tenant_id} | Session : {case.session_id} | Statut : {case.status} | Score : {case.confidence_score}/100"
    )
    doc.add_paragraph(f"Intégrité de la piste d'audit : {chain_label}")

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
        row[3].text = ", ".join(f"{e.file} {e.locator}" for e in f.evidences)

    doc.add_heading("3. Avis des experts (Gate 4)", level=2)
    if not case.expert_responses:
        doc.add_paragraph("Aucune escalade requise.")
    else:
        for role, resp in case.expert_responses.items():
            doc.add_paragraph(f"{role} ({resp.responder}, {resp.timestamp}) : {resp.decision} — {resp.comment}")

    doc.add_heading("4. Conclusion & Validation (Gate 5)", level=2)
    doc.add_paragraph(case.conclusion or case.recommendation)
    if case.validator_decision:
        doc.add_paragraph(
            f"Validé par : {case.validator_decision['validator']} ({case.validator_decision.get('role', 'Auditeur')}) — "
            f"{case.validator_decision['decision']} le {case.validator_decision['timestamp']}"
        )

    doc.add_heading("5. Piste d'audit chronologique", level=2)
    trail_table = doc.add_table(rows=1, cols=5)
    th = trail_table.rows[0].cells
    th[0].text = "Horodatage"
    th[1].text = "Gate"
    th[2].text = "Acteur"
    th[3].text = "Action / Décision"
    th[4].text = "Commentaire"
    for e in evts:
        r = trail_table.add_row().cells
        r[0].text = e.timestamp_utc[:19]
        r[1].text = e.gate
        r[2].text = f"{e.actor_id} ({e.actor_role})"
        r[3].text = f"{e.action} / {e.decision}"
        r[4].text = e.comment or "-"

    doc.add_paragraph("\nBrouillon généré par IA — validation humaine requise — données fictives.")
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()
