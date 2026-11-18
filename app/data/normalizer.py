"""Passport-driven normalization of /data/inputs into CanonicalInvoice + exact locators."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

from app.agents.models import CanonicalInvoice, LedgerEntry
from app.data.audit_logger import audit_logger
from app.security.gate1 import check_model_armor, server_vault

DATA_ROOT = Path(__file__).resolve().parent.parent.parent / "data"


class Gate1BlockError(Exception):
    def __init__(self, action: str, reason: str, file_rel: str, locator: dict[str, Any]) -> None:
        super().__init__(reason)
        self.action = action
        self.reason = reason
        self.file_rel = file_rel
        self.locator = locator


def load_passport(tenant_id: str) -> dict[str, Any]:
    p = DATA_ROOT / "passports" / f"{tenant_id}.json"
    if not p.exists():
        raise FileNotFoundError(f"Passport not found for {tenant_id}")
    return json.loads(p.read_text(encoding="utf-8"))


def _load_ledger_map(tenant_id: str) -> tuple[dict[str, tuple[LedgerEntry, int]], str]:
    rel = f"data/inputs/{tenant_id}/ledger.csv"
    path = DATA_ROOT / "inputs" / tenant_id / "ledger.csv"
    if not path.exists():
        return {}, rel
    df = pd.read_csv(path)
    out: dict[str, tuple[LedgerEntry, int]] = {}
    for idx, row in df.iterrows():
        out[str(row["invoice_id"])] = (
            LedgerEntry(
                account=str(row["account"]),
                amount=float(row["amount"]),
                period=str(row["period"]),
            ),
            int(idx) + 2,  # 1-based CSV row including header
        )
    return out, rel


def normalize_csv_file(
    expected_tenant: str, session_id: str, file_path: Path
) -> list[tuple[CanonicalInvoice, dict[str, Any]]]:
    """Run Gate 1 + Passport mapping on a CSV export. Returns (CanonicalInvoice, metadata_locators)."""
    passport = load_passport(expected_tenant)
    mapping = passport["column_mapping"]
    inv_map = {v: k for k, v in mapping.items()}
    rel_file = str(file_path.relative_to(DATA_ROOT.parent))
    ledger_map, ledger_rel = _load_ledger_map(expected_tenant)

    df = pd.read_csv(file_path)
    results: list[tuple[CanonicalInvoice, dict[str, Any]]] = []

    for idx, row in df.iterrows():
        csv_row = int(idx) + 2
        doc_tenant = str(row.get("tenant_id", expected_tenant)).strip()
        if doc_tenant != expected_tenant:
            audit_logger.log(
                session_id,
                expected_tenant,
                "Gate1",
                "TENANT_ISOLATION_BLOCK",
                "BLOCK",
                {"file": rel_file, "found_tenant": doc_tenant, "row": csv_row},
            )
            raise Gate1BlockError("TENANT_ISOLATION_BLOCK", f"Tenant mismatch: {doc_tenant} != {expected_tenant}", rel_file, {"row": csv_row, "column": "tenant_id"})

        raw_desc = str(row[inv_map["description"]])
        armor = check_model_armor(raw_desc)
        if not armor.is_safe:
            audit_logger.log(session_id, expected_tenant, "Gate1", "MODEL_ARMOR_BLOCK", "BLOCK", {"file": rel_file, "rule": armor.matched_rule})
            raise Gate1BlockError("MODEL_ARMOR_BLOCK", f"Prompt injection detected: {armor.matched_rule}", rel_file, {"row": csv_row, "column": inv_map["description"]})

        sup_mask, c1 = server_vault.pseudonymize(str(row[inv_map["supplier"]]))
        cust_mask, c2 = server_vault.pseudonymize(str(row[inv_map["customer"]]))
        if c1 + c2 > 0:
            audit_logger.log(session_id, expected_tenant, "Gate1", "DLP_MASKED", "PASS", {"file": rel_file, "count": c1 + c2})

        inv_id = str(row[inv_map["invoice_id"]])
        ht = float(row[inv_map["amount_ht"]])
        vat = float(row[inv_map["vat_rate"]])
        ledger_entry, ledger_row = ledger_map.get(
            inv_id, (LedgerEntry(account="622600", amount=ht, period=str(row[inv_map["invoice_date"]])[:7]), csv_row)
        )

        canon = CanonicalInvoice(
            tenant_id=expected_tenant,
            invoice_id=inv_id,
            supplier=sup_mask,
            customer=cust_mask,
            is_intercompany=str(row[inv_map["is_intercompany"]]).lower() == "true",
            amount_ht=ht,
            vat_rate=vat,
            amount_ttc=ht * (1.0 + vat),
            invoice_date=str(row[inv_map["invoice_date"]]),
            service_date=str(row[inv_map["service_date"]]),
            ledger_entry=ledger_entry,
            description=raw_desc,
            source_file=rel_file,
        )
        locators = {
            "kind": "csv",
            "row": csv_row,
            "inv_map": inv_map,
            "ledger_file": ledger_rel,
            "ledger_row": ledger_row,
        }
        results.append((canon, locators))
    return results


def normalize_txt_file(
    expected_tenant: str, session_id: str, file_path: Path
) -> tuple[CanonicalInvoice, dict[str, Any]]:
    """Run Gate 1 + Passport mapping on a TXT invoice document with exact line locators."""
    passport = load_passport(expected_tenant)
    mapping = passport["column_mapping"]
    inv_map = {v: k for k, v in mapping.items()}
    rel_file = str(file_path.relative_to(DATA_ROOT.parent))
    ledger_map, ledger_rel = _load_ledger_map(expected_tenant)

    lines = file_path.read_text(encoding="utf-8").splitlines()
    kv: dict[str, tuple[str, int]] = {}

    for line_no, raw_line in enumerate(lines, start=1):
        armor = check_model_armor(raw_line)
        if not armor.is_safe:
            audit_logger.log(
                session_id,
                expected_tenant,
                "Gate1",
                "MODEL_ARMOR_BLOCK",
                "BLOCK",
                {"file": rel_file, "line": line_no, "rule": armor.matched_rule, "provider": armor.provider},
            )
            raise Gate1BlockError(
                "MODEL_ARMOR_BLOCK",
                f"Model Armor blocked prompt injection at line {line_no}: {armor.matched_rule}",
                rel_file,
                {"line_start": line_no, "line_end": line_no},
            )
        if ":" in raw_line:
            k, v = raw_line.split(":", 1)
            kv[k.strip()] = (v.strip(), line_no)

    doc_tenant = kv.get("TENANT_ID", (expected_tenant, 1))[0]
    if doc_tenant != expected_tenant:
        t_line = kv.get("TENANT_ID", (expected_tenant, 1))[1]
        audit_logger.log(session_id, expected_tenant, "Gate1", "TENANT_ISOLATION_BLOCK", "BLOCK", {"file": rel_file, "found_tenant": doc_tenant})
        raise Gate1BlockError("TENANT_ISOLATION_BLOCK", f"Tenant mismatch: {doc_tenant} != {expected_tenant}", rel_file, {"line_start": t_line, "line_end": t_line})

    # Pseudonymize supplier & customer
    raw_sup, sup_ln = kv.get(inv_map["supplier"], ("Unknown", 1))
    sup_mask, c1 = server_vault.pseudonymize(raw_sup)
    raw_cust, cust_ln = kv.get(inv_map["customer"], ("Unknown", 1))
    cust_mask, c2 = server_vault.pseudonymize(raw_cust)
    if c1 + c2 > 0:
        audit_logger.log(session_id, expected_tenant, "Gate1", "DLP_MASKED", "PASS", {"file": rel_file, "count": c1 + c2})

    inv_id = kv.get(inv_map["invoice_id"], ("UNKNOWN", 1))[0]
    ht = float(kv.get(inv_map["amount_ht"], ("0", 1))[0])
    vat = float(kv.get(inv_map["vat_rate"], ("0.2", 1))[0])
    inv_date = kv.get(inv_map["invoice_date"], ("2026-12-31", 1))[0]
    srv_date = kv.get(inv_map["service_date"], (inv_date, 1))[0]
    ledger_entry, ledger_row = ledger_map.get(inv_id, (LedgerEntry(account="622600", amount=ht, period=inv_date[:7]), 2))

    canon = CanonicalInvoice(
        tenant_id=expected_tenant,
        invoice_id=inv_id,
        supplier=sup_mask,
        customer=cust_mask,
        is_intercompany=kv.get(inv_map["is_intercompany"], ("false", 1))[0].lower() == "true",
        amount_ht=ht,
        vat_rate=vat,
        amount_ttc=ht * (1.0 + vat),
        invoice_date=inv_date,
        service_date=srv_date,
        ledger_entry=ledger_entry,
        description=kv.get(inv_map["description"], ("", 1))[0],
        source_file=rel_file,
    )
    locators = {
        "kind": "txt",
        "kv": kv,
        "inv_map": inv_map,
        "lines": lines,
        "ledger_file": ledger_rel,
        "ledger_row": ledger_row,
    }
    return canon, locators
