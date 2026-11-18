"""Passeports Clients: per-tenant normalization rules, thresholds, and group entities."""

from __future__ import annotations

from pydantic import BaseModel, Field


class ClientRegles(BaseModel):
    seuil_validation: float
    taux_tva: float
    date_cloture: str  # YYYY-MM-DD


class ClientPassport(BaseModel):
    tenant_id: str
    client_name: str
    norme: str  # PCG | IFRS
    format: str  # erp_csv | pdf_ledger
    mapping: dict[str, str] = Field(default_factory=dict)
    regles: ClientRegles
    entites_groupe: list[str] = Field(default_factory=list)


PASSPORTS: dict[str, ClientPassport] = {
    "CLIENT_A": ClientPassport(
        tenant_id="CLIENT_A",
        client_name="Client A — Retail France (PCG)",
        norme="PCG",
        format="erp_csv",
        mapping={
            "Num_Fact": "invoice_id",
            "Montant_HT": "amount_ht",
            "Taux_TVA": "vat_rate",
            "Date_Fact": "invoice_date",
            "Date_Prest": "service_date",
        },
        regles=ClientRegles(seuil_validation=50_000.0, taux_tva=0.20, date_cloture="2026-12-31"),
        entites_groupe=["CLIENT_A_FRANCE"],
    ),
    "CLIENT_B": ClientPassport(
        tenant_id="CLIENT_B",
        client_name="Client B — Groupe International (IFRS)",
        norme="IFRS",
        format="pdf_ledger",
        mapping={
            "invoice_no": "invoice_id",
            "net_amount": "amount_ht",
            "vat": "vat_rate",
            "doc_date": "invoice_date",
            "delivery_date": "service_date",
        },
        regles=ClientRegles(seuil_validation=100_000.0, taux_tva=0.20, date_cloture="2026-12-31"),
        entites_groupe=["CLIENT_B_FRANCE", "CLIENT_B_LUXEMBOURG"],
    ),
}


def get_passport(tenant_id: str) -> ClientPassport:
    """Return the ClientPassport for a tenant_id."""
    if tenant_id not in PASSPORTS:
        raise ValueError(f"Unknown tenant_id '{tenant_id}'. Expected one of {list(PASSPORTS)}.")
    return PASSPORTS[tenant_id]
