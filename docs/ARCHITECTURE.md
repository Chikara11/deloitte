# Architecture — AuditBridge (Deloitte × Google Cloud)

## 1. Flux Complet

```text
           📥 ENTRÉES (CLIENT_A : ERP CSV/JSON | CLIENT_B : PDF + Grand Livre)
                                         │
                                         ▼
╔══════════════ GATE 1 : PARE-FEU CYBER (sans IA) ════════════════════╗
║ ① Vérification tenant_id (isolation multi-clients)                  ║
║ ② Model Armor (prompt injection / URL malveillante -> QUARANTAINE)  ║
║ ③ Pseudonymisation DLP/Python ([PERSONNE_1], [ENTITE_1], [IBAN_1])  ║
╚══════════════════════════════════════════════════════════════════════╝
                                         │
                                         ▼
┌──────────── NORMALISATION (Passeport Client -> JSON Canonique) ─────┐
│ Mapping colonnes + règles client (IFRS/PCG, seuil, TVA, clôture)    │
└──────────────────────────────────────────────────────────────────────┘
                                         │
                                         ▼
┌──────────── AGENTS IA (ADK + Gemini + Règles Python) ───────────────┐
│ 🔎 Agent Auditeur : 5 règles Python (Cut-off, Concordance, TVA,     │
│    Intercompagnie, Seuil) -> OK ou ANOMALIE                         │
│ 🌉 Agent Passerelle (si ANOMALIE) -> 2 Micro-Briefs :               │
│    ⚖️ Avocat Tax & Legal | 💼 Consultant                            │
└──────────────────────────────────────────────────────────────────────┘
                                         │
                                         ▼
╔══════════════ GATE 2 : VALIDATION DES EXPERTS 👤 ════════════════════╗
║ Onglets Avocat & Consultant (Conforme/Non conforme, Livré/Non livré)║
╚══════════════════════════════════════════════════════════════════════╝
                                         │
                                         ▼
┌──────────── AGENT SYNTHÈSE ─────────────────────────────────────────┐
│ Score = 100 - 20*(règles échec) - 30*(Avocat) - 30*(Consultant)     │
└──────────────────────────────────────────────────────────────────────┘
                                         │
                                         ▼
╔══════════════ GATE 3 : DÉCISION DE L'AUDITEUR 👤 ════════════════════╗
║ L'auditeur valide ou rejette la conclusion                          ║
╚══════════════════════════════════════════════════════════════════════╝
                                         │
                                         ▼
📄 FICHE DE CONTRÔLE DOCUMENTÉE (Markdown exportable)
📝 EN CONTINU : Cloud Logging + BigQuery Audit Sink + HUD SSE en direct
```

---

## 2. Contrat JSON Canonique

```json
{
  "tenant_id": "CLIENT_B",
  "invoice_id": "F-2026-0412",
  "supplier": "[ENTITE_1]",
  "customer": "[ENTITE_2]",
  "is_intercompany": true,
  "amount_ht": 2000000,
  "vat_rate": 0.0,
  "amount_ttc": 2000000,
  "invoice_date": "2026-12-28",
  "service_date": "2027-01-15",
  "ledger_entry": {"account": "622600", "amount": 2000000, "period": "2026-12"},
  "description": "Prestations de conseil stratégique",
  "source_file": "facture_0412.pdf",
  "security": {"model_armor": "clean", "pii_masked": 3}
}
```

---

## 3. Stack GCP : Démo vs À l'Échelle

| Brique | Démo (Codé & Déployé) | À l'échelle (Slide Architecture) |
| :--- | :--- | :--- |
| Hébergement | **Cloud Run** | **Cloud Run + Pub/Sub + Cloud Workflows** |
| IA | **ADK + Gemini (Vertex AI)** | **Vertex AI Agent Engine** |
| Sécurité IA | **Model Armor** | **Model Armor + VPC Service Controls** |
| Données personnelles | **Cloud DLP / Pseudonymiseur Python** | **Cloud DLP + KMS** |
| Traçabilité | **SSE HUD + BigQuery `audit_logs`** | **Cloud Logging + BigQuery immuable** |
| Validations humaines | **Onglets Web (Gates 2 & 3)** | **Bot Slack / Microsoft Teams + IAP/IAM** |
