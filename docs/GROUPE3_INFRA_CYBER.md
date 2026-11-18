# Groupe 3 — Infra GCP, Cyber & Human Gates

> Branche `track-2-demo-qa`. À fusionner dans `main` par l'équipe, puis redéployer Cloud Run.

## 1. Ce qui est livré

| Brique | Où | Preuve en démo |
|---|---|---|
| **Gate 1 — Pare-feu cyber** | `app/data/ingest.py`, `app/security/*`, `app/main.py` | Cas 3 → `MODEL_ARMOR_BLOCK` ; bouton *Test Isolation* → `TENANT_ISOLATION_BLOCK` |
| Vérif. `tenant_id` sur chaque dossier | header `X-Tenant-Id` obligatoire sur `/api/cases/*` | un autre client → **403** + log |
| Masquage DLP | HMAC déterministe (`[PER_xxxx]`, `[IBAN_xxxx]`) ; Cloud DLP si `USE_REAL_DLP=true` | HUD : `DLP_MASKED` |
| Upload durci | `.pdf`/`.csv` seulement, signature `%PDF`, 5 Mo max | fichier déguisé → **415** |
| Anti-XSS | UI : tout texte issu d'un document est échappé | facture piégée `<img onerror>` → affichée comme texte |
| **Gates 2 & 3 — Human Gates** | `app/main.py`, `app/static/index.html` | Gate 3 refusée tant que l'Avocat **et** le Consultant n'ont pas répondu ; signature immuable |
| **Gouvernance — logs infalsifiables** | `app/data/audit_logger.py` | *🔗 Intégrité logs* ✅ / *Simuler falsification* ⛔ |
| Logs BigQuery | `war_room.audit_logs` + colonnes `prev_hash`, `hash` | `scripts/bq_governance.sql` |
| **Scalabilité — Pub/Sub + Cloud Workflows** | `app/infra/pubsub.py`, `infra/workflow_auditbridge.yaml`, `scripts/deploy_scale.sh` | console Workflows : 1 exécution par facture, en attente du callback |

## 2. Architecture cible (slide « Sécurité & Scalabilité »)

```text
 Facture PDF/CSV ──► Cloud Run (FastAPI)
                       │ Gate 1 : tenant_id · Model Armor · DLP     ──► quarantaine (403)
                       │ Agent Auditeur → Agent Passerelle
                       ▼
                   Pub/Sub « auditbridge-case-evaluated »   (ids + statut, jamais de PII)
                       ▼  Eventarc
                   Cloud Workflows « auditbridge-gates »   (1 exécution durable par facture)
                       ├─ Gate 2 ∥ Avocat      ── callback ──► attend le clic (48 h SLA)
                       ├─ Gate 2 ∥ Consultant  ── callback ──► attend le clic (48 h SLA)
                       └─ Gate 3   Auditeur     ── callback ──► signature finale
                       ▼
                   BigQuery war_room.audit_logs  (chaîne de hash SHA-256 par client)
```

**Message pour l'oral (30 s) :**
- *Sécurité dès la conception* : chaque facture traverse un pare-feu **sans IA** avant d'atteindre un agent. Un document d'un autre client, une injection de prompt ou un fichier déguisé sont bloqués et tracés.
- *L'humain garde la main* : même l'Auditeur ne peut pas conclure tant que l'Avocat et le Consultant n'ont pas répondu.
- *Preuve d'audit* : chaque décision est chaînée par empreinte cryptographique ; modifier une ligne après coup est détecté.
- *Passage à l'échelle* : chaque facture devient une exécution Cloud Workflows qui « dort » sans coût en attendant les experts ; Pub/Sub absorbe les pics de clôture (des milliers de factures le 31/12).

## 3. Mise en production (à faire par l'équipe après la fusion)

```bash
# 1. Redéployer l'API (une seule instance pour garder la chaîne de logs continue pendant la démo)
gcloud run deploy war-room --source . --region europe-west1 --allow-unauthenticated --max-instances=1 \
  --set-env-vars=USE_REAL_GCP_DATA=true,GCP_PROJECT_ID=deloitteinnov26par-598,BQ_DATASET=war_room
```

```bash
# 2. Ajouter les colonnes de hash dans BigQuery (requête 1 de scripts/bq_governance.sql)
bq query --use_legacy_sql=false "ALTER TABLE \`war_room.audit_logs\` ADD COLUMN IF NOT EXISTS prev_hash STRING, ADD COLUMN IF NOT EXISTS hash STRING"
```

```bash
# 3. (Optionnel) Brancher Pub/Sub + Cloud Workflows
bash scripts/deploy_scale.sh
```

Vérifier ensuite dans BigQuery avec les requêtes 2 à 4 de `scripts/bq_governance.sql`.

## 4. Limites connues (à assumer en Q&A)

- La chaîne de hash est tenue en mémoire par instance : en production, la tête de chaîne irait dans Firestore/Spanner (transaction) ou on activerait la rétention verrouillée BigQuery / un bucket GCS avec *Bucket Lock*.
- Les notifications Gate 2 du workflow sont journalisées (`GATE2_BRIEF_SENT` + URL de callback) ; l'envoi par email/Google Chat est l'étape suivante.
- Les dossiers sont en mémoire dans Cloud Run (démo) ; en production : Firestore.
