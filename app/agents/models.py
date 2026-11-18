"""Pydantic schemas for AuditBridge: Evidence Traceability, Canonical JSON, Harness & Case."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class Evidence(BaseModel):
    """Mandatory evidence traceability object."""

    source_type: Literal["input", "passport", "regulation"]
    file: str  # relative path from repo root, e.g. data/inputs/CLIENT_B/facture_0412.txt
    locator: dict[str, Any]  # {line_start, line_end} | {row, column} | {json_path}
    excerpt: str
    explanation: str


class LedgerEntry(BaseModel):
    account: str
    amount: float
    period: str


class CanonicalInvoice(BaseModel):
    tenant_id: str
    invoice_id: str
    supplier: str
    customer: str
    is_intercompany: bool
    amount_ht: float
    vat_rate: float
    amount_ttc: float
    invoice_date: str
    service_date: str
    ledger_entry: LedgerEntry
    description: str
    source_file: str


class Finding(BaseModel):
    rule_id: str  # CUT_OFF | CONCORDANCE | TVA | INTERCOMPAGNIE | SEUIL
    label: str
    passed: bool
    summary: str
    evidences: list[Evidence] = Field(default_factory=list)
    skeptic_verified: bool = False


class MicroBrief(BaseModel):
    role: Literal["AVOCAT", "CONSULTANT"]
    title: str
    question: str
    options: list[str]
    context_summary: str


class ExpertResponse(BaseModel):
    role: Literal["AVOCAT", "CONSULTANT"]
    decision: str
    comment: str = ""
    responder: str = ""
    timestamp: str = ""


class AuditCase(BaseModel):
    case_id: str
    session_id: str
    tenant_id: str
    status: Literal["Conforme", "Anomalie", "Quarantaine", "Validé", "Rejeté"]
    invoice: CanonicalInvoice
    findings: list[Finding] = Field(default_factory=list)
    auditor_explanation: str = ""
    micro_briefs: list[MicroBrief] = Field(default_factory=list)
    expert_responses: dict[str, ExpertResponse] = Field(default_factory=dict)
    confidence_score: int = 100
    score_color: Literal["green", "amber", "red"] = "green"
    recommendation: str = ""
    validator_decision: dict[str, Any] | None = None
    harness_step: str = "IDLE"
    last_action: str = ""
    quarantine_reason: str = ""
    control_sheet_md: str = ""
