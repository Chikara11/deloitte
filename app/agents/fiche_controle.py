"""Automatic Fiche de Contrôle Documentée generator (Markdown export)."""

from __future__ import annotations

from datetime import datetime, timezone

from app.agents.models import AuditCase
from app.data.passports import get_passport


def generate_fiche_controle(case: AuditCase) -> str:
    """Render the audit-ready Fiche de Contrôle Documentée in Markdown."""
    passport = get_passport(case.tenant_id)
    inv = case.invoice
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    lines = [
        f"# FICHE DE CONTRÔLE INTERNE — {inv.invoice_id}",
        f"**Client / Tenant :** `{case.tenant_id}` ({passport.client_name})  ",
        f"**Référentiel :** {passport.norme} | **Seuil :** {passport.regles.seuil_validation:,.0f} € | **Clôture :** {passport.regles.date_cloture}  ",
        f"**Générée le :** {now}",
        "",
        "## 1. Objectif & Population Testée",
        f"- **Objectif :** Contrôle de cut-off, concordance comptable, TVA et réciprocité inter-compagnies.",
        f"- **Pièce testée :** `{inv.source_file}` — Facture `{inv.invoice_id}` ({inv.amount_ht:,.0f} € HT) entre `{inv.supplier}` et `{inv.customer}`.",
        f"- **Sécurité Gate 1 :** `tenant_id` vérifié | Model Armor : `{inv.security.model_armor}` | PII masquées : `{inv.security.pii_masked}`.",
        "",
        "## 2. Règles Appliquées (Agent Auditeur)",
        "| Règle | Résultat | Preuve / Source |",
        "| :--- | :---: | :--- |",
    ]

    for r in case.rules:
        badge = "✅ OK" if r.passed else "❌ ANOMALIE"
        lines.append(f"| **{r.label}** (`{r.rule_id}`) | {badge} | {r.evidence} |")

    lines.extend(["", "## 3. Avis des Experts (Gate 2 — Supervision Humaine)"])
    if not case.expert_responses:
        lines.append("- *Aucune escalade requise (contrôle conforme dès la Gate 1 / Auditeur).*")
    else:
        for role, resp in case.expert_responses.items():
            lines.append(
                f"- **{role}** (`{resp.responder_id}`) — **{resp.decision}** *({resp.timestamp})* : {resp.comment or 'Sans commentaire'}"
            )

    valideur = (
        f"{case.auditor_gate3['auditor_id']} ({case.auditor_gate3['decision']} le {case.auditor_gate3['timestamp']})"
        if case.auditor_gate3
        else "En attente de validation Auditeur (Gate 3)"
    )

    lines.extend(
        [
            "",
            "## 4. Synthèse & Conclusion",
            f"- **Score de Confiance :** **{case.confidence_score}/100** (`{case.score_color}`)",
            f"- **Recommandation :** {case.recommendation}",
            f"- **Valideur (Gate 3) :** {valideur}",
        ]
    )
    return "\n".join(lines)
