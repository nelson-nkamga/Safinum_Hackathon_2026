# SAFINUM — Traduction des services financiers numériques vers les langues nationales du Cameroun

**Livrables documentaires** — note technique, description de la solution et méthode de validation linguistique.
Projet : extension de traduction d'interface « français/anglais → ewondo » pour le site SAFINUM (services financiers numériques). Date : novembre 2026.

---

## 1. Description succincte de la solution et du problème qu'elle résout

### Le problème

Les interfaces des services financiers numériques au Cameroun sont conçues en **français et en anglais**. Or une grande partie des utilisateurs lisent mieux — ou seulement — une **langue nationale** (ewondo, bulu, duala, bassa…). Cette exclusion linguistique a des conséquences concrètes et graves dans un contexte d'argent :

- l'utilisateur ne comprend pas ce qu'il valide : **montants, frais, bénéficiaire, confirmation** ;
- les **avertissements de sécurité** (ne jamais partager son code, vérifier le bénéficiaire) sont inefficaces s'ils ne sont pas lus ;
- la fracture linguistique devient un facteur d'**exclusion financière** et un vecteur de fraude.

Traduire « à chaud » des interfaces d'argent pose un risque nouveau : **une traduction fausse est plus dangereuse qu'une absence de traduction** (« Votre plafond est atteint » mal traduit peut conduire à une erreur d'opération).

### La solution

Une **extension Chrome** à trois modules qui traduit l'interface de SAFINUM vers l'**ewondo**, avec une garantie centrale : *rien de sensible ne sort du navigateur, et rien de faux ne s'affiche à l'écran*.

| Module | Rôle | Où il tourne |
|---|---|---|
| **1. Protection & extraction** | Parcourt le DOM, masque les données sensibles (montants, téléphones, comptes, références, dates, e-mails, noms) par des jetons `⟦M1⟧ ⟦T1⟧…`, surveille les écrans dynamiques (Vue/Inertia) | Navigateur (content scripts, JS pur) |
| **2. Moteur de traduction** | API locale : mémoire de traduction validée, glossaire financier verrouillé, moteur neuronal Marian (CTranslate2), validateur de qualité, garde-fous | Machine locale (Python / FastAPI) |
| **3. Interface utilisateur** | Popup (choix de langue, statistiques, panneau « Comprendre cette étape »), service worker relais vers l'API, intégration du module 1 | Extension MV3 (React + TypeScript) |

**Résultat mesuré sur le site réel** : les écrans du parcours Solde → Frais → Bénéficiaire → Récapitulatif → Confirmation s'affichent en ewondo ; les montants, numéros et noms restent inchangés ; toute traduction jugée douteuse est automatiquement remplacée par le texte français d'origine.

---

## 2. Note technique

### 2.1 Architecture

```
        NAVIGATEUR (chrome)                                POSTE LOCAL
┌──────────────────────────────────────────┐    ┌────────────────────────────────┐
│  Module 1 : privacy → extractor →        │    │  Module 2 : FastAPI (port 8000)│
│             observer                     │    │                                │
│   extraction DOM + masquage ⟦M1⟧…        │    │  pipeline (8 étapes) :         │
│         │ payloads masqués               │    │   mémoire validée → glossaire  │
│         ▼                                │    │   → Marian/CT2 → validateur    │
│  Module 3 : service worker (relais) ─────┼───►│   → repli sûr                  │
│   + popup React (statuts, langue)        │    │   mémoire + glossaire (JSON)   │
│         │ résultats [{id,text,status}]   │    │   unseen.jsonl (phrases inéd.) │
│         ▼                                │    │   validation_traductions.xlsx  │
│  observer : validate() + restore()       │    │   4 modèles Marian int8 (74Mo) │
│   → réinjection DOM (valeurs intactes)   │◄───┤   fr↔ew · en→fr→ew (pivot)     │
└──────────────────────────────────────────┘    └────────────────────────────────┘
```

**Pipeline de traduction (8 étapes)** — `safinum-module2/pipeline.py` :

1. recherche exacte dans `memory.json` (forme masquée) → si trouvée et **validée**, renvoyer la traduction humaine ;
2. sinon, protection des termes du glossaire par jetons `⟦G1⟧` ;
3. envoi au moteur Marian (texte protégé, jetons convertis au format que le modèle conserve) ;
4. pour l'anglais : pivot anglais → français → ewondo ;
5. réinsertion des termes du glossaire validés ;
6. contrôles durs : jetons présents une seule fois chacun, chiffres inchangés, pas de copie, pas de répétition, longueur plausible ;
7. **rétro-traduction** ewondo → français comparée à la source (score chrF, seuils calibrables) ;
8. décision : afficher l'ewondo **ou replier** sur le texte français d'origine.

### 2.2 Modalités d'intégration

**Contrat d'API** (deux formats acceptés sur `POST /translate`) :

- canonique (module 1 → module 2) : `{"source":"fr","target":"ewondo","items":[{"id","text","lang","ctx"}]}` — les `items` sont exactement les payloads masqués du module 1 (`ctx.alert` porte l'alerte sécurité, `lang` la langue détectée par texte : `fr`/`en`) ;
- extension React : `{"target_language":"ewondo","texts":[…]}` → réponse `{"translations":[{id, original, translated, status, warning}]}` avec `status` ∈ `human_validated` / `model_generated` / `unavailable`.
- Autres endpoints : `GET /health` (diagnostic complet), `GET /languages`, `GET /model/status`, `POST /reload` (recharge mémoire/glossaire **sans redémarrer**).

**Branchement navigateur** :

- le content script n'appelle jamais `http://127.0.0.1` directement : le **service worker** MV3 (déclaré dans `manifest.json`, `host_permissions` sur `localhost:8000`) relaie les appels et neutralise CORS/PNA — le serveur répond néanmoins correctement aux préflights `Access-Control-Allow-Private-Network` pour les futures pages publiques ;
- l'intégration module 1 ↔ module 3 se fait par une seule interface : `SafinumLang.observer.setTransport / start({transport})` — le transport reçoit les payloads masqués et renvoie `[{id, text}]` (jetons intacts) ;
- réinjection : `privacy.validate()` exige que chaque jeton revienne **exactement une fois** ; `privacy.restore()` remet les vraies valeurs depuis un *vault* resté en mémoire du navigateur ;
- format de jetons découplé : le module 1 n'écrit qu'en `⟦…⟧` ; le moteur convertit à l'entrée/sortie (`TokenCodec`) — le format mesuré le mieux conservé par Marian est `numdash` (**75 %**, mesuré sur le vrai modèle ; `⟦M1⟧` natif : 0 %) ; en cas de perte, le moteur essaie automatiquement les autres formats puis replie.

**Lancement de bout en bout** (documenté à la racine, `README.md`) : `uvicorn main:app --host 127.0.0.1 --port 8000` (`SAFINUM_WARMUP=1` précharge les 4 directions ; `SAFINUM_ALLOW_DRAFT_MEMORY=1` = mode démonstration « brouillons à relire »), puis chargement du dossier `dist/` de l'extension dans `chrome://extensions`.

### 2.3 Dépendances principales

| Composant | Choix | Justification |
|---|---|---|
| Moteur neuronal | **Marian MT converti int8, inférence CTranslate2 4.9** | CPU-only, 74 Mo/direction, pas de PyTorch requis à l'exécution, latence compatible navigateur |
| Modèle | `flagship-ai/cameroon-int8` (4 directions fr↔ew, en↔fr) | Seul dépôt public couvrant l'ewondo ; **licence CC BY-NC 4.0 (usage non commercial — à respecter et déclarer)** |
| Tokenisation | `transformers` MarianTokenizer + sentencepiece | Format du dépôt du modèle |
| API | FastAPI + Pydantic + uvicorn | Contrats typés, docs automatiques, CORS maîtrisé |
| Qualité | rétro-traduction + chrF (implémenté maison, ~80 lignes) | Pas de dépendance externe, seuils calibrables |
| Extension | React 18 + Vite + TypeScript (MV3, service worker) | Popup maintenue, build `dist/` autonome |
| Confort locuteurs | openpyxl (classeur de validation) | Workflow tableur simple |

### 2.4 Limites connues (honnêteté complète)

1. **Qualité du modèle de base** : entraîné sur un corpus **biblique** ; sur les phrases financières hors mémoire, la rétro-traduction score 0.06–0.35 → la MT est refusée et le français s'affiche. L'ewondo visible aujourd'hui = mémoire validée (+ brouillons en mode démo). Levier : affiner le modèle sur un corpus financier, puis recalibrer via `scripts/calibrate.py`.
2. **Mémoire à correspondance exacte** (normalisée casse/espaces/apostrophe/point final) : une phrase « proche mais différente » n'est jamais servie avec la traduction d'une autre (anti-contresens) — au prix d'une couverture strictement limitée aux phrases connues.
3. **Découpage DOM nœud par nœud** : une phrase coupée par une balise interne est envoyée en deux morceaux ; aucun cas gênant identifié sur les 5 écrans connus.
4. **Non lisibles** : textes dans images/canvas/`<title>` d'onglet ; messages d'erreur non encore générés par le site (capturés automatiquement par l'observateur lorsqu'ils apparaîtront).
5. **Déploiement local** : le backend tourne sur la machine de l'utilisateur (`127.0.0.1`) ; une mise en production publique exigerait HTTPS + hébergement + stratégie d'authentification (hors périmètre du prototype).
6. **Permissions d'extension larges** (`<all_urls>`) : à restreindre à `https://safinum.cm/*` pour une distribution.
7. **Licence non commerciale** du modèle (CC BY-NC 4.0) : tout usage commercial requiert l'accord des titulaires.
8. **Capacité par lot** : 50 textes/appel (extension) vs 100 max côté API ; un seul appel par écran en pratique.
9. **Ewondo uniquement** activé : l'ajout d'une langue nationale se fait par configuration (`config.py` → entrée `LANGUAGES` + paires de modèles + colonnes mémoire/glossaire), pas de refactorisation.

---

## 3. Langues nationales prises en charge et méthode de validation linguistique

### 3.1 Langue prise en charge : l'ewondo

- **Langue activée : ewondo** (famille beti-fang, région du Centre et du Sud Cameroun), dans **les 4 directions** : français ↔ ewondo, et anglais ↔ ewondo (par pivot français).
- Le code est **multilingue par configuration** : `config.py` décrit chaque langue (paires de modèles, pivot) ; les écrans, la mémoire, le glossaire et le pipeline sont génériques. Ajouter le bulu ou le duala = ajouter une paire de modèles + une entrée de configuration + une colonne de traduction dans la mémoire/le glossaire — aucune refonte.
- Priorité donnée à l'ewondo par la disponibilité du seul corpus parallèle public (dépôt `flagship-ai/cameroon-int8`) et par l'audience visée.

### 3.2 Méthode de validation linguistique — « l'humain au centre, la machine au service »

Le principe directeur : **une traduction affichée est soit humaine et validée, soit automatique et prouvée, soit elle n'a pas lieu** (repli français).

**a) Contrôles automatiques (bloquants, à chaque traduction)**

- **Contrat des jetons** : tout masquage `⟦M1⟧…` doit revenir exactement une fois — un jeton perdu = montant/téléphone/nom potentiellement perdu → refus immédiat ;
- **Chiffres inchangés**, pas de copie du texte source, pas de répétitions, pas de symboles inconnus (`<unk>`), longueur plausible (ratio 0.25–3.5) ;
- **Rétro-traduction** (ewondo → français par le modèle inverse) comparée à la source (score chrF) : acceptée si ≥ **0.40** (phrase ≥ 4 mots) ou ≥ **0.60** (phrase courte) ; en dessous → **refus, repli français** ; entre 0.40 et 0.65 → acceptée mais marquée **« à relire »** ;
- **Politique des avertissements** : un texte porteur d'alerte sécurité (`ctx.alert`) n'est jamais traduit automatiquement sans traduction validée en mémoire ;
- **Garde-fou serveur** (`guard.py`) : si une donnée sensible a survécu au masquage, le serveur refuse de traduire **et** de journaliser.

**b) Validation humaine (la source de vérité)**

