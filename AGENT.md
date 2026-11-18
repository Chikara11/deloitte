# AGENT.md — Zero-Trust M&A Forensic War Room (2-Hour Hackathon Blueprint)

> **Purpose:** This file gives AI coding agents everything needed to build, deploy, secure, govern, and demo the **Zero-Trust M&A Forensic War Room** on **Google Cloud Platform (GCP)** within a **2-hour hackathon** for **Deloitte × Google Cloud**.

---

## 1. Mission & Non-Negotiable Constraints

Build a **multi-agent M&A Due Diligence & Forensic Investigation War Room** where Deloitte analysts upload a target company's Data Room (PDF contracts + CSV financial ledgers) and a swarm of **IAM-scoped AI agents** uncovers legal, financial, and fraud risks—while **GCP Guardrails** block indirect prompt injections, mask PII deterministically, verify every claim against ground truth, and require **Human-in-the-Loop (HITL) Break-Glass sign-off** before unmasking sensitive data.

### 2-Hour Hackathon Rules (CRITICAL)
1. **Optimize for a working live demo in 120 minutes.** Do NOT spend time on Terraform, VPC-SC, or Vertex AI Search (which takes 15–25 min to index).
2. **Use fast, real GCP primitives:**
   - **LLM & Embeddings:** Vertex AI (`gemini-2.5-flash` / `gemini-2.5-pro` + `text-embedding-005`) via `google-genai` or `google-adk`.
   - **Hot Vector Store:** Firestore Native Vector Search (or in-memory numpy cosine store backed by GCS/JSON if Firestore index isn't ready—keep behind a clean `VectorStore` interface).
   - **Structured Ledger & Audit Sink:** BigQuery (`war_room.ledger_2025` and `war_room.audit_logs`).
   - **Security Guardrails:**
     - **Model Armor** (`modelarmor.googleapis.com`) for chunk-level indirect prompt injection screening (with a deterministic regex/heuristic fallback adapter if the hackathon project hasn't enabled the Model Armor API).
     - **Cloud DLP** (`dlp.googleapis.com`) for PII/IBAN tokenization using deterministic HMAC/surrogate tokens (`[IBAN_4c12]`, `[PER_9a3f]`) so cross-document fraud matching still works without exposing raw PII.
   - **IAM Least-Privilege:** 3 distinct GCP Service Accounts (`sa-legal`, `sa-quant`, `sa-forensic`) + a live **Cross-Scope Probe** endpoint/button that proves GCP returns `403 PERMISSION_DENIED` when an agent tries to access another agent's data.
   - **Deployment:** Single **Cloud Run** service (FastAPI backend serving REST + SSE live events + static/bundled React or single-file Tailwind/JS War Room UI) for zero-CORS, one-command deployment.

---

## 2. Target Repository Structure

Create all application code inside `deloitte-gcp-war-room/`:

```text
deloitte-gcp-war-room/
├── AGENT.md                        # You are here
├── .env.example                    # GCP project, region, dataset, bucket, SA emails
├── pyproject.toml                  # Python 3.11+ dependencies (uv / pip)
├── Dockerfile                      # Single-container Cloud Run build
├── docs/
│   ├── ARCHITECTURE.md             # 5-zone GCP architecture, IAM matrix, schemas
│   ├── USE_CASES.md                # NovaLogistics scenario, 4 planted traps, Price Chip rules
│   └── IMPLEMENTATION_PLAN_2H.md   # Minute-by-minute 2-hour build & deploy plan
├── scripts/
│   ├── setup_gcp.sh                # Enables APIs, creates GCS, BQ, 3 SAs + IAM bindings
│   └── generate_data.py            # Generates the 5 synthetic PDFs + 1 CSV with planted traps
├── app/
│   ├── main.py                     # FastAPI app + SSE event stream + static UI serving
│   ├── config.py                   # Pydantic settings from .env
│   ├── security/
│   │   ├── model_armor.py          # Chunk-level prompt injection scanner + quarantine logger
│   │   ├── dlp_tokenizer.py        # Cloud DLP / HMAC deterministic tokenization + Break-Glass unmask
│   │   └── iam_impersonator.py     # Downscoped GCP credentials per agent + 403 probe
│   ├── data/
│   │   ├── ingest.py               # PDF chunker -> Model Armor -> DLP -> VectorStore & BQ loader
│   │   ├── vector_store.py         # Firestore Vector Search + fast local fallback
│   │   └── audit_logger.py         # Writes immutable governance events to BigQuery + SSE queue
│   ├── agents/
│   │   ├── orchestrator.py         # Google ADK / asyncio fan-out + Skeptic loop (max_retries=2)
│   │   ├── legal_agent.py          # sa-legal: RAG-only contract clause extractor
│   │   ├── quant_agent.py          # sa-quant: BigQuery dry-run + SQL anomaly detector
│   │   ├── forensic_agent.py       # sa-forensic: Cross-doc [IBAN_*] / [PER_*] entity graph
│   │   ├── skeptic_agent.py        # Deterministic quote/SQL verifier + Gemini Critic
│   │   └── price_chip.py           # Deterministic M&A valuation adjustment (€ Escrow / CP)
│   └── static/
│       └── index.html              # 2-column War Room UI + Governance HUD + Entity Graph
└── tests/
    └── test_guardrails.py          # Fast pytest suite for DLP, Model Armor, Skeptic, Price Chip
```

---

## 3. Core Engineering Contracts (Do Not Violate)

1. **Zero Raw PII in Prompts:** Every PDF chunk must pass through `model_armor.scan_chunk()` and `dlp_tokenizer.deidentify()` **before** embedding or LLM invocation.
2. **Quarantine, Don't Crash:** If `model_armor` flags a chunk, quarantine *only* that chunk into `audit_logs` as `MODEL_ARMOR_BLOCK` and emit a `SELLER_TAMPERING` forensic finding. Keep clean chunks in the pipeline.
3. **Zero LLM Arithmetic:** `quant_agent.py` must **never** compute totals in LLM text. It must run `bigquery.QueryJobConfig(dry_run=True, maximum_bytes_billed=10_000_000)` first, then execute SQL and return `{sql_query, bq_job_id, result_rows}`.
4. **Deterministic Verification Before LLM Critic:** `skeptic_agent.py` must verify `chunk_id` existence and `>= 0.90` quote match in Python before calling Gemini, and cap retries at `max_retries = 2`.
5. **Break-Glass Unmasking:** Tokens (`[PER_9a3f]`, `[IBAN_4c12]`) remain masked in the UI and API responses until `/api/deals/{deal_id}/break-glass` is called with `partner_id` and `reason`, which logs an immutable `BREAK_GLASS_UNMASK` row to BigQuery.

---

## 4. Build & Run Commands (Target)

```bash
# 1. Bootstrap GCP (once)
bash scripts/setup_gcp.sh

# 2. Generate synthetic M&A Data Room (5 PDFs + 1 CSV)
uv run python scripts/generate_data.py --out ./sample_data_room

# 3. Run locally
uv run uvicorn app.main:app --reload --port 8080

# 4. Run guardrail tests
uv run pytest -q

# 5. Deploy to Cloud Run
gcloud run deploy war-room --source . --region europe-west1 --allow-unauthenticated
```

---

## 5. Agent Coding Order

Work strictly in this order so a runnable vertical slice exists by minute 60:
1. `scripts/generate_data.py` + `app/config.py` + `app/data/audit_logger.py`
2. `app/security/model_armor.py` + `app/security/dlp_tokenizer.py` + `app/data/ingest.py`
3. `app/agents/legal_agent.py`, `quant_agent.py`, `forensic_agent.py`, `skeptic_agent.py`, `price_chip.py`, `orchestrator.py`
4. `app/main.py` + `app/static/index.html`
5. `tests/test_guardrails.py` + `Dockerfile` + Cloud Run deploy
