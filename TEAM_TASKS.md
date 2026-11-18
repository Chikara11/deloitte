# Team Task Split & Gemini Prompts — AuditBridge

> **Repo:** `https://github.com/Chikara11/deloitte.git`  
> **Live Cloud Run App:** `https://war-room-445615405690.europe-west1.run.app`

---

## Branch Workflow
- `main` — Production / Live Cloud Run baseline (do not push untested changes directly).
- **`track-1-pitch`** — Colleague 1 (Pitch Deck, Storytelling, Speaker Notes & Backup Pack).
- **`track-2-demo-qa`** — Colleague 2 (Custom File Upload UI, Live Demo QA & GCP Proof).
- **At 15:45:** Merge both branches into `main` and redeploy Cloud Run.

---

## Track 1 — Colleague 1 (`branch: track-1-pitch`)

### Deliverables
1. **5-Slide Pitch Deck + Speaker Notes (`docs/SLIDES.md`)** based on `problematique.md`.
2. **Backup Screenshots Folder (`docs/backups/`)**:
   - Screenshot 1: `✅ Cas 1 : Normal (A)` (Score `100/100 GREEN`)
   - Screenshot 2: `⚠️ Cas 2 : Interco 2M€ (B)` (Micro-Briefs + Score `0/100 RED`)
   - Screenshot 3: `🛡️ Cas 3 : PDF Piégé` (HUD rouge `MODEL_ARMOR_BLOCK`)
   - Screenshot 4: Exported **Fiche de Contrôle Documentée** + BigQuery `war_room.audit_logs`

### Git Commands
```bash
git clone https://github.com/Chikara11/deloitte.git
cd deloitte
git checkout track-1-pitch
```

### Prompt to Paste into Gemini (Track 1)
> Read `problematique.md`, `docs/ARCHITECTURE.md`, and `docs/USE_CASES.md`.  
> We are on branch `track-1-pitch` for a 5-minute Deloitte × Google Cloud hackathon pitch.  
> Create `docs/SLIDES.md` with:  
> 1. Exact text, bullet points, and visual layout for 5 slides (Problem: 2M€ invoice = 5 days of emails -> 10 min; Solution: AuditBridge 3 Gates + Client Passports; Live Demo 3 cases; GCP Security & Governance; Business ROI & Scale with Pub/Sub + Cloud Workflows).  
> 2. A timed 5-minute speaker script (in French, non-technical, focused on Deloitte Audit & Assurance value).  
> 3. Top 5 anticipated Q&A answers for Deloitte & Google AI engineers.  
> Commit and push to `track-1-pitch`.

---

## Track 2 — Colleague 2 (`branch: track-2-demo-qa`)

### Deliverables
1. **Add a Custom PDF/CSV Upload Dropzone** in `app/static/index.html` wired to the existing `POST /api/tenants/{tenant_id}/upload` endpoint (showing a clear red Gate 1 block alert if `HTTP 403` is returned).
2. **Verify End-to-End Demo & BigQuery Persistence:**
   - Test `Cas 1`, `Cas 2` (Gate 2 Avocat + Consultant $\rightarrow$ Gate 3 Auditeur $\rightarrow$ `Exporter (.md)`), `Cas 3`, `Test Isolation`, and `IAM 403`.
   - Confirm rows appear in BigQuery (`deloitteinnov26par-598:war_room.audit_logs`).
   - Run `uv run pytest -v` and ensure all tests pass.

### Git Commands
```bash
git clone https://github.com/Chikara11/deloitte.git
cd deloitte
git checkout track-2-demo-qa
```

### Prompt to Paste into Gemini (Track 2)
> Read `AGENT.md`, `app/main.py`, and `app/static/index.html`.  
> We are on branch `track-2-demo-qa`.  
> 1. Add a clean file upload input (`<input type="file" accept=".pdf,.csv">`) in `app/static/index.html` that posts to `/api/tenants/${currentTenant}/upload`, handles `403` Gate 1 Quarantine errors cleanly in the UI + HUD, and adds valid uploaded cases to `cases`.  
> 2. Add a pytest in `tests/test_guardrails.py` testing `POST /api/tenants/CLIENT_B/upload` with both a valid PDF and a poisoned PDF (`403`).  
> 3. Run `uv run pytest -v` to verify all tests pass, then commit and push to `track-2-demo-qa`.

---

## Final Merge & Redeploy (15:45)

Once both branches are pushed, run (or ask Gemini to run):
```bash
git checkout main
git pull origin main
git merge track-1-pitch
git merge track-2-demo-qa
uv run pytest -v
git push origin main
```