- `memory.json` : chaque phrase porte un **statut** — `todo` → `draft` (proposée par le modèle, **jamais utilisée** par défaut) → `validated` (signée) / `rejected` ; chaque validation enregistre **qui** (`validated_by`) et **quand** (`validated_on`) ;
- Workflow locuteur : `tools/export_xlsx.py` génère un classeur (68 phrases + 27 termes) → le locuteur **corrige** la traduction, met `validated` et **son nom** → `tools/import_xlsx.py` réimporte en **refusant** toute ligne sans nom, avec des jetons altérés ou un statut invalide → `POST /reload` (sans redémarrer) ;
- Glossaire financier : les termes validés sont ensuite **verrouillés par jetons** pendant la traduction automatique — le modèle ne peut plus déformer « frais », « solde », « bénéficiaire » ;
- `scripts/calibrate.py` : dès **≥ 5 (idéalement 30) phrases validées**, mesure la distribution des scores de rétro-traduction des traductions humaines vs automatiques et **suggère le seuil** `SAFINUM_MIN_BT` — le seuil est ainsi calibré sur le jugement des locuteurs, pas sur une intuition.

**c) Boucle d'amélioration continue**

```
site réel → phrases inédites loguées (unseen.jsonl, textes masqués uniquement)
          → le moteur propose des brouillons (fill_drafts)
          → export_xlsx → le locuteur corrige et signe
          → import_xlsx → /reload → l'ewondo validé s'affiche
```

