# 2-Hour Hackathon Implementation Plan

> **Team Split Recommendation:**
> - **Person 1 (Infra & Security):** GCP setup, `model_armor.py`, `dlp_tokenizer.py`, `iam_impersonator.py`
> - **Person 2 (Data & Agents):** `generate_data.py`, `ingest.py`, `legal_agent.py`, `quant_agent.py`, `forensic_agent.py`, `skeptic_agent.py`
> - **Person 3 (UI & Deploy):** `main.py` (FastAPI + SSE), `static/index.html` (War Room + Governance HUD), Cloud Run deploy

---

## Timeline (0:00 → 2:00)

### 0:00 – 0:20 | Bootstrap & Synthetic Data
- [ ] Run `bash scripts/setup_gcp.sh` (creates GCS bucket, BigQuery dataset, 3 Service Accounts).
- [ ] Copy `.env.example` $\rightarrow$ `.env` and fill `GCP_PROJECT_ID`.
- [ ] Run `scripts/generate_data.py` to produce the 5 PDFs + `04_Invoices_2025.csv`.
- [ ] Verify BigQuery upload of `04_Invoices_2025.csv` into `war_room.ledger_2025`.

### 0:20 – 0:55 | Security Shield & Hot Data Plane
- [ ] Implement `app/data/audit_logger.py` (in-memory SSE broadcaster + BigQuery `audit_logs` writer).
- [ ] Implement `app/security/model_armor.py` (Model Armor API call + heuristic fallback for offline/quota safety).
- [ ] Implement `app/security/dlp_tokenizer.py` (Cloud DLP deterministic tokenization + KMS/HMAC vault + Break-Glass unmask).
- [ ] Implement `app/data/ingest.py` + `vector_store.py` (PDF chunking $\rightarrow$ Model Armor $\rightarrow$ DLP $\rightarrow$ `text-embedding-005` $\rightarrow$ Firestore/local vector store).

### 0:55 – 1:30 | IAM-Scoped Agent Swarm & Skeptic Gate
- [ ] Implement `app/security/iam_impersonator.py` + `403` cross-scope probe.
- [ ] Implement `legal_agent.py`, `quant_agent.py` (BigQuery dry-run + SQL), and `forensic_agent.py` (token graph).
- [ ] Implement `skeptic_agent.py` (Python citation/SQL verification + Gemini Critic `max_retries=2`).
- [ ] Implement `price_chip.py` (deterministic € valuation impact) + `orchestrator.py`.
- [ ] Run `uv run pytest -q` to verify guardrails.

### 1:30 – 1:50 | War Room UI + Cloud Run Deploy
- [ ] Wire `app/main.py` REST endpoints (`/ingest`, `/analyze`, `/iam-probe`, `/break-glass`, `/events` SSE).
- [ ] Build `app/static/index.html` (Left: Findings, Entity Graph, Price Chip, Break-Glass button; Right: Live Governance & Security HUD).
- [ ] Deploy to Cloud Run: `gcloud run deploy war-room --source . --region europe-west1 --allow-unauthenticated`.

### 1:50 – 2:00 | Stage Rehearsal
- [ ] Test Scenario A (Clean 4 files), Scenario B (Live drop `05_Poisoned_Vendor_Addendum.pdf`), Scenario C (IAM 403 probe + Break-Glass Unmask).
- [ ] Confirm BigQuery `audit_logs` has live rows to show judges if asked.
