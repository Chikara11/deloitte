"""Pydantic schemas for AuditBridge: Evidence Traceability, Canonical JSON, 5-Gate HITL & Hash-Chained Audit Log."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

CaseStatus = Literal[
    "RECEIVED",
    "SECURITY_CHECKED",
    "AUDITOR_AGENT_DONE",
    "GATE2_APPROVED",
    "BRIEFS_DRAFTED",
    "GATE3_APPROVED",
    "EXPERTS_ANSWERED",
    "SYNTHESIS_DONE",
    "GATE5_APPROVED",
    "DOCUMENTED",
    "QUARANTINED",
    "REJECTED",
]


class Evidence(BaseModel):
    """Mandatory evidence traceability object."""

    source_type: Literal["input", "passport", "regulation"]
    file: str
    locator: dict[str, Any]
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
    overridden_by: str | None = None
    override_justification: str | None = None


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


class AuditEvent(BaseModel):
    """Append-only tamper-evident audit event with SHA-256 hash chain."""

    event_id: str
    timestamp_utc: str
    session_id: str
    tenant_id: str
    case_id: str
    gate: str
    actor_type: Literal["human", "agent", "system"]
    actor_id: str
    actor_role: str
    action: str
    decision: str
    comment: str = ""
    before: dict[str, Any] | None = None
    after: dict[str, Any] | None = None
    model_name: str | None = None
    prompt_hash: str | None = None
    evidence_refs: list[str] = Field(default_factory=list)
    prev_hash: str
    hash: str


class AuditCase(BaseModel):
    case_id: str
    session_id: str
    tenant_id: str
    status: CaseStatus = "RECEIVED"
    invoice: CanonicalInvoice
    scope_files: list[str] = Field(default_factory=list)
    findings: list[Finding] = Field(default_factory=list)
    auditor_explanation: str = ""
    auditor_feedback: str = ""
    micro_briefs: list[MicroBrief] = Field(default_factory=list)
    expert_responses: dict[str, ExpertResponse] = Field(default_factory=dict)
    confidence_score: int = 100
    score_color: Literal["green", "amber", "red"] = "green"
    recommendation: str = ""
    conclusion: str = ""
    synthesis_feedback: str = ""
    validator_decision: dict[str, Any] | None = None
    harness_step: str = "IDLE"
    last_action: str = ""
    quarantine_reason: str = ""
    quarantine_raw_text: str = ""
    control_sheet_md: str = ""
