# AuditBridge — Governed Multi-Agent Audit Platform (Deloitte × Google Cloud)

**AuditBridge** is a stateless, 5-gate Human-in-the-Loop (HITL) multi-agent platform on Google Cloud Run for documenting internal controls on high-value service invoices and intercompany transactions (cut-off, VAT, concordance, thresholds).

---

## 5-Gate Human-in-the-Loop Workflow

Every case follows a strict state machine where the ADK Harness **pauses after every agent** until a human decision (`Approve` / `Edit` / `Reject` with mandatory comment) is recorded:

1. **Gate 1 — Automatic Security + Analyste sécurité Quarantine Queue**
   - `tenant_id` isolation, **Model Armor** (`google-cloud-modelarmor` + regex fallback) prompt-injection screening, and deterministic server-side pseudonymization (`ServerVault` / Cloud DLP).
   - Flagged files enter `QUARANTINED`; `Analyste sécurité` can **Release** or **Confirm block** (`REJECTED`).
2. **Gate 2 — Auditeur Review (after `AuditorAgent`)**
   - `AuditorAgent` runs deterministic Python rules + Gemini explanation + mandatory **Skeptic Check** (`>=1 input` + `>=1 regulation/passport` evidence).
   - Pauses at `AUDITOR_AGENT_DONE`. `Auditeur` can edit scope files, add/edit evidence, override rules with justification, **Reject** (re-runs `AuditorAgent` with feedback), or **Bulk Approve** green cases.
3. **Gate 3 — Auditeur Brief Review (after `BridgeAgent`)**
   - `BridgeAgent` drafts micro-briefs (`BRIEFS_DRAFTED`). `Auditeur` reviews/edits them in text areas; an automatic DLP re-check ensures no unmasked PII leaks before `GATE3_APPROVED`.
4. **Gate 4 — Experts (`Avocat` & `Consultant`)**
   - Briefs become visible to experts only after `GATE3_APPROVED`. Once both answer, `SynthesisAgent` computes the confidence score and pauses at `SYNTHESIS_DONE`.
5. **Gate 5 — Final Validation (`Auditeur` / `Manager` required if score < 40)**
   - `Approve` / `Edit` conclusion / `Reject` (re-runs `SynthesisAgent`). Only upon `GATE5_APPROVED` is the Control Documentation Sheet (`DOCUMENTED`) generated and unlocked for `.md` / `.docx` export.

---

## Traceable, Tamper-Evident Audit Log

- Every human, agent, or system action appends an immutable `AuditEvent` (`event_id`, `timestamp_utc`, `session_id`, `tenant_id`, `case_id`, `gate`, `actor_type`, `actor_id`, `actor_role`, `action`, `decision`, `comment`, `before`, `after`, `model_name`, `prompt_hash`, `evidence_refs`, `prev_hash`, `hash`).
- **SHA-256 Hash Chain** per `case_id`: `GET /api/cases/{id}/verify-chain` recomputes the entire chain and surfaces `"Journal intègre ✓"` in the UI and Control Documentation Sheet.
- **Real-time SSE** (`/api/events/stream`) + filterable `Journal` tab with `before`/`after` JSON diff and CSV export (`/api/events/export/csv`).

---

## Target Production Architecture on Google Cloud

```
Cloud Run (Stateless FastAPI + ADK Harness)
 ├── State & Append-Only Events ──▶ Cloud Firestore (audit_cases, audit_events)
 ├── Cross-Instance Live SSE     ──▶ Cloud Pub/Sub (topic: audit-events)
 ├── Structured JSON Logs        ──▶ Cloud Logging ──▶ Log Sink ──▶ BigQuery (WORM Analytics)
 ├── Guardrails & PII            ──▶ Vertex AI Model Armor + Cloud DLP + Secret Manager
 └── Tamper-Evidence & Auth      ──▶ Cloud KMS (signing head hashes) + Identity-Aware Proxy (IAP)
```

- **Stateless Cloud Run**: Zero local session dependency; all case states (`audit_cases`) and append-only events (`audit_events`) persist in **Firestore** (with automatic in-memory fallback for local/sandbox runs).
- **Pub/Sub for Real-Time Fan-Out**: Publishing each `AuditEvent` to a **Cloud Pub/Sub** topic ensures every Cloud Run instance pushes live SSE updates to connected auditors regardless of which instance handled the POST request.
- **Cloud Logging Sink → BigQuery**: Every event is emitted as structured JSON to `stdout` (ingested by **Cloud Logging**) and routed via an immutable **Log Sink** into a partitioned **BigQuery** audit table for long-term compliance analytics.

---

## Local Run & Tests

```bash
uv sync --extra dev
uv run pytest -v
uv run uvicorn app.main:app --reload
```
