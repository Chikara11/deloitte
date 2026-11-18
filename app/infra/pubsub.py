"""Publish 'case evaluated' events to Pub/Sub to start the Cloud Workflows Human Gates (optional).

Disabled unless PUBSUB_TOPIC is set. Uses the Pub/Sub REST API with google-auth (no extra dependency).
Only identifiers and statuses are published: no invoice content, no PII.
"""

from __future__ import annotations

import base64
import json
import sys

from app.agents.models import AuditCase
from app.config import settings
from app.data.audit_logger import audit_logger

_session = None


def _get_session():
    global _session
    if _session is None:
        import google.auth
        from google.auth.transport.requests import AuthorizedSession

        creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/pubsub"])
        _session = AuthorizedSession(creds)
    return _session


def publish_case_evaluated(case: AuditCase) -> bool:
    """Publish a minimal case event; never raises (the synchronous UI flow keeps working)."""
    if not settings.pubsub_topic:
        return False
    message = {
        "case_id": case.case_id,
        "tenant_id": case.tenant_id,
        "status": case.status,
        "expert_roles": [b.role for b in case.micro_briefs],
        "confidence_score": case.confidence_score,
    }
    topic = f"projects/{settings.gcp_project_id}/topics/{settings.pubsub_topic}"
    try:
        resp = _get_session().post(
            f"https://pubsub.googleapis.com/v1/{topic}:publish",
            json={
                "messages": [
                    {
                        "data": base64.b64encode(json.dumps(message).encode("utf-8")).decode("ascii"),
                        "attributes": {"tenant_id": case.tenant_id, "status": case.status},
                    }
                ]
            },
            timeout=3,
        )
        resp.raise_for_status()
        audit_logger.log(case.tenant_id, "orchestrator", "WORKFLOW_TRIGGERED", "INFO",
                         {"case_id": case.case_id, "topic": settings.pubsub_topic})
        return True
    except Exception as exc:
        print(f"[pubsub] publish failed for {case.case_id}: {exc}", file=sys.stderr)
        return False
