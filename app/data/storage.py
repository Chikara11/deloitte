"""Google Cloud Storage document store (protected buckets) with local /data fallback for offline tests."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.config import settings

DATA_ROOT = Path(__file__).resolve().parent.parent.parent / "data"


class DocumentStore:
    def __init__(self) -> None:
        self._client: Any = None

    def _get_client(self) -> Any:
        if not settings.use_real_gcp_data:
            return None
        if self._client is None:
            try:
                from google.cloud import storage

                self._client = storage.Client(project=settings.gcp_project_id)
            except Exception:
                self._client = False
        return self._client if self._client is not False else None

    def _normalize_blob_name(self, rel_path: str) -> str:
        clean = rel_path.lstrip("/")
        if clean.startswith("data/"):
            clean = clean[5:]
        return clean

    def save_document(self, rel_path: str, content: bytes) -> str:
        """Save document to protected GCS bucket (gs://...) and return URI."""
        blob_name = self._normalize_blob_name(rel_path)
        client = self._get_client()
        if client:
            try:
                bucket = client.bucket(settings.gcs_bucket)
                blob = bucket.blob(blob_name)
                blob.upload_from_string(content)
                return f"gs://{settings.gcs_bucket}/{blob_name}"
            except Exception:
                pass
        # Local fallback (tests / offline)
        target = DATA_ROOT / blob_name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        return str(target)

    def quarantine_document(self, rel_path: str, content: bytes) -> str:
        """Store blocked/quarantined document in the isolated GCS quarantine bucket."""
        blob_name = self._normalize_blob_name(rel_path)
        client = self._get_client()
        if client:
            try:
                bucket = client.bucket(settings.gcs_quarantine_bucket)
                blob = bucket.blob(blob_name)
                blob.upload_from_string(content)
                return f"gs://{settings.gcs_quarantine_bucket}/{blob_name}"
            except Exception:
                pass
        return f"quarantine://{blob_name}"

    def read_document(self, rel_path: str) -> str:
        """Read document from GCS first (if enabled), falling back to local /data."""
        blob_name = self._normalize_blob_name(rel_path)
        client = self._get_client()
        if client:
            try:
                bucket = client.bucket(settings.gcs_bucket)
                blob = bucket.blob(blob_name)
                if blob.exists():
                    return blob.download_as_text(encoding="utf-8")
            except Exception:
                pass
        local_target = (DATA_ROOT / blob_name).resolve()
        if not str(local_target).startswith(str(DATA_ROOT.resolve())) or not local_target.exists():
            raise FileNotFoundError(rel_path)
        return local_target.read_text(encoding="utf-8")


doc_store = DocumentStore()
