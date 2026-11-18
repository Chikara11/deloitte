# AuditBridge — Technical Specification

## 1. Architecture & Pipeline
1. **Gate 1 (No LLM):** `tenant_id` isolation $\rightarrow$ Model Armor (`google-cloud-modelarmor` behind `USE_REAL_MODEL_ARMOR` flag + regex fallback) $\rightarrow$ deterministic pseudonymization (`[PER_XXXX]`, `[IBAN_XXXX]`, server-side mapping only).
2. **Normalization:** Client Passport (`data/passports/*.json`) maps CSV/TXT inputs into canonical JSON (`CanonicalInvoice`) while recording exact locators (`{row, column}`, `{line_start, line_end}`, `{json_path}`).
3. **ADK Harness (`app/agents/harness.py`):**
   - Fixed order: `AuditorAgent` $\rightarrow$ (`BridgeAgent` on anomaly) $\rightarrow$ **Pause Gate 2** $\rightarrow$ `SynthesisAgent` $\rightarrow$ **Pause Gate 3** $\rightarrow$ Control Documentation Sheet.
   - Enforces per-agent tool allow-list (`before_tool_callback`), Model Armor prompt/output checks (`before_model_callback` / `after_model_callback`), Pydantic validation with 1 retry, and **Skeptic Evidence Check** (every finding must have $\ge 1$ `input` evidence AND $\ge 1$ `regulation` or `passport` evidence).
   - Emits structured JSON logs (`session_id`, `tenant_id`, `agent`, `action`, `verdict`, `timestamp`) to Cloud Logging / BigQuery / SSE.
4. **Export:** Auto-generated Control Documentation Sheet exported as `.md` and `.docx` (`python-docx`).
5. **Startup Seed:** Pre-loads `CLIENT_A` (normal green invoice), `CLIENT_B` (`facture_0412.txt` 2M€ intercompany anomaly + `facture_poison.txt` quarantined).
