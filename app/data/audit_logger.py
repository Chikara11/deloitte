"""Structured JSON Cloud Logging + BigQuery Audit Sink + SSE Live Stream + Trust Metrics."""

from __future__ import annotations

import asyncio
import json
import sys
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel

from app.config import settings


class StructuredLogEvent(BaseModel):
    session_id: str
    tenant_id: str
    agent: str
    action: str
    verdict: str  # PASS | BLOCK | ANOMALIE | REJECT | INFO
    timestamp: str
    details: dict[str, Any] = {}


class AuditLogger:
    def __init__(self) -> None:
        self._logs: list[StructuredLogEvent] = []
        self._subscribers: list[asyncio.Queue[StructuredLogEvent]] = []
        self._bq_client: Any = None
        self.metrics: dict[str, Any] = {
            "tenant_verified": True,
            "pii_masked_count": 0,
            "model_armor_blocks": 0,
            "skeptic_rejections": 0,
            "current_harness_step": "IDLE",
        }

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

    def set_step(self, step: str) -> None:
        self.metrics["current_harness_step"] = step

    def log(
        self,
        session_id: str,
        tenant_id: str,
        agent: str,
        action: str,
        verdict: str,
        details: dict[str, Any] | None = None,
    ) -> StructuredLogEvent:
        evt = StructuredLogEvent(
            session_id=session_id,
            tenant_id=tenant_id,
            agent=agent,
            action=action,
            verdict=verdict,
            timestamp=datetime.now(timezone.utc).isoformat(),
            details=details or {},
        )
        self._logs.append(evt)

        if action == "DLP_MASKED":
            self.metrics["pii_masked_count"] += int((details or {}).get("count", 0))
        elif action == "MODEL_ARMOR_BLOCK":
            self.metrics["model_armor_blocks"] += 1
        elif action == "SKEPTIC_REJECT":
            self.metrics["skeptic_rejections"] += 1
        elif action == "TENANT_ISOLATION_BLOCK":
            self.metrics["tenant_verified"] = False

        # Emit structured JSON to stdout for Cloud Logging
        print(json.dumps({"severity": "WARNING" if verdict in ("BLOCK", "REJECT") else "INFO", **evt.model_dump()}), file=sys.stdout, flush=True)

        for q in list(self._subscribers):
            q.put_nowait(evt)

        bq = self._get_bq()
        if bq is not None:
            try:
                table_id = f"{settings.gcp_project_id}.{settings.bq_dataset}.{settings.bq_audit_table}"
                bq.insert_rows_json(
                    table_id,
                    [
                        {
                            "event_id": f"{session_id}-{len(self._logs)}",
                            "timestamp": evt.timestamp,
                            "deal_id": evt.tenant_id,
                            "agent_name": evt.agent,
                            "event_type": evt.action,
                            "severity": evt.verdict,
                            "details_json": json.dumps(evt.details),
                        }
                    ],
                )
            except Exception:
                pass
        return evt

    def list_logs(self, tenant_id: str | None = None) -> list[StructuredLogEvent]:
        if tenant_id is None:
            return list(self._logs)
        return [e for e in self._logs if e.tenant_id == tenant_id]

    def clear(self) -> None:
        self._logs.clear()
        self.metrics = {
            "tenant_verified": True,
            "pii_masked_count": 0,
            "model_armor_blocks": 0,
            "skeptic_rejections": 0,
            "current_harness_step": "IDLE",
        }

    def subscribe(self) -> asyncio.Queue[StructuredLogEvent]:
        q: asyncio.Queue[StructuredLogEvent] = asyncio.Queue()
        self._subscribers.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue[StructuredLogEvent]) -> None:
        if q in self._subscribers:
            self._subscribers.remove(q)


audit_logger = AuditLogger()
