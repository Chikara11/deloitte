"""Application configuration loaded from environment / .env."""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    gcp_project_id: str = "deloitteinnov26par-598"
    gcp_region: str = "europe-west1"

    bq_dataset: str = "war_room"
    bq_audit_table: str = "audit_logs"

    gemini_fast_model: str = "gemini-2.5-flash"
    gemini_pro_model: str = "gemini-2.5-pro"

    model_armor_template: str = "projects/deloitteinnov26par-598/locations/europe-west1/templates/war-room-shield"
    use_real_model_armor: bool = False
    use_real_dlp: bool = False
    use_real_gcp_data: bool = False
    dlp_hmac_secret: str = "auditbridge-server-vault-secret"


settings = Settings()
