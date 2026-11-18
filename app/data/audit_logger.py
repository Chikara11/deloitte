"""Immutable governance audit logger with BigQuery sink + live SSE event stream."""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel

from app.config import settings


class AuditEvent(BaseModel):
    """Single governance or agent telemetry event."""

    event_id: str
    timestamp: str
    deal_id: str
    agent_name: str
    event_type: str
    severity: str
    details: dict[str, Any]


class AuditLogger:
    """Broadcasts governance events to SSE subscribers and optionally BigQuery."""

    def __init__(self) -> None:
        self._events: list[AuditEvent] = []
        self._subscribers: list[asyncio.Queue[AuditEvent]] = []
        self._bq_client: Any = None

    def _get_bq(self) -> Any:
        if not settings.use_real_gcp_data:
            return None
        if self._bq_client is None:
            try:
                from google.cloud import bigquery

                self._bq_client = bigquery.Client(project=settings.gcp_project_id)
            except Exception:
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
        """Record an audit event, notify SSE listeners, and sink to BigQuery if enabled."""
        evt = AuditEvent(
            event_id=str(uuid.uuid4())[:12],
            timestamp=datetime.now(timezone.utc).isoformat(),
            deal_id=deal_id,
            agent_name=agent_name,
            event_type=event_type,
            severity=severity,
            details=details or {},
        )
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
                    "details_json": json.dumps(evt.details),
                }
                bq.insert_rows_json(table_id, [row])
            except Exception:
                pass
        return evt

    def list_events(self, deal_id: str | None = None) -> list[AuditEvent]:
        """Return recorded events, optionally filtered by deal_id."""
        if deal_id is None:
            return list(self._events)
        return [e for e in self._events if e.deal_id == deal_id]

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
