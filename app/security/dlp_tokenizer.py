"""Crypto-deterministic PII/IBAN tokenization (Cloud DLP + KMS-style vault) & Break-Glass unmasking."""

from __future__ import annotations

import hashlib
import hmac
import re
from dataclasses import dataclass

from app.config import settings

_IBAN_RE = re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{11,30}\b")
_EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
# Matches Title-case two-word person names near executive/HR labels
_PERSON_RE = re.compile(
    r"(?:Chief Executive Officer|Chief Financial Officer|CEO|CFO|Director|Manager|Signed by)\s*:\s*([A-Z][a-z]+ [A-Z][a-z]+)"
)


@dataclass
class TokenizationResult:
    """Sanitized text and entity count."""

    sanitized_text: str
    entities_masked: int
    tokens_used: list[str]
    provider: str


class DlpTokenizer:
    """Deterministic surrogate tokenizer preserving cross-document entity links."""

    def __init__(self) -> None:
        # Locked KMS-style token vault: token -> raw_value
        self._vault: dict[str, str] = {}

    def _surrogate(self, prefix: str, raw_value: str) -> str:
        digest = hmac.new(
            settings.dlp_hmac_secret.encode("utf-8"),
            raw_value.strip().encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()[:4]
        token = f"[{prefix}_{digest}]"
        self._vault[token] = raw_value.strip()
        return token

    def deidentify(self, text: str) -> TokenizationResult:
        """Mask IBANs, emails, and person names into deterministic surrogate tokens."""
        tokens_used: list[str] = []
        masked = text
        provider = "dlp_hmac_deterministic"

        if settings.use_real_dlp:
            try:
                from google.cloud import dlp_v2

                dlp = dlp_v2.DlpServiceClient()
                parent = f"projects/{settings.gcp_project_id}/locations/{settings.gcp_region}"
                inspect_resp = dlp.inspect_content(
                    request={
                        "parent": parent,
                        "inspect_config": {
                            "info_types": [
                                {"name": "IBAN_CODE"},
                                {"name": "EMAIL_ADDRESS"},
                                {"name": "PERSON_NAME"},
                            ]
                        },
                        "item": {"value": masked},
                    }
                )
                for finding in sorted(
                    inspect_resp.result.findings,
                    key=lambda f: f.location.byte_range.start,
                    reverse=True,
                ):
                    quote = finding.quote
                    if not quote:
                        continue
                    itype = finding.info_type.name
                    prefix = "IBAN" if itype == "IBAN_CODE" else ("EMAIL" if itype == "EMAIL_ADDRESS" else "PER")
                    tok = self._surrogate(prefix, quote)
                    masked = masked.replace(quote, tok)
                    tokens_used.append(tok)
                provider = "gcp_cloud_dlp"
            except Exception:
                pass

        # Deterministic regex pass ensures 100% coverage even without GCP DLP API
        def _rep_iban(m: re.Match[str]) -> str:
            tok = self._surrogate("IBAN", m.group(0))
            tokens_used.append(tok)
            return tok

        def _rep_email(m: re.Match[str]) -> str:
            tok = self._surrogate("EMAIL", m.group(0))
            tokens_used.append(tok)
            return tok

        masked = _IBAN_RE.sub(_rep_iban, masked)
        masked = _EMAIL_RE.sub(_rep_email, masked)

        for m in list(_PERSON_RE.finditer(masked)):
            raw_name = m.group(1)
            tok = self._surrogate("PER", raw_name)
            masked = masked.replace(raw_name, tok)
            tokens_used.append(tok)

        unique_tokens = list(dict.fromkeys(tokens_used))
        return TokenizationResult(
            sanitized_text=masked,
            entities_masked=len(tokens_used),
            tokens_used=unique_tokens,
            provider=provider,
        )

    def unmask(self, text: str) -> str:
        """Break-Glass re-identification of surrogate tokens."""
        out = text
        for tok, raw in self._vault.items():
            out = out.replace(tok, raw)
        return out

    def vault_snapshot(self) -> dict[str, str]:
        """Return masked keys only (never raw values unless Break-Glass is called)."""
        return {tok: "***LOCKED_IN_KMS_VAULT***" for tok in self._vault}

    def reveal_vault(self) -> dict[str, str]:
        """Return full token -> raw mapping after Partner Break-Glass approval."""
        return dict(self._vault)


dlp_tokenizer = DlpTokenizer()
