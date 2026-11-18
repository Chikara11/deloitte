"""Tamper-evident governance audit logger: per-tenant SHA-256 hash chain + BigQuery sink + live SSE."""

from __future__ import annotations

import asyncio
import hashlib
import json
import sys
import threading
import uuid
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel

from app.config import settings

GENESIS_HASH = "0" * 64


class AuditEvent(BaseModel):
    """Single governance or agent telemetry event, chained to the previous event of the same tenant."""

    event_id: str
    timestamp: str
    deal_id: str  # tenant_id (kept as deal_id for BigQuery schema compatibility)
    agent_name: str
    event_type: str
    severity: str
    details: dict[str, Any]
    prev_hash: str = GENESIS_HASH
    hash: str = ""


def compute_event_hash(evt: AuditEvent) -> str:
    """SHA-256 over the canonical JSON of the event content + the previous hash."""
    payload = {
        "event_id": evt.event_id,
        "timestamp": evt.timestamp,
        "deal_id": evt.deal_id,
        "agent_name": evt.agent_name,
        "event_type": evt.event_type,
        "severity": evt.severity,
        "details": evt.details,
        "prev_hash": evt.prev_hash,
    }
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def verify_chain(events: list[AuditEvent]) -> dict[str, Any]:
    """Recompute the hash chain; any modified, deleted or reordered event breaks it."""
    prev = GENESIS_HASH
    for idx, evt in enumerate(events):
        if evt.prev_hash != prev or compute_event_hash(evt) != evt.hash:
            return {"valid": False, "events_checked": len(events), "broken_at": evt.event_id, "broken_index": idx}
        prev = evt.hash
    return {"valid": True, "events_checked": len(events), "head_hash": prev, "broken_at": None}


class AuditLogger:
    """Broadcasts governance events to SSE subscribers and appends them to BigQuery."""

    def __init__(self) -> None:
        self._events: list[AuditEvent] = []
        self._subscribers: list[asyncio.Queue[AuditEvent]] = []
        self._bq_client: Any = None
        self._heads: dict[str, str] = {}  # tenant_id -> last hash
        self._lock = threading.Lock()  # agents may log from worker threads

    def _get_bq(self) -> Any:
        if not settings.use_real_gcp_data:
            return None
        if self._bq_client is None:
            try:
                from google.cloud import bigquery

                self._bq_client = bigquery.Client(project=settings.gcp_project_id)
            except Exception as exc:
                print(f"[audit_logger] BigQuery client unavailable: {exc}", file=sys.stderr)
                self._bq_client = False
        return self._bq_client if self._bq_client is not False else None

    def log(
        self,
        deal_id: str,
        agent_name: str,
        event_type: str,
        severity: str = "INFO",
        details: dict[str, Any] | None = None,
    ) -> AuditEvent:
        """Record a chained audit event, notify SSE listeners, and append to BigQuery if enabled."""
        with self._lock:
            evt = AuditEvent(
                event_id=str(uuid.uuid4())[:12],
                timestamp=datetime.now(timezone.utc).isoformat(),
                deal_id=deal_id,
                agent_name=agent_name,
                event_type=event_type,
                severity=severity,
                details=json.loads(json.dumps(details or {}, default=str)),
                prev_hash=self._heads.get(deal_id, GENESIS_HASH),
            )
            evt.hash = compute_event_hash(evt)
            self._heads[deal_id] = evt.hash
            self._events.append(evt)

        for q in list(self._subscribers):
            q.put_nowait(evt)

        bq = self._get_bq()
        if bq is not None:
            try:
                table_id = f"{settings.gcp_project_id}.{settings.bq_dataset}.{settings.bq_audit_table}"
                row = {
                    "event_id": evt.event_id,
                    "timestamp": evt.timestamp,
                    "deal_id": evt.deal_id,
                    "agent_name": evt.agent_name,
                    "event_type": evt.event_type,
                    "severity": evt.severity,
                    "details_json": json.dumps(evt.details, ensure_ascii=False),
                    "prev_hash": evt.prev_hash,
                    "hash": evt.hash,
                }
                # ignore_unknown_values keeps inserts working on tables created before the hash columns existed
                errors = bq.insert_rows_json(table_id, [row], ignore_unknown_values=True)
                if errors:
                    print(f"[audit_logger] BigQuery insert errors: {errors}", file=sys.stderr)
            except Exception as exc:
                print(f"[audit_logger] BigQuery insert failed: {exc}", file=sys.stderr)
        return evt

    def list_events(self, deal_id: str | None = None) -> list[AuditEvent]:
        """Return recorded events, optionally filtered by deal_id."""
        if deal_id is None:
            return list(self._events)
        return [e for e in self._events if e.deal_id == deal_id]

    def verify(self, deal_id: str, simulate_tamper: bool = False) -> dict[str, Any]:
        """Verify a tenant's chain. simulate_tamper alters a COPY of one event to show detection (non-destructive)."""
        events = [e.model_copy(deep=True) for e in self.list_events(deal_id)]
        tampered_id = None
        if simulate_tamper and events:
            target = events[len(events) // 2]
            target.details = {**target.details, "decision": "VALIDER", "_forged": True}
            tampered_id = target.event_id
        res = verify_chain(events)
        res["simulated_tamper_on"] = tampered_id
        return res

    def subscribe(self) -> asyncio.Queue[AuditEvent]:
        """Register a new SSE subscriber queue."""
        q: asyncio.Queue[AuditEvent] = asyncio.Queue()
        self._subscribers.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue[AuditEvent]) -> None:
        """Remove an SSE subscriber queue."""
        if q in self._subscribers:
            self._subscribers.remove(q)


audit_logger = AuditLogger()
