"""Application configuration loaded from environment / .env."""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Typed GCP and guardrail configuration."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    gcp_project_id: str = "demo-local-project"
    gcp_region: str = "europe-west1"

    gcs_quarantine_bucket: str = ""
    bq_dataset: str = "war_room"
    bq_ledger_table: str = "ledger_2025"
    bq_audit_table: str = "audit_logs"
    firestore_collection: str = "deal_chunks"
    pubsub_topic: str = ""  # e.g. auditbridge-case-evaluated (empty = Workflows orchestration disabled)

    gemini_fast_model: str = "gemini-2.5-flash"
    gemini_pro_model: str = "gemini-2.5-pro"
    embedding_model: str = "text-embedding-005"

    use_real_dlp: bool = False
    use_real_model_armor: bool = False
    use_real_iam_impersonation: bool = False
    use_real_gcp_data: bool = False
    dlp_hmac_secret: str = "hackathon-demo-secret-rotate-in-kms"

    sa_legal_email: str = "sa-legal@demo-local-project.iam.gserviceaccount.com"
    sa_quant_email: str = "sa-quant@demo-local-project.iam.gserviceaccount.com"
    sa_forensic_email: str = "sa-forensic@demo-local-project.iam.gserviceaccount.com"


settings = Settings()
