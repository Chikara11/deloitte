# Architecture Specification — Zero-Trust M&A Forensic War Room

## 1. High-Level 5-Zone GCP Architecture

```text
[War Room UI (SSE + Upload)]
       │
       ├──(PDFs)──▶ [ZONE 1: Security Shield]
       │               ├── GCS Quarantine Bucket (untrusted raw PDFs)
       │               ├── Model Armor (chunk-level prompt injection filter) ──▶ Quarantine Sink
       │               └── Cloud DLP + KMS (crypto-deterministic [IBAN_*]/[PER_*])
       │
       └──(CSVs)──▶ [ZONE 2: Hot Hybrid Data Plane]
                       ├── Firestore Vector Search (text-embedding-005, <300ms)
                       ├── BigQuery Ledger (war_room.ledger_2025)
                       └── KMS Token Vault (locked raw PII map)
                              │
                              ▼
                    [ZONE 3: IAM-Scoped ADK Swarm (Cloud Run)]
                       ├── Legal Agent    (sa-legal    -> Firestore ONLY)
                       ├── Quant Agent    (sa-quant    -> BigQuery ONLY, dry-run capped)
                       └── Forensic Agent (sa-forensic -> Cross-doc [IBAN_*] graph)
                              │
                              ▼
                    [ZONE 4: Verification & Telemetry]
                       ├── Deterministic Python Verifier (chunk_id + quote >=90% + BQ job_id)
                       ├── Gemini 2.5 Pro Skeptic Critic (max_retries = 2)
                       └── Cloud Trace (OpenTelemetry) + BigQuery Audit Sink
                              │
                              ▼
                    [ZONE 5: Deal Output & Break-Glass Governance]
                       ├── Deterministic M&A Price Chip Engine (€ Escrow / CP)
                       └── Partner HITL Gate -> KMS Unmask + Immutable Audit Log
```

---

## 2. IAM Least-Privilege Matrix

Each specialist agent impersonates a dedicated GCP Service Account via `google.auth.impersonated_credentials` (with graceful local-dev fallback if running without impersonation permissions):

| Service Account | Allowed GCP Roles | Explicitly Denied / Absent |
| :--- | :--- | :--- |
| `sa-ingestor` | `storage.objectAdmin` (quarantine), `dlp.user`, `datastore.user`, `bigquery.dataEditor` | Cannot decrypt KMS Break-Glass vault |
| `sa-legal` | `datastore.viewer`, `aiplatform.user` | **NO** BigQuery access, **NO** GCS raw bucket access |
| `sa-quant` | `bigquery.dataViewer`, `bigquery.jobUser`, `aiplatform.user` | **NO** Firestore/Vector access, **NO** GCS access |
| `sa-forensic` | `datastore.viewer`, `aiplatform.user` | **NO** BigQuery financial rows, **NO** KMS decrypt |

### Live Cross-Scope Probe
Expose `POST /api/security/iam-probe` so the demo can intentionally instruct `sa-legal` to run `SELECT COUNT(*) FROM war_room.ledger_2025`, capturing the real GCP `403 PERMISSION_DENIED` response and streaming it into the Governance HUD.

---

## 3. Data & Audit Schemas

### A. Sanitized Document Chunk (Firestore / VectorStore)
```json
{
  "chunk_id": "c_01_p3_02",
  "deal_id": "nova_logistics_2025",
  "doc_name": "01_Customer_Contract_MegaRetail.pdf",
  "page_num": 3,
  "text": "Section 14.2 Change of Control: Upon acquisition of >50% equity...",
  "sha256": "9f86d081...",
  "embedding": [0.012, -0.044, "..."]
}
```

### B. Financial Ledger (`war_room.ledger_2025` in BigQuery)
| Column | Type | Description |
| :--- | :--- | :--- |
| `deal_id` | `STRING` | Tenant isolation key (`nova_logistics_2025`) |
| `invoice_id` | `STRING` | e.g., `INV-2025-0042` |
| `counterparty` | `STRING` | Customer or vendor name |
| `direction` | `STRING` | `REVENUE` or `EXPENSE` |
| `amount_eur` | `FLOAT64` | Exact euro amount |
| `invoice_date` | `DATE` | Booking date |
| `bank_token` | `STRING` | Tokenized IBAN (`[IBAN_4c12]`) |

### C. Immutable Governance Audit Log (`war_room.audit_logs` in BigQuery)
| Column | Type | Description |
| :--- | :--- | :--- |
| `event_id` | `STRING` | UUID |
| `timestamp` | `TIMESTAMP` | UTC timestamp |
| `deal_id` | `STRING` | Tenant deal ID |
| `agent_name` | `STRING` | `ingestor`, `sa-legal`, `sa-quant`, `skeptic`, `partner_hitl` |
| `event_type` | `STRING` | `DLP_MASKED`, `MODEL_ARMOR_BLOCK`, `SQL_DRY_RUN`, `IAM_403_BLOCK`, `SKEPTIC_PASS`, `SKEPTIC_REJECT`, `BREAK_GLASS_UNMASK` |
| `severity` | `STRING` | `INFO`, `WARNING`, `CRITICAL` |
| `details_json` | `STRING` | Structured payload (token counts, SQL bytes, quote hash, partner ID) |
