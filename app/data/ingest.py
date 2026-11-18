"""Gate 1 (Cyber Firewall) + Client Passport Normalization -> Canonical JSON."""

from __future__ import annotations

import csv
import io
import re
from pathlib import Path
from typing import Any

from pypdf import PdfReader

from app.agents.models import CanonicalInvoice, LedgerEntry, SecurityMeta
from app.data.audit_logger import audit_logger
from app.data.passports import get_passport
from app.security.dlp_tokenizer import dlp_tokenizer
from app.security.model_armor import scan_chunk


class QuarantineError(Exception):
    """Raised when Gate 1 blocks a document (tenant mismatch or Model Armor)."""

    def __init__(self, reason: str, event_type: str, details: dict[str, Any]) -> None:
        super().__init__(reason)
        self.reason = reason
        self.event_type = event_type
        self.details = details


def _check_tenant(expected_tenant: str, doc_tenant: str, filename: str) -> None:
    if doc_tenant and doc_tenant != expected_tenant:
        details = {
            "expected_tenant": expected_tenant,
            "found_tenant": doc_tenant,
            "source_file": filename,
        }
        audit_logger.log(
            deal_id=expected_tenant,
            agent_name="gate1_cyber",
            event_type="TENANT_ISOLATION_BLOCK",
            severity="CRITICAL",
            details=details,
        )
        raise QuarantineError(
            f"Tenant isolation violation: {filename} belongs to {doc_tenant}, not {expected_tenant}.",
            "TENANT_ISOLATION_BLOCK",
            details,
        )


def ingest_csv_to_canonical(expected_tenant: str, filename: str, data: bytes) -> list[CanonicalInvoice]:
    """Gate 1 + Passport mapping for ERP CSV exports."""
    passport = get_passport(expected_tenant)
    text = data.decode("utf-8")
    reader = csv.DictReader(io.StringIO(text))
    invoices: list[CanonicalInvoice] = []

    for row in reader:
        doc_tenant = row.get("tenant_id", expected_tenant).strip()
        _check_tenant(expected_tenant, doc_tenant, filename)

        # Gate 1 Model Armor check on description
        desc = row.get("Description", "")
        armor = scan_chunk(desc)
        if not armor.is_safe:
            details = {"source_file": filename, "rule": armor.matched_rule, "provider": armor.provider}
            audit_logger.log(expected_tenant, "gate1_cyber", "MODEL_ARMOR_BLOCK", "CRITICAL", details)
            raise QuarantineError("Model Armor blocked malicious CSV payload.", "MODEL_ARMOR_BLOCK", details)

        # Gate 1 DLP pseudonymization on supplier/customer
        sup_res = dlp_tokenizer.deidentify(row.get("Fournisseur", "Fournisseur"))
        cust_res = dlp_tokenizer.deidentify(row.get("Client", "Client"))
        masked = sup_res.entities_masked + cust_res.entities_masked

        audit_logger.log(
            expected_tenant,
            "gate1_cyber",
            "GATE1_PASS",
            "INFO",
            {"source_file": filename, "tenant_verified": True, "pii_masked": masked, "norme": passport.norme},
        )

        ht = float(row.get("Montant_HT", 0))
        vat = float(row.get("Taux_TVA", 0))
        invoices.append(
            CanonicalInvoice(
                tenant_id=expected_tenant,
                invoice_id=row.get("Num_Fact", "F-UNKNOWN"),
                supplier=sup_res.sanitized_text,
                customer=cust_res.sanitized_text,
                is_intercompany=row.get("Intercompagnie", "false").lower() == "true",
                amount_ht=ht,
                vat_rate=vat,
                amount_ttc=ht * (1.0 + vat),
                invoice_date=row.get("Date_Fact", "2026-12-01"),
                service_date=row.get("Date_Prest", "2026-12-01"),
                ledger_entry=LedgerEntry(
                    account=row.get("Compte", "622600"),
                    amount=float(row.get("Montant_Ecriture", ht)),
                    period=row.get("Periode", "2026-12"),
                ),
                description=desc,
                source_file=filename,
                security=SecurityMeta(model_armor="clean", pii_masked=masked, tenant_verified=True),
            )
        )
    return invoices


