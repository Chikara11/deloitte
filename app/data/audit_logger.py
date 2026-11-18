"""Append-only Hash-Chained Audit Log (Firestore + In-Memory Fallback + Cloud Logging JSON + SSE)."""

from __future__ import annotations

import asyncio
import csv
import hashlib
import io
import json
import sys
import uuid
from datetime import datetime, timezone
from typing import Any

from app.agents.models import AuditCase, AuditEvent
from app.config import settings

GENESIS_HASH = "0" * 64


def _compute_event_hash(payload_without_hash: dict[str, Any], prev_hash: str) -> str:
    canonical = json.dumps(payload_without_hash, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(f"{canonical}|{prev_hash}".encode("utf-8")).hexdigest()


class AuditLogger:
    """Append-only tamper-evident audit store and stateless case repository."""

    def __init__(self) -> None:
        self._events: list[AuditEvent] = []
        self._cases: dict[str, AuditCase] = {}
        self._subscribers: list[asyncio.Queue[AuditEvent]] = []
        self._fs_client: Any = None
        self.metrics: dict[str, Any] = {
            "tenant_verified": True,
            "pii_masked_count": 0,
            "model_armor_blocks": 0,
            "skeptic_rejections": 0,
            "current_harness_step": "IDLE",
            "storage_backend": "memory",
        }

    def _get_firestore(self) -> Any:
        if not settings.use_real_gcp_data:
            return None
        if self._fs_client is None:
            try:
                from google.cloud import firestore

                client = firestore.Client(project=settings.gcp_project_id)
                # Quick connectivity check (non-destructive)
                list(client.collection("audit_events").limit(1).stream())
                self._fs_client = client
                self.metrics["storage_backend"] = "firestore"
            except Exception:
                self._fs_client = False
                self.metrics["storage_backend"] = "memory"
        return self._fs_client if self._fs_client is not False else None

    def set_step(self, step: str) -> None:
        self.metrics["current_harness_step"] = step

    def reset_memory(self) -> None:
        """Reset in-memory state (used for local demo reseed / unit tests)."""
        self._events.clear()
        self._cases.clear()
        self.metrics.update(
            {
                "tenant_verified": True,
                "pii_masked_count": 0,
                "model_armor_blocks": 0,
                "skeptic_rejections": 0,
                "current_harness_step": "IDLE",
            }
        )

    # ── Stateless Case Repository (Firestore + Memory fallback) ───────────────

    def save_case(self, case: AuditCase) -> None:
        self._cases[case.case_id] = case
        fs = self._get_firestore()
        if fs:
            try:
                fs.collection("audit_cases").document(case.case_id.replace("/", "_")).set(case.model_dump())
            except Exception:
                pass

    def get_case(self, case_id: str) -> AuditCase | None:
        if case_id in self._cases:
            return self._cases[case_id]
        fs = self._get_firestore()
        if fs:
            try:
                doc = fs.collection("audit_cases").document(case_id.replace("/", "_")).get()
                if doc.exists:
                    case = AuditCase.model_validate(doc.to_dict())
                    self._cases[case.case_id] = case
                    return case
            except Exception:
                pass
        return None

    def list_cases(self, tenant_id: str | None = None) -> list[AuditCase]:
        fs = self._get_firestore()
        if fs and not self._cases:
            try:
                for doc in fs.collection("audit_cases").stream():
                    case = AuditCase.model_validate(doc.to_dict())
                    self._cases[case.case_id] = case
            except Exception:
                pass
        items = list(self._cases.values())
        if tenant_id:
            items = [c for c in items if c.tenant_id == tenant_id]
        return items

    # ── Append-Only Hash-Chained Events ───────────────────────────────────────

    def _last_hash_for_case(self, case_id: str) -> str:
        case_events = [e for e in self._events if e.case_id == case_id]
        if case_events:
            return case_events[-1].hash
        fs = self._get_firestore()
        if fs:
            try:
                docs = (
                    fs.collection("audit_events")
                    .where("case_id", "==", case_id)
                    .order_by("timestamp_utc", direction="DESCENDING")
                    .limit(1)
                    .stream()
                )
                for d in docs:
                    return str(d.to_dict().get("hash", GENESIS_HASH))
            except Exception:
                pass
        return GENESIS_HASH

    def record_event(
        self,
        *,
        session_id: str,
        tenant_id: str,
        case_id: str,
        gate: str,
        actor_type: str,
        actor_id: str,
        actor_role: str,
        action: str,
        decision: str,
        comment: str = "",
        before: dict[str, Any] | None = None,
        after: dict[str, Any] | None = None,
        model_name: str | None = None,
        prompt_hash: str | None = None,
        evidence_refs: list[str] | None = None,
    ) -> AuditEvent:
        prev_hash = self._last_hash_for_case(case_id)
        event_id = str(uuid.uuid4())
        timestamp_utc = datetime.now(timezone.utc).isoformat()
        payload = {
            "event_id": event_id,
            "timestamp_utc": timestamp_utc,
            "session_id": session_id,
            "tenant_id": tenant_id,
            "case_id": case_id,
            "gate": gate,
            "actor_type": actor_type,
            "actor_id": actor_id,
            "actor_role": actor_role,
            "action": action,
            "decision": decision,
            "comment": comment,
            "before": before,
            "after": after,
            "model_name": model_name,
            "prompt_hash": prompt_hash,
            "evidence_refs": evidence_refs or [],
            "prev_hash": prev_hash,
        }
        event_hash = _compute_event_hash(payload, prev_hash)
        evt = AuditEvent(**payload, hash=event_hash)
        self._events.append(evt)

        # Update trust metrics
        if action == "DLP_MASKED":
            self.metrics["pii_masked_count"] += int((after or {}).get("count", 0))
        elif action == "MODEL_ARMOR_BLOCK":
            self.metrics["model_armor_blocks"] += 1
        elif action == "SKEPTIC_REJECT":
            self.metrics["skeptic_rejections"] += 1
        elif action == "TENANT_ISOLATION_BLOCK":
            self.metrics["tenant_verified"] = False

        # Structured JSON log to stdout for Cloud Logging
        severity = "WARNING" if decision in {"BLOCK", "REJECT", "REJECTED"} else "INFO"
        print(json.dumps({"severity": severity, **evt.model_dump()}, default=str), file=sys.stdout, flush=True)

        # Append-only Firestore write (never update/delete)
        fs = self._get_firestore()
        if fs:
            try:
                fs.collection("audit_events").document(evt.event_id).set(evt.model_dump())
            except Exception:
                pass

        # Broadcast via SSE
        for q in list(self._subscribers):
            try:
                q.put_nowait(evt)
            except asyncio.QueueFull:
                pass

        return evt

    def log(
        self,
        session_id: str,
        tenant_id: str,
        agent: str,
        action: str,
        verdict: str,
        details: dict[str, Any] | None = None,
        case_id: str = "SYSTEM",
        gate: str = "SYSTEM",
    ) -> AuditEvent:
        """Compatibility helper mapping legacy log calls into hash-chained AuditEvents."""
        actor_type = "agent" if agent.endswith("Agent") else "system"
        cid = case_id if case_id != "SYSTEM" else str((details or {}).get("case_id", session_id))
        return self.record_event(
            session_id=session_id,
            tenant_id=tenant_id,
            case_id=cid,
            gate=gate,
            actor_type=actor_type,
            actor_id=agent,
            actor_role=agent,
            action=action,
            decision=verdict,
            comment=str((details or {}).get("reason", "")),
            after=details or {},
        )

    def list_events(
        self,
        *,
        case_id: str | None = None,
        actor_id: str | None = None,
        actor_role: str | None = None,
        gate: str | None = None,
        action: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
    ) -> list[AuditEvent]:
        events = list(self._events)
        fs = self._get_firestore()
        if fs and not events:
            try:
                docs = fs.collection("audit_events").order_by("timestamp_utc").stream()
                events = [AuditEvent.model_validate(d.to_dict()) for d in docs]
                self._events = events
            except Exception:
                pass

        if case_id:
            events = [e for e in events if case_id.lower() in e.case_id.lower()]
        if actor_id:
            events = [e for e in events if actor_id.lower() in e.actor_id.lower()]
        if actor_role:
            events = [e for e in events if actor_role.lower() in e.actor_role.lower()]
        if gate:
            events = [e for e in events if gate.lower() == e.gate.lower()]
        if action:
            events = [e for e in events if action.lower() in e.action.lower()]
        if date_from:
            events = [e for e in events if e.timestamp_utc >= date_from]
        if date_to:
            events = [e for e in events if e.timestamp_utc <= date_to]
        return events

    def verify_chain(self, case_id: str) -> dict[str, Any]:
        events = [e for e in self.list_events() if e.case_id == case_id]
        events.sort(key=lambda e: e.timestamp_utc)
        if not events:
            return {"case_id": case_id, "valid": True, "event_count": 0, "first_broken_event_id": None}

        expected_prev = GENESIS_HASH
        for idx, evt in enumerate(events):
            if evt.prev_hash != expected_prev:
                return {
                    "case_id": case_id,
                    "valid": False,
                    "event_count": len(events),
                    "first_broken_event_id": evt.event_id,
                    "reason": f"prev_hash mismatch at index {idx}",
                }
            payload = evt.model_dump(exclude={"hash"})
            recomputed = _compute_event_hash(payload, expected_prev)
            if recomputed != evt.hash:
                return {
                    "case_id": case_id,
                    "valid": False,
                    "event_count": len(events),
                    "first_broken_event_id": evt.event_id,
                    "reason": f"SHA-256 hash mismatch at index {idx}",
                }
            expected_prev = evt.hash

        return {
            "case_id": case_id,
            "valid": True,
            "event_count": len(events),
            "first_broken_event_id": None,
            "head_hash": expected_prev,
        }

    def export_events_csv(self, **filters: str | None) -> str:
        events = self.list_events(**filters)
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(
            [
                "event_id",
                "timestamp_utc",
                "session_id",
                "tenant_id",
                "case_id",
                "gate",
                "actor_type",
                "actor_id",
                "actor_role",
                "action",
                "decision",
                "comment",
                "model_name",
                "prompt_hash",
                "prev_hash",
                "hash",
            ]
        )
        for e in events:
            writer.writerow(
                [
                    e.event_id,
                    e.timestamp_utc,
                    e.session_id,
                    e.tenant_id,
                    e.case_id,
                    e.gate,
                    e.actor_type,
                    e.actor_id,
                    e.actor_role,
                    e.action,
                    e.decision,
                    e.comment,
                    e.model_name or "",
                    e.prompt_hash or "",
                    e.prev_hash,
                    e.hash,
                ]
            )
        return buf.getvalue()

    def subscribe(self) -> asyncio.Queue[AuditEvent]:
        q: asyncio.Queue[AuditEvent] = asyncio.Queue(maxsize=200)
        self._subscribers.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue[AuditEvent]) -> None:
        if q in self._subscribers:
            self._subscribers.remove(q)


audit_logger = AuditLogger()
