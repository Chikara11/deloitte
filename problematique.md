# Problématique & Solution — AuditBridge (Deloitte × Google Cloud)

> **Pitch en 1 phrase :** *AuditBridge transforme 5 jours d'e-mails risqués entre l'Auditeur, l'Avocat Tax & Legal et le Consultant sur une facture complexe de 2 M€ en 10 minutes de contrôle sécurisé, traçable et automatiquement documenté sur Google Cloud.*

---

## 1. La Problématique : Le Contrôle des Prestations & Transactions Complexes (Cut-off / Inter-compagnies)

En audit financier chez **Deloitte**, les erreurs et fraudes les plus coûteuses proviennent des **factures de prestations** ou des **flux inter-compagnies** à fort montant (ex. une facture de conseil stratégique de **2 M€** datée du 28 décembre 2026) :

1. **Silos entre les 3 métiers de Deloitte :**
   - **L'Auditeur** ne sait pas seul si la prestation a *vraiment été livrée* (il a besoin du **Consultant**).
   - Il ne sait pas seul si le montage inter-compagnies ou la TVA à 0 % sont *conformes* (il a besoin de l'**Avocat Tax & Legal**).
   - Résultat : **5 jours d'allers-retours par e-mail**, perte de temps et risque d'erreur.
2. **Hétérogénéité des données clients :**
   - Chaque client a son propre format (export ERP CSV/JSON pour le Client A, factures PDF + grand livre pour le Client B), ses normes (**IFRS vs PCG**) et ses seuils de matérialité.
3. **Risques Cyber & Confidentialité (Data Room hostile) :**
   - Les données clients sensibles (noms, IBANs, montants) risquent de fuiter vers un LLM non protégé ou entre deux dossiers clients.
   - Des factures PDF peuvent contenir des **pièges cyber** (*indirect prompt injection* : `IGNORE ALL PREVIOUS INSTRUCTIONS...`).
4. **Documentation des contrôles internes :**
   - L'auditeur doit produire une **fiche de contrôle documentée** prouvant quelles règles ont été testées, sur quelles preuves et qui a validé quoi — tâche manuelle fastidieuse.

---

## 2. La Solution : AuditBridge sur Google Cloud Platform (3 Gates + Multi-Agents)

### Gate 1 — Le Pare-feu Cyber (sans IA, exécuté avant tout LLM)
1. **Vérification `tenant_id` :** Un document du Client A déposé dans le dossier du Client B est immédiatement rejeté (`TENANT_ISOLATION_BLOCK`).
2. **Model Armor :** Détecte toute injection de prompt ou URL malveillante dans les PDF et met le document en **quarantaine** (`MODEL_ARMOR_BLOCK`).
3. **Pseudonymisation (Cloud DLP / Python) :** Masque les noms, entités et IBANs (`[PERSONNE_1]`, `[ENTITE_1]`, `[IBAN_1]`) avant tout appel LLM.

### Normalisation via le « Passeport Client » $\rightarrow$ JSON Canonique
Un fichier de configuration JSON par client (**Passeport Client**) décrit le mapping de colonnes, le référentiel (IFRS/PCG), la date de clôture, le taux de TVA attendu et le seuil de matérialité. Tout input hétérogène est normalisé en un **JSON Canonique** unique — sans modifier une ligne de code pour un nouveau client.

### Les 3 Agents IA (ADK + Gemini + Règles Python)
1. **🔎 Agent Auditeur (5 règles Python déterministes + explication Gemini) :**
   - **Cut-off :** prestation réalisée en 2027 mais comptabilisée en 2026 $\rightarrow$ *Anomalie*.
   - **Concordance :** montant facture $\neq$ écriture comptable $\rightarrow$ *Anomalie*.
   - **TVA :** taux à 0 % inattendu (vs passeport client) $\rightarrow$ *À vérifier*.
   - **Intercompagnie :** flux intra-groupe à vérifier en réciprocité.
   - **Seuil :** montant $>$ seuil du passeport client $\rightarrow$ *Examen renforcé*.
   *(Si tout est OK $\rightarrow$ génération directe de la Fiche de Contrôle verte. Si Anomalie $\rightarrow$ déclenche l'Agent Passerelle.)*
2. **🌉 Agent Passerelle :**
   - Traduit l'anomalie dans la langue de chaque métier sous forme de **Micro-Briefs** fermés :
     - ⚖️ **Avocat Tax & Legal :** *« Le montage et la TVA sont-ils conformes ? »*
     - 💼 **Consultant :** *« La prestation a-t-elle vraiment été livrée ? »*
3. **📊 Agent Synthèse (Score de Confiance) :**
   - Formule transparente et auditable :
     - Base **100**
     - **−20** par règle en échec
     - **−30** si l'Avocat répond *« Non conforme »*
     - **−30** si le Consultant répond *« Non livré »*
   - Décision : **$\ge 70$** 🟢 Valider | **40–69** 🟠 Ajuster / Provisionner | **$< 40$** 🔴 Rejeter / Signaler fraude.

### Gates 2 & 3 (Supervision Humaine AI Act) & Livrable Final
- **Gate 2 :** L'Avocat et le Consultant valident en 1 clic dans leurs onglets respectifs.
- **Gate 3 :** L'Auditeur valide ou rejette la conclusion finale.
- **📄 Fiche de Contrôle Documentée :** Générée automatiquement en **Markdown** (exportable), avec objectif, population testée, résultats des 5 règles, avis horodatés des experts, score de confiance et identité du valideur.

---

## 3. Trame du Pitch (5 Slides — 5 Minutes)

1. **Le Problème :** Une facture intercompagnie de **2 M€** suspecte = **5 jours d'e-mails** entre auditeur, avocat et consultant, risque de fuite de données, PDF piégés et contrôles internes à documenter à la main.
2. **La Solution AuditBridge :** Un pont sécurisé sur GCP reliant les 3 métiers de Deloitte grâce aux **Passeports Clients** + **JSON Canonique** + **3 Gates**.
3. **Démo Live (les 3 cas) :**
   - ✅ **Cas 1 (Client A) :** Facture normale $\rightarrow$ 5/5 règles OK $\rightarrow$ Score 100 🟢 $\rightarrow$ Fiche verte.
   - ⚠️ **Cas 2 (Client B, 2 M€) :** Cut-off 2027/2026 + TVA 0% + Intercompagnie $\rightarrow$ Micro-Briefs $\rightarrow$ Avocat *Non conforme* + Consultant *Non livré (2027)* $\rightarrow$ Score **0 🔴** $\rightarrow$ Gate 3 Auditeur $\rightarrow$ **Fiche de Contrôle**.
   - 🛡️ **Cas 3 (PDF Piégé) :** Bloqué à la Gate 1 par **Model Armor** + HUD rouge en direct.
4. **Confiance & Gouvernance GCP :** Isolation `tenant_id`, pseudonymisation DLP, supervision humaine (AI Act), traçabilité **Cloud Logging / BigQuery**.
5. **Valeur & Passage à l'Échelle :** De **5 jours à 10 minutes**, extensible à tout client par simple ajout de Passeport, et scalable via **Cloud Run + Pub/Sub + Cloud Workflows + Agent Engine**.
