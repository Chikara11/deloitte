# AuditBridge — Pitch Deck (5 Slides • 5 Minutes) & Speaker Script

> **Consigne orale :** Rester centré sur l'**Audit Financier Deloitte**, l'impact métier (*5 jours d'e-mails $\rightarrow$ 10 minutes*), la démo live des 3 cas, et la confiance/gouvernance GCP — sans s'attarder sur les détails d'implémentation code.

---

## Slide 1 — Le Problème : Une Facture de 2 M€ = 5 Jours d'E-mails & Risques Cyber *(0:00 – 0:50)*

### Visuel suggéré
- À gauche : **Facture complexe 2 000 000 €** (Cut-off / Inter-compagnie) entourée de 3 silos : `Auditeur`, `Avocat Tax & Legal`, `Consultant`.
- À droite : **4 risques rouges** : `5 jours d'e-mails`, `Fuite PII / NDA`, `PDF piégé (Prompt Injection)`, `Contrôle interne non documenté`.

### Bullets Slide
- **Le cas réel :** Une facture de prestation inter-compagnie de **2 M€** fin décembre.
- **Silos métiers :** L'auditeur ne peut pas valider seul la livraison (**Consultant**) ni la TVA / prix de transfert (**Avocat Tax & Legal**).
- **Données hétérogènes :** Formats ERP/PDF différents selon chaque client (PCG vs IFRS).
- **Pourquoi un simple LLM échoue :** Risque de fuite PII, PDF hostile (prompt injection), hallucinations mathématiques et zéro piste d'audit.

### Script Oral (FR)
> *« En audit financier chez Deloitte, les anomalies les plus coûteuses viennent des factures de prestations et des flux inter-compagnies en fin d'exercice. Aujourd'hui, vérifier une facture suspecte de 2 M€ prend jusqu'à **5 jours d'e-mails** entre l'auditeur, l'avocat Tax & Legal et le consultant. Et on ne peut pas simplement la coller dans un chatbot : les données clients sont confidentielles, les formats changent d'un client à l'autre, et un PDF vendeur peut même contenir une attaque par prompt injection. »*

---

## Slide 2 — La Solution : AuditBridge, le Pont Sécurisé sur Google Cloud *(0:50 – 1:40)*

### Visuel suggéré
- Schéma simplifié **3 Gates** :
  - `Gate 1 (Pare-feu Cyber sans IA)` $\rightarrow$ `Passeport Client → JSON Canonique` $\rightarrow$ `Agents (Auditeur + Passerelle)` $\rightarrow$ `Gate 2 (Avocat + Consultant)` $\rightarrow$ `Agent Synthèse` $\rightarrow$ `Gate 3 (Auditeur)` $\rightarrow$ `📄 Fiche de Contrôle`.

### Bullets Slide
- **Passeport Client (Multi-Clients) :** Un fichier JSON par client (norme IFRS/PCG, seuils, TVA) — zéro modification de code pour on-boarder un nouveau client.
- **3 Agents Spécialisés (ADK + Gemini) :**
  - **Agent Auditeur :** 5 règles déterministes (Cut-off, Concordance, TVA, Intercompagnie, Seuil).
  - **Agent Passerelle :** Traduit l'anomalie en **Micro-Briefs** fermés pour l'Avocat et le Consultant.
  - **Agent Synthèse :** Calcule un **Score de Confiance** transparent (`0–100`).
- **Livrable Automatique :** Génère la **Fiche de Contrôle Documentée** prête pour le dossier d'audit.

### Script Oral (FR)
> *« Voici **AuditBridge**. Chaque client dispose d'un **Passeport** qui normalise ses factures vers un format unique. Notre **Agent Auditeur** applique 5 règles déterministes fiables. Dès qu'une anomalie apparaît, l'**Agent Passerelle** envoie un Micro-Brief ciblé à l'Avocat et au Consultant. L'IA propose, les experts arbitrent en un clic, et AuditBridge génère automatiquement la **Fiche de Contrôle Documentée**. »*

---

## Slide 3 — Démo Live : 3 Cas en Temps Réel *(1:40 – 3:30)*

### Séquence Démo sur `https://war-room-445615405690.europe-west1.run.app`
1. **✅ Cas 1 — Facture Normale (`CLIENT_A`, 35 k€) :**
   - 5/5 règles OK $\rightarrow$ Score **100/100 🟢** $\rightarrow$ Fiche de contrôle verte générée immédiatement.
2. **⚠️ Cas 2 — Facture Inter-compagnie 2 M€ (`CLIENT_B`) :**
   - Prestation réalisée en **janvier 2027** mais comptabilisée en **décembre 2026**, TVA **0 %** $\rightarrow$ Escalade vers **Avocat** (*Non conforme*) et **Consultant** (*Livré en 2027*) $\rightarrow$ Score **0/100 🔴** $\rightarrow$ **Gate 3 Auditeur** valide la recommandation $\rightarrow$ **Exporter (.md)**.
3. **🛡️ Cas 3 — Facture PDF Piégée (`CLIENT_B`) + Test Isolation + IAM 403 :**
   - Le PDF contenant *« IGNORE ALL PREVIOUS INSTRUCTIONS »* est bloqué à la **Gate 1 par Model Armor** : le panneau **Sécurité & Gouvernance** à droite s'allume en rouge en direct.

---

## Slide 4 — Sécurité, Gouvernance & Passage à l'Échelle GCP *(3:30 – 4:25)*

### Bullets Slide
- **Gate 1 Zero-Trust (avant tout LLM) :** Isolation `tenant_id`, **Model Armor** (anti-injection), pseudonymisation **Cloud DLP** (`[PER_8785]`, `[IBAN_c24b]`).
- **Supervision Humaine (EU AI Act) :** Gates 2 & 3 obligatoires avant toute clôture.
- **Traçabilité Immuable :** Chaque blocage, règle et validation est journalisé dans **BigQuery** (`war_room.audit_logs`) et **Cloud Logging**.
- **Architecture à l'échelle :** Déployé sur **Cloud Run**, extensible vers **Pub/Sub + Cloud Workflows + Vertex AI Agent Engine + VPC Service Controls**.

---

## Slide 5 — Valeur Métier & ROI pour Deloitte *(4:25 – 5:00)*

### Chiffres Clés
- ⏱️ **De 5 jours d'e-mails à 10 minutes** par transaction complexe.
- 🌍 **Multi-clients instantané :** Nouveau client = 1 **Passeport JSON**, sans redéployer.
- 📄 **100 % des contrôles documentés** automatiquement (conformité audit & AI Act).

---

## Top 5 Questions / Réponses Jury (Deloitte & Google Cloud)

1. **Q : Comment garantissez-vous que le LLM ne se trompe pas dans les calculs ?**  
   **R :** Les 5 règles d'audit et le Score de Confiance sont du **code Python déterministe** (et SQL BigQuery), jamais du calcul mental par le LLM. Gemini sert uniquement à synthétiser et traduire les Micro-Briefs.
2. **Q : Comment empêchez-vous les données du Client A de fuiter vers le Client B ?**  
   **R :** Contrôle strict du `tenant_id` à la Gate 1 (démontré par le bouton *Test Isolation*), pseudonymisation Cloud DLP avant tout prompt, et comptes de service GCP séparés (`sa-legal`, `sa-quant`, `sa-forensic`).
3. **Q : Que se passe-t-il si le vendeur cache un prompt malveillant dans un PDF ?**  
   **R :** **Model Armor** intercepte l'instruction à la Gate 1 *avant* l'appel LLM, met la pièce en quarantaine, et journalise l'incident en rouge dans BigQuery `audit_logs`.
4. **Q : Comment passez-vous d'une démo à 10 000 factures par nuit ?**  
   **R :** En production, l'ingestion passe par **Cloud Storage $\rightarrow$ Pub/Sub $\rightarrow$ Cloud Workflows** orchestrant des workers **Cloud Run / Agent Engine** en parallèle, avec notifications **Slack/Teams** pour les Gates 2 & 3.
5. **Q : En quoi cela respecte-t-il l'EU AI Act ?**  
   **R :** Transparence de la formule de score, traçabilité immuable dans BigQuery, et double **supervision humaine** obligatoire (Gates 2 & 3) avant toute décision d'audit.
