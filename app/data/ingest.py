"""Ingestion pipeline: PDF/CSV parsing -> Model Armor -> Cloud DLP -> VectorStore/BigQuery."""

from __future__ import annotations

import csv
import io
from pathlib import Path
from typing import Any

from pypdf import PdfReader

from app.config import settings
from app.data.audit_logger import audit_logger
from app.data.vector_store import vector_store
from app.security.dlp_tokenizer import dlp_tokenizer
from app.security.model_armor import scan_chunk


def ingest_pdf_bytes(deal_id: str, filename: str, data: bytes) -> dict[str, Any]:
    """Extract PDF pages, screen with Model Armor, mask with Cloud DLP, and index."""
    if settings.use_real_gcp_data and settings.gcs_quarantine_bucket:
        try:
            from google.cloud import storage

            client = storage.Client(project=settings.gcp_project_id)
            bucket = client.bucket(settings.gcs_quarantine_bucket)
            bucket.blob(f"{deal_id}/{filename}").upload_from_string(data, content_type="application/pdf")
        except Exception:
            pass

    reader = PdfReader(io.BytesIO(data))
    indexed_chunks = 0
    blocked_chunks = 0
    masked_entities = 0
    tampering_alerts: list[dict[str, Any]] = []

    for page_idx, page in enumerate(reader.pages, start=1):
        raw_text = page.extract_text() or ""
        # Split by lines/paragraphs so Model Armor quarantines ONLY the poisoned segment
        lines = [ln.strip() for ln in raw_text.splitlines() if ln.strip()]
        clean_lines: list[str] = []

        for line in lines:
            armor = scan_chunk(line)
            if not armor.is_safe:
                blocked_chunks += 1
                alert = {
                    "doc_name": filename,
                    "page_num": page_idx,
                    "matched_rule": armor.matched_rule,
                    "provider": armor.provider,
                    "snippet_preview": line[:120],
                }
                tampering_alerts.append(alert)
                audit_logger.log(
                    deal_id=deal_id,
                    agent_name="ingestor",
                    event_type="MODEL_ARMOR_BLOCK",
                    severity="CRITICAL",
                    details=alert,
                )
            else:
                clean_lines.append(line)

        if clean_lines:
            page_clean_text = "\n".join(clean_lines)
            dlp_res = dlp_tokenizer.deidentify(page_clean_text)
            masked_entities += dlp_res.entities_masked
            if dlp_res.entities_masked > 0:
                audit_logger.log(
                    deal_id=deal_id,
                    agent_name="ingestor",
                    event_type="DLP_MASKED",
                    severity="INFO",
                    details={
                        "doc_name": filename,
                        "page_num": page_idx,
                        "entities_masked": dlp_res.entities_masked,
                        "tokens": dlp_res.tokens_used,
                        "provider": dlp_res.provider,
                    },
                )
            vector_store.add_chunk(
                deal_id=deal_id,
                doc_name=filename,
                page_num=page_idx,
                chunk_idx=1,
                text=dlp_res.sanitized_text,
            )
            indexed_chunks += 1

    return {
        "filename": filename,
        "type": "pdf",
        "pages": len(reader.pages),
        "indexed_chunks": indexed_chunks,
        "blocked_chunks": blocked_chunks,
        "masked_entities": masked_entities,
        "tampering_alerts": tampering_alerts,
    }


def ingest_csv_bytes(deal_id: str, filename: str, data: bytes) -> dict[str, Any]:
    """Load structured financial CSV into BigQuery (if enabled) and local ledger store."""
    text = data.decode("utf-8")
    reader = csv.DictReader(io.StringIO(text))
    rows: list[dict[str, Any]] = []
    for row in reader:
        # Deterministically tokenize IBANs in ledger rows too
        iban_raw = row.get("bank_token", "")
        if iban_raw and not iban_raw.startswith("[IBAN_"):
            iban_tok = dlp_tokenizer.deidentify(iban_raw).sanitized_text
        else:
            iban_tok = iban_raw
        rows.append(
            {
                "deal_id": deal_id,
                "invoice_id": row["invoice_id"],
                "counterparty": row["counterparty"],
                "direction": row["direction"],
                "amount_eur": float(row["amount_eur"]),
                "invoice_date": row["invoice_date"],
                "bank_token": iban_tok,
            }
        )

    vector_store.set_ledger(deal_id, rows)

    if settings.use_real_gcp_data:
        try:
            from google.cloud import bigquery

            bq = bigquery.Client(project=settings.gcp_project_id)
            table_id = f"{settings.gcp_project_id}.{settings.bq_dataset}.{settings.bq_ledger_table}"
            job_cfg = bigquery.LoadJobConfig(
                write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
                autodetect=True,
            )
            bq.load_table_from_json(rows, table_id, job_config=job_cfg).result()
        except Exception:
            pass

    audit_logger.log(
        deal_id=deal_id,
        agent_name="ingestor",
        event_type="LEDGER_LOADED",
        severity="INFO",
        details={"filename": filename, "rows_loaded": len(rows)},
    )
    return {"filename": filename, "type": "csv", "rows_loaded": len(rows)}


def ingest_path(deal_id: str, path: Path) -> dict[str, Any]:
    """Ingest a local PDF or CSV file."""
    data = path.read_bytes()
    if path.suffix.lower() == ".csv":
        return ingest_csv_bytes(deal_id, path.name, data)
    return ingest_pdf_bytes(deal_id, path.name, data)
