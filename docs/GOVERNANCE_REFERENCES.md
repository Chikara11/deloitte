# Référentiel Réglementaire & Gouvernance — AuditBridge

> Ce document recense les textes publics européens, français et normes d'audit utilisés comme **références obligatoires** dans chaque contrôle, alerte et **Fiche de Contrôle Documentée** d'AuditBridge.

---

## 1. EU AI Act — Règlement (UE) 2024/1689
- **Art. 9 — Système de gestion des risques :** Identification et atténuation continue des risques avant mise en production (Gate 1 Pare-feu Cyber).
- **Art. 12 — Enregistrement & Traçabilité :** Journalisation automatique et immuable des événements (`war_room.audit_logs` dans BigQuery + HUD SSE).
- **Art. 13 — Transparence & Explicabilité :** Formule explicite et reproductible du Score de Confiance (`100 - 20*échecs - 30*Avocat - 30*Consultant`).
- **Art. 14 — Contrôle Humain (Human Oversight) :** Validation humaine obligatoire aux **Gates 2 & 3** (Avocat, Consultant, Auditeur) — l'IA propose, l'humain décide.
- **Art. 15 — Exactitude, Robustesse & Cybersécurité :** Règles d'audit en Python déterministe (zéro calcul mental LLM) + protection contre les injections de prompt via **Model Armor**.

---

## 2. RGPD / GDPR — Règlement (UE) 2016/679
- **Art. 5(1)(c) & Art. 25 — Minimisation & Privacy by Design :** Pseudonymisation systématique des données personnelles et IBAN (`[PER_*]`, `[IBAN_*]`) par **Cloud DLP** avant tout appel LLM.
- **Art. 32 — Sécurité du traitement :** Cloisonnement strict par `tenant_id` (isolation multi-clients), comptes de service IAM séparés et chiffrement **Cloud KMS** (`war-room-keyring`).

---

## 3. Normes Comptables, Fiscales & d'Audit (PCG / IFRS / ISA / OCDE)
- **Cut-off (`CUT_OFF`) :** *PCG Art. 512-1 & IAS 1 / IFRS 15* — Principe d'indépendance des exercices (rattachement des charges et produits à l'exercice de réalisation effective de la prestation).
- **Concordance (`CONCORDANCE`) :** *ISA 500 / NEP 500* — Caractère probant des éléments collectés (rapprochement exact pièce justificative vs écriture comptable).
- **TVA (`TVA`) :** *Directive TVA 2006/112/CE & CGI Art. 256 / 262 ter* — Justification obligatoire d'un taux de TVA à 0 % sur les prestations et flux intra-communautaires.
- **Intercompagnie (`INTERCOMPAGNIE`) :** *IFRS 10 (B86) & Principes OCDE Prix de Transfert* — Réciprocité, élimination des soldes intra-groupe et principe de pleine concurrence.
- **Seuil (`SEUIL`) :** *ISA 320 / NEP 320* — Caractère significatif (seuil de matérialité défini par client dans son Passeport).
