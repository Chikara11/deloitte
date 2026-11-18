"""Canonical JSON and AuditBridge workflow Pydantic models."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class LedgerEntry(BaseModel):
    account: str
    amount: float
    period: str  # YYYY-MM


class SecurityMeta(BaseModel):
    model_armor: str  # clean | blocked
    pii_masked: int = 0
    tenant_verified: bool = True


class CanonicalInvoice(BaseModel):
    """Strict Canonical JSON contract between Group 1 (Ingestion) and Group 2 (Agents)."""

    tenant_id: str
    invoice_id: str
    supplier: str
    customer: str
    is_intercompany: bool
    amount_ht: float
    vat_rate: float
    amount_ttc: float
    invoice_date: str  # YYYY-MM-DD
    service_date: str  # YYYY-MM-DD
    ledger_entry: LedgerEntry
    description: str
    source_file: str
    security: SecurityMeta


class RuleCheckResult(BaseModel):
    rule_id: str  # CUT_OFF | CONCORDANCE | TVA | INTERCOMPAGNIE | SEUIL
    label: str
    passed: bool
    evidence: str
    reference: str = ""


class MicroBrief(BaseModel):
    role: str  # AVOCAT | CONSULTANT
    title: str
    question: str
    options: list[str]
    context_summary: str


class ExpertResponse(BaseModel):
    role: str  # AVOCAT | CONSULTANT
    decision: str  # Conforme | Non conforme | Livré | Non livré | Livré en 2027
    comment: str = ""
    responder_id: str = ""
    timestamp: str = ""


class AuditCase(BaseModel):
    case_id: str
    tenant_id: str
    invoice: CanonicalInvoice
    status: str  # OK | ANOMALIE | QUARANTINE | VALIDATED | REJECTED
    rules: list[RuleCheckResult] = Field(default_factory=list)
    auditor_explanation: str = ""
    micro_briefs: list[MicroBrief] = Field(default_factory=list)
    expert_responses: dict[str, ExpertResponse] = Field(default_factory=dict)
    confidence_score: int = 100
    score_color: str = "GREEN"  # GREEN | ORANGE | RED
    recommendation: str = ""
    auditor_gate3: dict[str, Any] | None = None
    governance_references: list[dict[str, str]] = Field(default_factory=list)
    fiche_controle_md: str = ""