def ingest_pdf_to_canonical(expected_tenant: str, filename: str, data: bytes) -> list[CanonicalInvoice]:
    """Gate 1 (tenant_id + Model Armor + DLP) + PDF normalization into Canonical JSON."""
    passport = get_passport(expected_tenant)
    reader = PdfReader(io.BytesIO(data))
    full_raw = "\n".join((p.extract_text() or "") for p in reader.pages)

    # 1. Tenant check
    t_match = re.search(r"TENANT_ID:\s*([A-Z0-9_]+)", full_raw)
    if t_match:
        _check_tenant(expected_tenant, t_match.group(1).strip(), filename)

    # 2. Model Armor line-by-line check
    for line in full_raw.splitlines():
        armor = scan_chunk(line)
        if not armor.is_safe:
            details = {
                "source_file": filename,
                "matched_rule": armor.matched_rule,
                "provider": armor.provider,
                "snippet": line[:120],
            }
            audit_logger.log(expected_tenant, "gate1_cyber", "MODEL_ARMOR_BLOCK", "CRITICAL", details)
            raise QuarantineError(
                f"Model Armor quarantined {filename}: prompt injection detected ({armor.matched_rule}).",
                "MODEL_ARMOR_BLOCK",
                details,
            )

    # 3. DLP pseudonymization
    dlp_res = dlp_tokenizer.deidentify(full_raw)
    clean = dlp_res.sanitized_text
    audit_logger.log(
        expected_tenant,
        "gate1_cyber",
        "DLP_MASKED",
        "INFO",
        {"source_file": filename, "pii_masked": dlp_res.entities_masked, "tokens": dlp_res.tokens_used, "norme": passport.norme},
    )

    def _find(pattern: str, default: str = "") -> str:
        m = re.search(pattern, clean, re.IGNORECASE)
        return m.group(1).strip() if m else default

    inv_id = _find(r"FACTURE\s*N°?:\s*([A-Z0-9-]+)", "F-2026-PDF")
    supplier = _find(r"Emetteur:\s*([^\n]+)", "[ENTITE_1]")
    customer = _find(r"Destinataire:\s*([^\n]+)", "[ENTITE_2]")
    interco = _find(r"Intercompagnie:\s*(OUI|NON|true|false)", "NON").upper() in ("OUI", "TRUE")
    ht = float(_find(r"Montant\s*HT:\s*([\d.]+)", "0"))
    vat_pct = float(_find(r"TVA:\s*([\d.]+)%", "20")) / 100.0
    ttc = float(_find(r"Montant\s*TTC:\s*([\d.]+)", str(ht * (1 + vat_pct))))
    inv_date = _find(r"Date\s*Facture:\s*(\d{4}-\d{2}-\d{2})", "2026-12-28")
    srv_date = _find(r"Date\s*Prestation:\s*(\d{4}-\d{2}-\d{2})", inv_date)
    account = _find(r"Compte\s*Grand\s*Livre:\s*(\d+)", "622600")
    ledger_amt = float(_find(r"Montant\s*Ecriture:\s*([\d.]+)", str(ht)))
    period = _find(r"Periode:\s*(\d{4}-\d{2})", inv_date[:7])
    desc = _find(r"Description:\s*([^\n]+)", "Prestation de conseil")

    return [
        CanonicalInvoice(
            tenant_id=expected_tenant,
            invoice_id=inv_id,
            supplier=supplier,
            customer=customer,
            is_intercompany=interco,
            amount_ht=ht,
            vat_rate=vat_pct,
            amount_ttc=ttc,
            invoice_date=inv_date,
            service_date=srv_date,
            ledger_entry=LedgerEntry(account=account, amount=ledger_amt, period=period),
            description=desc,
            source_file=filename,
            security=SecurityMeta(model_armor="clean", pii_masked=dlp_res.entities_masked, tenant_verified=True),
        )
    ]


def ingest_file(expected_tenant: str, path: Path) -> list[CanonicalInvoice]:
    """Ingest a local CSV or PDF file through Gate 1 + Canonical Normalization."""
    data = path.read_bytes()
    if path.suffix.lower() == ".csv":
        return ingest_csv_to_canonical(expected_tenant, path.name, data)
    return ingest_pdf_to_canonical(expected_tenant, path.name, data)
