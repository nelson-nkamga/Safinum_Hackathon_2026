# SAFINUM 2026 — Guide de lancement et de test

Extension Chrome qui traduit l'interface d'un service financier du français/anglais
vers l'**ewondo** (seule langue nationale activée), sans jamais modifier ni exposer
une donnée sensible.

**Ce guide est conçu pour qu'un vérificateur n'ait rien à décider** : chaque étape
donne la commande ou le clic exact, et le résultat attendu. Durée totale : ~10 minutes
(~3 min si l'environnement est déjà préparé, ce qui est le cas sur la machine de démo).

```
Module 1 (navigateur)           Module 3 (extension React)         Module 2 (backend)
privacy + extractor + observer  display.ts + popup + service       FastAPI + Marian
─────────────────────────       worker                             ────────────────────
extrait les textes du DOM  ──►  transport : payloads masqués  ──►  mémoire → glossaire →
masque montants/tél/noms        (lang + ctx par item)              Marian (pivot fr pour EN)
(⟦M1⟧, ⟦N1⟧…)                                                     → validateur → repli sûr
reçoit [{id, text}]        ◄──  résultats [{id, translated}] ◄──  [{id, text, status, …}]
valide + réinjecte les          statuts/avertissements             réponse en 2 contrats
vraies valeurs à l'écran        dans le popup                      (canonique + legacy)
```

---

## Étape 1 — Lancer le projet (une seule commande)

Dans un terminal, à la racine du projet :

```bash
./start.sh
```

Le script fait tout, dans l'ordre, et s'arrête avec un message clair si quelque chose
manque : vérification de Python, création de l'environnement (première fois seulement),
installation des dépendances (première fois seulement), vérification des modèles,
arrêt d'une instance précédente, démarrage de l'API, attente de la santé, serveur de
la page de test.

**Résultat attendu** (les durées varient) :

```
[safinum] Python 3.13 détecté
  ✔ Dépendances Python prêtes
  ✔ Modèles Marian présents (4 directions)
[safinum] Démarrage de l'API et chargement des modèles (~20-30 s …)…
  ✔ API prête : http://127.0.0.1:8000  (documentation interactive : /docs)
  ✔ Page de test servie : http://127.0.0.1:8080/demo/live-test.html
──────────────────────────────────────────────────────────────────────────────
  ✔ LANCEMENT TERMINÉ — la suite se passe dans Chrome : …
```

> **Mode automatique** : s'il n'existe encore aucune traduction validée par un
> locuteur (cas actuel), le script démarre en **mode démonstration** — les brouillons
> du modèle s'affichent marqués « à relire ». Dès qu'au moins une traduction est
> validée dans la mémoire, le mode **production** s'applique seul (traductions
> validées uniquement). Forcer un mode : `./start.sh --demo` ou `./start.sh --production`.
>
> Laissez le terminal ouvert (il affiche les journaux). Pour tout arrêter : `./start.sh --stop`.
> Pour lancer les tests automatiques : `./start.sh --tests` (57 tests backend + chaîne e2e).

**Vérification immédiate (optionnelle)** — ouvrez http://127.0.0.1:8000/health :
la réponse contient `"status": "ok"`, le format de jetons et la liste des 4 `directions`
de modèles chargées.

---

## Étape 2 — Charger l'extension dans Chrome (5 clics)

1. Ouvrir **chrome://extensions** dans la barre d'adresse ;
2. Activer l'interrupteur **« Mode développeur »** (en haut à droite) ;
3. Cliquer **« Charger l'extension non empaquetée »** ;
4. Choisir le dossier **`safinum-extension-react/safinum-react-release/dist`**
   (depuis la racine du projet) ;
5. Épingler l'icône SAFINUM : cliquer la pièce de puzzle 🧩 de la barre d'extensions,
   puis la broche 📌 à côté de « SAFINUM ».

**Résultat attendu** : une carte « SAFINUM » apparaît dans chrome://extensions,
avec une icône colorée dans la barre d'outils.

---

## Étape 3 — Tester la traduction

### 3a. Sur le site de test officiel (recommandé)

1. Ouvrir **https://safinum.cm/hackathon-test** ;
2. Cliquer l'icône SAFINUM : le popup s'ouvre ;
3. Sélectionner **« Ewondo »** dans la liste des langues ;
4. Activer l'interrupteur de traduction (le mode « simulation » se décoche tout seul
   dès que l'API répond) ;
