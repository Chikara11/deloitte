"""Gate 1 Security (No LLM): tenant_id isolation, Model Armor, deterministic pseudonymization."""

from __future__ import annotations

import hashlib
import hmac
import re
from dataclasses import dataclass

from app.config import settings

_INJECTION_PATTERNS = [
    re.compile(r"ignore\s+(all\s+)?(previous|prior)\s+instructions", re.IGNORECASE),
    re.compile(r"output\s+(your|the)\s+(internal\s+)?system\s+prompt", re.IGNORECASE),
    re.compile(r"mark\s+all\s+invoices?\s+compliant", re.IGNORECASE),
    re.compile(r"system\s+override", re.IGNORECASE),
]

_IBAN_RE = re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{11,30}\b")
_EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
_NAME_RE = re.compile(r"(?:Signataire|Signer|Contact)\s*:\s*([A-Z][a-z]+ [A-Z][a-z]+)|\(([A-Z][a-z]+ [A-Z][a-z]+)\)")


@dataclass
class ModelArmorVerdict:
    is_safe: bool
    provider: str
    matched_rule: str | None = None


class ServerVault:
    """Server-side only pseudonymization mapping (never sent to client/LLM)."""

    def __init__(self) -> None:
        self._token_to_raw: dict[str, str] = {}

    def tokenize(self, prefix: str, raw: str) -> str:
        clean = raw.strip()
        digest = hmac.new(settings.dlp_hmac_secret.encode("utf-8"), clean.encode("utf-8"), hashlib.sha256).hexdigest()[:4]
        tok = f"[{prefix}_{digest}]"
        self._token_to_raw[tok] = clean
        return tok

    def pseudonymize(self, text: str) -> tuple[str, int]:
        count = 0
        out = text

        def _iban(m: re.Match[str]) -> str:
            nonlocal count
            count += 1
            return self.tokenize("IBAN", m.group(0))

        def _email(m: re.Match[str]) -> str:
            nonlocal count
            count += 1
            return self.tokenize("EMAIL", m.group(0))

        out = _IBAN_RE.sub(_iban, out)
        out = _EMAIL_RE.sub(_email, out)

        for m in list(_NAME_RE.finditer(out)):
            raw_name = m.group(1) or m.group(2)
            if raw_name:
                tok = self.tokenize("PER", raw_name)
                out = out.replace(raw_name, tok)
                count += 1

        return out, count


server_vault = ServerVault()


def check_model_armor(text: str) -> ModelArmorVerdict:
    """Screen text with google-cloud-modelarmor (behind feature flag) + regex fallback."""
    if settings.use_real_model_armor:
        try:
            from google.cloud import modelarmor_v1

            client = modelarmor_v1.ModelArmorClient(
                transport="rest",
                client_options={"api_endpoint": f"modelarmor.{settings.gcp_region}.rep.googleapis.com"},
            )
            req = modelarmor_v1.SanitizeUserPromptRequest(
                name=settings.model_armor_template,
                user_prompt_data=modelarmor_v1.DataItem(text=text),
            )
            resp = client.sanitize_user_prompt(request=req)
            if str(resp.sanitization_result.filter_match_state) != "NO_MATCH_FOUND":
                return ModelArmorVerdict(is_safe=False, provider="google-cloud-modelarmor", matched_rule="MODEL_ARMOR_TEMPLATE")
            return ModelArmorVerdict(is_safe=True, provider="google-cloud-modelarmor")
        except Exception:
            pass

    for pat in _INJECTION_PATTERNS:
        m = pat.search(text)
        if m:
            return ModelArmorVerdict(is_safe=False, provider="model_armor_regex_fallback", matched_rule=m.group(0))
    return ModelArmorVerdict(is_safe=True, provider="model_armor_regex_fallback")
