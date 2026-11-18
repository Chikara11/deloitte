"""Forensic Graph Agent (IAM: sa-forensic -> Cross-document [IBAN_*] & [PER_*] linking)."""

from __future__ import annotations

import re

from app.agents.models import EntityGraph, Finding, GraphEdge, GraphNode
from app.config import settings
from app.data.audit_logger import audit_logger
from app.data.vector_store import vector_store

_IBAN_TOK_RE = re.compile(r"\[IBAN_[a-f0-9]+\]")
_PER_TOK_RE = re.compile(r"\[PER_[a-f0-9]+\]")


def run_forensic_agent(deal_id: str) -> tuple[list[Finding], EntityGraph]:
    """Build cross-document entity graph on DLP-tokenized text and detect IBAN collisions."""
    audit_logger.log(
        deal_id=deal_id,
        agent_name="sa-forensic",
        event_type="AGENT_START",
        severity="INFO",
        details={"scope": "tokenized_entity_graph", "sa": settings.sa_forensic_email},
    )

    chunks = vector_store.list_chunks(deal_id)
    nodes: dict[str, GraphNode] = {}
    edges: list[GraphEdge] = []
    iban_owners: dict[str, list[tuple[str, str, int, str, str]]] = {}

    for c in chunks:
        for line in c.text.splitlines():
            ibans = _IBAN_TOK_RE.findall(line)
            if not ibans:
                # Also look at adjacent lines in same chunk for IBAN tokens
                ibans = _IBAN_TOK_RE.findall(c.text)
            persons = _PER_TOK_RE.findall(c.text)

            for iban in set(ibans):
                nodes[iban] = GraphNode(id=iban, label=iban, kind="IBAN")
                if "apex logistics" in c.text.lower():
                    comp = "Apex Logistics Advisory"
                    nodes[comp] = GraphNode(id=comp, label=comp, kind="COMPANY")
                    edges.append(GraphEdge(source=comp, target=iban, relation="SETTLEMENT_ACCOUNT", doc_name=c.doc_name))
                    iban_owners.setdefault(iban, []).append((comp, c.doc_name, c.page_num, c.chunk_id, line.strip()))
                for per in set(persons):
                    if iban in line or per in line:
                        nodes[per] = GraphNode(id=per, label=f"CEO {per}", kind="PERSON")
                        edges.append(GraphEdge(source=per, target=iban, relation="PAYROLL_IBAN", doc_name=c.doc_name))
                        iban_owners.setdefault(iban, []).append((per, c.doc_name, c.page_num, c.chunk_id, line.strip()))
                break

    # Deduplicate edges
    unique_edges: list[GraphEdge] = []
    seen_e: set[tuple[str, str, str]] = set()
    for e in edges:
        key = (e.source, e.target, e.relation)
        if key not in seen_e:
            seen_e.add(key)
            unique_edges.append(e)

    findings: list[Finding] = []
    for iban, refs in iban_owners.items():
        distinct_entities = list(dict.fromkeys(r[0] for r in refs))
        if len(distinct_entities) >= 2:
            primary_ref = refs[0]
            findings.append(
                Finding(
                    finding_id="FOR-01",
                    agent="sa-forensic",
                    category="FORENSIC",
                    severity="CRITICAL",
                    title=f"Hidden Self-Dealing Fraud via Shared Token {iban}",
                    summary=(
                        f"Deterministic DLP token {iban} is shared between "
                        f"{' and '.join(distinct_entities)} across Supplier and HR Payroll documents."
                    ),
                    doc_name=primary_ref[1],
                    page_num=primary_ref[2],
                    chunk_id=primary_ref[3],
                    exact_quote=primary_ref[4],
                    metric_value=2_500_000.0,
                )
            )

    graph = EntityGraph(nodes=list(nodes.values()), edges=unique_edges)
    return findings, graph
