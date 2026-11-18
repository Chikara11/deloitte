"""Shared Pydantic schemas for findings, entity graph, and deal valuation."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class Finding(BaseModel):
    """Single verified or candidate M&A risk finding."""

    finding_id: str
    agent: str
    category: str  # LEGAL | QUANT | FORENSIC | CYBER_TAMPERING
    severity: str  # LOW | MEDIUM | HIGH | CRITICAL
    title: str
    summary: str
    doc_name: str | None = None
    page_num: int | None = None
    chunk_id: str | None = None
    exact_quote: str | None = None
    sql_query: str | None = None
    bq_job_id: str | None = None
    metric_value: float | None = None
    verified: bool = False
    verification_note: str = ""


class GraphNode(BaseModel):
    id: str
    label: str
    kind: str  # PERSON | IBAN | COMPANY


class GraphEdge(BaseModel):
    source: str
    target: str
    relation: str
    doc_name: str


class EntityGraph(BaseModel):
    nodes: list[GraphNode] = Field(default_factory=list)
    edges: list[GraphEdge] = Field(default_factory=list)


class PriceChipItem(BaseModel):
    rule_name: str
    impact_eur: float
    action: str


class DealReport(BaseModel):
    deal_id: str
    deal_status: str  # CLEAR | CAUTION | CRITICAL_WALK_AWAY
    proposed_price_eur: float = 200_000_000.0
    adjusted_price_eur: float = 200_000_000.0
    total_price_chip_eur: float = 0.0
    price_chips: list[PriceChipItem] = Field(default_factory=list)
    findings: list[Finding] = Field(default_factory=list)
    entity_graph: EntityGraph = Field(default_factory=EntityGraph)
    tampering_detected: bool = False
    pii_unmasked: bool = False
    partner_signoff: dict[str, Any] | None = None
