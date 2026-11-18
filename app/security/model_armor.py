"""Chunk-level indirect prompt injection defense via GCP Model Armor + heuristic fallback."""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.config import settings

_INJECTION_PATTERNS = [
    re.compile(r"ignore\s+(all\s+)?(previous|prior)\s+instructions", re.IGNORECASE),
    re.compile(r"system\s+override", re.IGNORECASE),
    re.compile(r"output\s+(your|the)\s+(internal\s+)?system\s+prompt", re.IGNORECASE),
    re.compile(r"(rate|mark|conclude).{0,40}(zero\s+risk|safe|approve\s+the\s+eur)", re.IGNORECASE),
    re.compile(r"disregard\s+all\s+guardrails", re.IGNORECASE),
]


@dataclass
class ArmorResult:
    """Result of screening a single document chunk."""

    is_safe: bool
    provider: str
    matched_rule: str | None = None


def scan_chunk(text: str) -> ArmorResult:
    """Screen a text chunk for indirect prompt injection.

    Uses GCP Model Armor when USE_REAL_MODEL_ARMOR=true, with a deterministic
    pattern guard as defense-in-depth / local fallback.
    """
    if settings.use_real_model_armor:
        try:
            from google.cloud import modelarmor_v1

            client = modelarmor_v1.ModelArmorClient(
                transport="rest",
                client_options={"api_endpoint": f"modelarmor.{settings.gcp_region}.rep.googleapis.com"},
            )
            req = modelarmor_v1.SanitizeUserPromptRequest(
                name=f"projects/{settings.gcp_project_id}/locations/{settings.gcp_region}/templates/war-room-shield",
                user_prompt_data=modelarmor_v1.DataItem(text=text),
            )
            resp = client.sanitize_user_prompt(request=req)
            if str(resp.sanitization_result.filter_match_state) != "NO_MATCH_FOUND":
                return ArmorResult(is_safe=False, provider="gcp_model_armor", matched_rule="MODEL_ARMOR_PI_MATCH")
            return ArmorResult(is_safe=True, provider="gcp_model_armor")
        except Exception:
            # Fall through to deterministic defense-in-depth if API/template isn't provisioned
            pass

    for pat in _INJECTION_PATTERNS:
        m = pat.search(text)
        if m:
            return ArmorResult(is_safe=False, provider="model_armor_shield", matched_rule=m.group(0))
    return ArmorResult(is_safe=True, provider="model_armor_shield")
