"""Downscoped GCP Service Account impersonation & live 403 cross-scope probe."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.config import settings


@dataclass
class IamProbeResult:
    """Result of testing whether an agent can access an out-of-scope GCP resource."""

    actor_sa: str
    target_resource: str
    allowed: bool
    status_code: int
    message: str
    real_gcp: bool


def get_impersonated_credentials(target_sa: str, scopes: list[str] | None = None) -> Any:
    """Return impersonated GCP credentials for a least-privilege Service Account."""
    if not settings.use_real_iam_impersonation:
        return None
    import google.auth
    from google.auth import impersonated_credentials

    source_creds, _ = google.auth.default()
    return impersonated_credentials.Credentials(
        source_credentials=source_creds,
        target_principal=target_sa,
        target_scopes=scopes or ["https://www.googleapis.com/auth/cloud-platform"],
        lifetime=300,
    )


def probe_cross_scope_access() -> IamProbeResult:
    """Intentionally test sa-legal attempting to query BigQuery financial ledger."""
    actor = settings.sa_legal_email
    target = f"bigquery://{settings.gcp_project_id}.{settings.bq_dataset}.{settings.bq_ledger_table}"

    if settings.use_real_iam_impersonation and settings.use_real_gcp_data:
        try:
            from google.cloud import bigquery

            creds = get_impersonated_credentials(actor)
            client = bigquery.Client(project=settings.gcp_project_id, credentials=creds)
            job = client.query(
                f"SELECT COUNT(*) FROM `{settings.gcp_project_id}.{settings.bq_dataset}.{settings.bq_ledger_table}`"
            )
            job.result()
            return IamProbeResult(
                actor_sa=actor,
                target_resource=target,
                allowed=True,
                status_code=200,
                message="WARNING: sa-legal unexpectedly had BigQuery access!",
                real_gcp=True,
            )
        except Exception as exc:
            return IamProbeResult(
                actor_sa=actor,
                target_resource=target,
                allowed=False,
                status_code=403,
                message=f"403 PERMISSION_DENIED: {exc}",
                real_gcp=True,
            )

    return IamProbeResult(
        actor_sa=actor,
        target_resource=target,
        allowed=False,
        status_code=403,
        message=(
            f"403 PERMISSION_DENIED: Service account '{actor}' does not have "
            "bigquery.jobs.create / bigquery.tables.getData permission on "
            f"'{settings.bq_dataset}.{settings.bq_ledger_table}'."
        ),
        real_gcp=False,
    )
