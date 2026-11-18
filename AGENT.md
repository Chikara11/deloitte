# AGENT.md — AuditBridge (Contrôle des Prestations & Transactions Complexes)

> **Mission:** Plateforme multi-agents **Deloitte × Google Cloud** reliant les **3 métiers de Deloitte** (*Auditeur, Avocat Tax & Legal, Consultant*) pour automatiser et documenter le contrôle des prestations et flux inter-compagnies (Cut-off / TVA / Seuils) avec sécurité Zero-Trust sur GCP.

---

## 1. Architecture AuditBridge (3 Gates + 3 Agents)

1. **Gate 1 — Pare-feu Cyber (sans IA) :**
   - Vérification `tenant_id` (isolation stricte multi-clients)
   - **Model Armor** (détection prompt injection / URL malveillante $\rightarrow$ Quarantaine)
   - **Pseudonymisation (Cloud DLP / Python)** (`[PERSONNE_1]`, `[IBAN_1]`, `[ENTITE_1]`)
2. **Normalisation via Passeport Client (`CLIENT_A`, `CLIENT_B`) $\rightarrow$ JSON Canonique**
3. **Agents IA (ADK + Gemini + Règles Python) :**
   - **Agent Auditeur** : applique les **5 règles Python déterministes** (`CUT_OFF`, `CONCORDANCE`, `TVA`, `INTERCOMPAGNIE`, `SEUIL`).
   - **Agent Passerelle** : rédige 2 **Micro-Briefs** fermés pour l'Avocat (*Tax & Legal*) et le Consultant.
   - **Agent Synthèse** : calcule le **Score de Confiance** (`100 - 20*échecs - 30*AvocatNonConforme - 30*ConsultantNonLivré`) et formule la recommandation.
4. **Gate 2 (Validation Experts : Avocat & Consultant)** $\rightarrow$ **Gate 3 (Décision Auditeur)** $\rightarrow$ **Fiche de Contrôle Documentée (Markdown exportable)**.

---

## 2. Structure du Repo

```text
deloitte-gcp-war-room/
├── AGENT.md
├── problematique.md                # Problématique, solution & pitch 5 slides (FR)
├── docs/
│   ├── ARCHITECTURE.md             # Architecture AuditBridge, JSON canonique, GCP stack
│   └── USE_CASES.md                # 2 Passeports Clients + 3 cas de démo
├── scripts/
│   ├── setup_gcp.sh                # Bootstrap GCP (APIs, GCS, BigQuery, IAM)
│   └── generate_data.py            # Génère passeports CLIENT_A/B + 3 factures démo
├── app/
│   ├── main.py                     # FastAPI + SSE + endpoints AuditBridge
│   ├── config.py
│   ├── security/
│   │   ├── model_armor.py          # Gate 1: Prompt injection & quarantaine
│   │   ├── dlp_tokenizer.py        # Gate 1: Pseudonymisation [PERSONNE_1], [ENTITE_1], [IBAN_1]
│   │   └── iam_impersonator.py     # Probe IAM 403
│   ├── data/
│   │   ├── audit_logger.py         # SSE + BigQuery audit_logs
│   │   ├── passports.py            # Passeports Clients (CLIENT_A / CLIENT_B)
│   │   └── ingest.py               # Gate 1 + Normalisation -> JSON Canonique
│   ├── agents/
│   │   ├── models.py               # CanonicalInvoice, RuleResult, MicroBrief, AuditCase, FicheControle
│   │   ├── auditeur_agent.py       # 5 règles Python déterministes + explication Gemini
│   │   ├── passerelle_agent.py     # Micro-Briefs Avocat & Consultant
│   │   ├── synthese_agent.py       # Score de confiance + recommandation
│   │   ├── fiche_controle.py       # Générateur Fiche de Contrôle Markdown
│   │   └── orchestrator.py
│   └── static/
│       └── index.html              # Interface AuditBridge (Sélecteur Client, Onglets Rôles, HUD, Fiche)
└── tests/
    └── test_guardrails.py
```

---

## 3. Commandes

```bash
uv run pytest -v
uv run uvicorn app.main:app --reload --port 8080
```