5. Naviguer : Accueil → Effectuer un transfert → Montant → Bénéficiaire →
   Récapitulatif → Confirmation.

**Résultat attendu** :

- les libellés et phrases d'interface s'affichent en ewondo (mode démonstration :
  ce sont des brouillons du modèle, la popup les signale « à relire ») ;
- **montants, numéros de téléphone, noms, références restent inchangés** ;
- l'anglais est traduit aussi (pivot anglais → français → ewondo) ;
- toute phrase inconnue du système **reste en français** (repli sûr) au lieu d'un
  contresens ;
- le popup affiche les statistiques (textes traduits, replis, données protégées).

### 3b. Sans le site officiel — page de test locale

Ouvrir **http://127.0.0.1:8080/demo/live-test.html** puis cliquer **« Traduire (ewondo) »**.

Cette page charge exactement les mêmes fichiers que l'extension et réplique son
transport. Résultat attendu (la page contient son propre guide en encadré) :

| Texte | Comportement attendu |
|---|---|
| Titre « Transfert effectué », message de succès, libellés (Bénéficiaire, Montant, Téléphone, Référence), « Bonjour, Jean Dupont », « Frais de transfert : 500 FCFA », phrase de vérification, boutons « Confirmer le transfert » / « Retour » | ✅ traduits en ewondo (brouillons « à relire » en mode démo) |
| « Jean Dupont », « 50 000 FCFA », « 6 70 00 00 00 », « SAF-2026-0RGVFI » | ✅ **jamais modifiés** (données sensibles masquées puis restituées à l'identique) |
| « Annuler » | 🟠 reste en français : hors mémoire (repli sûr) |
| « Attention : ne partagez jamais votre code secret… » | 🟠 reste en français : alerte de sécurité, jamais traduite sans validation humaine |
| Bouton « Faire apparaître un message dynamique » | ✅ le nouveau texte « Veuillez confirmer votre opération. » est traduit à la volée |

### 3c. Vérifier les compteurs

- Dans la **popup** de l'extension : traductions appliquées, replis, textes protégés ;
- Dans la console du navigateur (F12) sur la page de test : `SafinumLang.observer.stats()`.

---

## Étape 4 — Vérifier le backend sans navigateur (optionnel)

```bash
curl -s http://127.0.0.1:8000/health | python3 -m json.tool    # état des 4 modèles
curl -s http://127.0.0.1:8000/languages | python3 -m json.tool # ewondo : 4 directions
curl -s -X POST http://127.0.0.1:8000/translate \
  -H 'Content-Type: application/json' \
  -d '{"target_language":"ewondo","texts":[{"id":"1","text":"Confirmer le transfert"}]}'
# → {"translations":[{"id":"1","translated":"Adzoe mëkpamaṅ, asu yë na mibòòlò ziṅ.", …}]} (mode démo)

# Garde serveur : une donnée sensible envoyée NON masquée est refusée (comportement voulu) :
curl -s -X POST http://127.0.0.1:8000/translate \
  -H 'Content-Type: application/json' \
  -d '{"target_language":"ewondo","texts":[{"id":"2","text":"Frais de transfert : 500 FCFA"}]}'
# → "status": "rejected", "reasons": ["sensitive:amount"] — le montant n'est ni traduit ni journalisé

curl -s http://127.0.0.1:8000/docs                             # documentation interactive
```

---

## Dépannage

| Symptôme | Cause probable | Solution |
|---|---|---|
| `start.sh` s'arrête sur « python3 introuvable » | Python absent | Installer Python 3.11+ (paquets `python3`, `python3-venv`) puis relancer |
| `start.sh` s'arrête sur « modèle manquant » | dossier `models/` incomplet | Voir `safinum-module2/README.md` §Téléchargement des modèles, puis relancer |
| Le popup dit « API injoignable » / tout reste français | backend pas lancé ou arrêté | Relancer `./start.sh` ; vérifier http://127.0.0.1:8000/health |
| « Échec du chargement de l'extension » dans Chrome | mauvais dossier choisi | Choisir le dossier **`dist`** (pas `dist/..`, pas la racine du projet) |
| La page ne change pas en cliquant « Traduire » | traduction déjà appliquée ou API occupée au 1er appel | Cliquer d'abord « Revenir au français » puis « Traduire (ewondo) » ; le 1er appel peut prendre jusqu'à 90 s (chargement du modèle) |
| Des étiquettes « Non traduit » apparaissent à côté des textes | une **ancienne version** de l'extension est encore chargée (deux cartes SAFINUM dans chrome://extensions) | Supprimer les anciennes cartes (Corriger/Supprimer), ne garder que celle chargée depuis `dist`, puis recharger la page |
| Tout reste en français en mode production | aucune traduction validée par un locuteur | C'est le comportement normal et sûr : valider le classeur (ci-dessous) ou lancer `./start.sh --demo` |
| « Annuler » ou une phrase inconnue reste français | hors mémoire / alerte de sécurité | Comportement voulu (repli sûr) — voir la boucle d'amélioration ci-dessous |
| Port 8000 déjà utilisé par une autre API | instance précédente | `./start.sh --stop` puis `./start.sh` |
| Windows | le script est bash | Utiliser WSL (Ubuntu) ou exécuter manuellement les commandes du §Étape 1 de `safinum-module2/README.md` |

---

## Arrêter proprement

```bash
./start.sh --stop
```

---

## Pour aller plus loin

### Workflow de validation par un locuteur ewondo (l'étape qui fait passer en production)

Le modèle Marian réel est entraîné sur un corpus biblique : ses brouillons sont
exploitables mais imparfaits. La règle du projet : **seul un locuteur ewondo rend une
traduction définitive** — jamais la machine.

1. `cd safinum-module2 && source .venv/bin/activate && python tools/export_xlsx.py`
   → classeur `validation_traductions.xlsx` (90 brouillons déjà remplis) ;
2. le locuteur corrige la colonne « traduction », met le statut `validated` et **son nom** ;
3. `python tools/import_xlsx.py validation_traductions.xlsx`
   → refus automatique de toute ligne sans nom, avec jetons altérés ou statut invalide ;
4. `curl -X POST http://127.0.0.1:8000/reload` → les traductions validées s'affichent
   immédiatement, **sans redémarrer** ; relancer sans `--demo` passe en mode production ;
5. dès ≥ 5 phrases validées : `python scripts/calibrate.py ewondo` → le seuil
   `SAFINUM_MIN_BT` du validateur est calibré sur le jugement des locuteurs.

### Boucle d'amélioration continue

Chaque phrase aperçue sur le site mais inconnue de la mémoire est journalisée dans
`unseen.jsonl` (texte masqué uniquement, jamais de donnée sensible) :

`unseen.jsonl` → `python tools/fill_drafts.py ewondo` → `python tools/export_xlsx.py`
→ validation locuteur → `import_xlsx.py` → `/reload`. La couverture ewondo grandit
sans jamais dégrader la qualité.

### Où est chaque pièce

| Élément | Chemin |
|---|---|
| Lanceur tout-en-un | `start.sh` (racine) |
| Module 1 (sources complètes) | `Module1_safinum/{privacy,extractor,observer}.js` |
| Module 1 embarqué dans l'extension | `safinum-extension-react/safinum-react-release/public/safinum-core/` |
| Module 2 (backend réel) | `safinum-module2/` (README détaillé, 57 tests) |
| Module 3 (extension React) | `safinum-react-release/` (build → `dist/`) |
| Page de test locale | `safinum-react-release/demo/live-test.html` (servie par `start.sh`) |
| Chaîne e2e Node | `safinum-module2/integration/e2e_node_test.js` |
| Classeur de validation locuteur | `safinum-module2/validation_traductions.xlsx` |
| Note technique (livrable) | `NOTE_TECHNIQUE.md` / `NOTE_TECHNIQUE.pdf` |

### Règles de sécurité vérifiées

1. **Rien de sensible ne sort du navigateur** : `privacy.mask()` remplace montants,
   téléphones, comptes, références, dates, noms par ⟦M1⟧ ⟦T1⟧… ; `assertSafe()` bloque
   l'envoi en cas de fuite ; le serveur (`guard.py`) rejette en dernier recours
   (`status: rejected`). Le masquage ne modifie jamais le DOM : seule une traduction
   validée réécrit un texte, et toujours avec les vraies valeurs restituées.
2. **Rien de faux à l'écran** : le validateur refuse la traduction machine douteuse
   (jetons perdus, chiffres changés, rétro-traduction faible) → le texte français
   d'origine reste affiché.
3. **Avertissements de sécurité** (`ctx.alert`) : jamais traduits automatiquement sans
   traduction validée en mémoire.
4. **Pages anglaises** : le module 1 détecte la langue par texte (`lang: 'fr'|'en'`),
   transmise à l'API ; l'anglais passe par le pivot anglais → français → ewondo.