**d) Ce que cette méthode garantit**

| Garantie | Mécanisme |
|---|---|
| Aucune donnée sensible ne sort du navigateur | masquage module 1 + `assertSafe()` + `guard.py` serveur |
| Aucun montant faux à l'écran | jetons vérifiés + chiffres figés + rétro-traduction + repli |
| Traçabilité linguistique | statut + nom + date sur chaque phrase validée |
| Avertissements de sécurité toujours lisibles | jamais traduits sans validation humaine |
| Extension de la couverture sans dégrader la qualité | boucle unseen → draft → validation humaine |

---

## Annexe — état vérifié (14/11/2026)

| Vérification | Résultat |
|---|---|
| Modèles réels chargés (4 directions int8) | ✅ au démarrage de l'API |
| Traduction réelle testée (fr→ew, en→ew pivot, ew→fr, ew→en) | ✅ |
| Format de jeton mesuré sur le vrai modèle | `numdash` 75 % (meilleur de 6 formats) |
| Brouillons produits par le moteur | 90 (63 mémoire + 27 glossaire), en attente de validation |
| Chaîne e2e masquage → API → restauration | ✅ `integration/e2e_node_test.js` — zéro fuite |
| Tests automatiques du backend | 57 ✅ |
| Extension chargée dans Chrome, traduction visible sur le site | ✅ confirmée par test utilisateur |
| Validation locuteur / calibration | ⏳ classeur `validation_traductions.xlsx` prêt |
