"""Public regulatory & audit references (EU AI Act, RGPD/GDPR, PCG/IFRS/ISA/OCDE)."""

from __future__ import annotations

from pydantic import BaseModel


class GovReference(BaseModel):
    code: str
    framework: str  # EU AI Act | RGPD | Audit / Comptable | Fiscalité
    citation: str
    summary: str


RULE_REFERENCES: dict[str, GovReference] = {
    "CUT_OFF": GovReference(
        code="CUT_OFF",
        framework="Audit / Comptable",
        citation="PCG Art. 512-1 • IAS 1 & IFRS 15",
        summary="Principe d'indépendance des exercices : la charge doit être rattachée à l'exercice de réalisation effective.",
    ),
    "CONCORDANCE": GovReference(
        code="CONCORDANCE",
        framework="Audit / Comptable",
        citation="ISA 500 • NEP 500 (Éléments probants)",
        summary="Rapprochement exact entre la pièce justificative et l'écriture enregistrée au Grand Livre.",
    ),
    "TVA": GovReference(
        code="TVA",
        framework="Fiscalité",
        citation="Directive TVA 2006/112/CE • CGI Art. 256 & 262 ter",
        summary="Un taux à 0 % exige une justification juridique d'exonération ou d'autoliquidation.",
    ),
    "INTERCOMPAGNIE": GovReference(
        code="INTERCOMPAGNIE",
        framework="Audit / Prix de Transfert",
        citation="IFRS 10 (B86) • Principes OCDE Prix de Transfert",
        summary="Obligation de réciprocité des flux intra-groupe et respect du principe de pleine concurrence.",
    ),
    "SEUIL": GovReference(
        code="SEUIL",
        framework="Audit / Comptable",
        citation="ISA 320 • NEP 320 (Caractère significatif)",
        summary="Tout montant supérieur au seuil de matérialité du Passeport Client impose un examen renforcé.",
    ),
}

PLATFORM_GOVERNANCE_REFS: list[GovReference] = [
    GovReference(
        code="GATE1_TENANT",
        framework="RGPD",
        citation="RGPD Art. 32 (Sécurité du traitement)",
        summary="Isolation multi-clients stricte par tenant_id et comptes de service IAM dédiés.",
    ),
    GovReference(
        code="GATE1_DLP",
        framework="RGPD",
        citation="RGPD Art. 5(1)(c) & Art. 25 (Privacy by Design)",
        summary="Pseudonymisation Cloud DLP + KMS avant tout traitement par l'IA.",
    ),
    GovReference(
        code="GATE1_ARMOR",
        framework="EU AI Act",
        citation="Règlement (UE) 2024/1689 Art. 9 & Art. 15",
        summary="Gestion des risques et cybersécurité IA : mise en quarantaine Model Armor des injections de prompt.",
    ),
    GovReference(
        code="GATES_2_3_HITL",
        framework="EU AI Act",
        citation="Règlement (UE) 2024/1689 Art. 14 (Contrôle humain)",
        summary="Supervision humaine obligatoire par l'Avocat, le Consultant et l'Auditeur avant conclusion.",
    ),
    GovReference(
        code="AUDIT_TRAIL",
        framework="EU AI Act",
        citation="Règlement (UE) 2024/1689 Art. 12 & Art. 13",
        summary="Traçabilité immuable dans BigQuery (audit_logs) et transparence de la formule de score.",
    ),
]


def get_rule_reference(rule_id: str) -> GovReference:
    """Return the official regulatory reference for a given audit rule."""
    return RULE_REFERENCES[rule_id]
