# Module 2 — Intelligence artificielle et moteur de traduction

Responsable : Fred. Dépend de `safinum-module1` (extraction + masquage) et fournit l'API qu'appelle l'extension.

## État réel (vérifié sur machine, 14/11/2026)

| Vérification | Résultat |
|---|---|
| Modèles locaux `models/` (4 directions × 74 Mo, int8) | ✅ présents, chargés au démarrage (`SAFINUM_WARMUP=1`) |
| `python scripts/check_directions.py --translate` | ✅ 4 directions OK, traduction + rétro-traduction réelles |
| `python scripts/test_token_formats.py ewondo` | ✅ `numdash` gagne : **75 %** de jetons conservés (native 0 %, square 0 %, brace 0 %, alnum 25 %, num 67 %) → `SAFINUM_TOKEN_FORMAT=numdash` est la valeur par défaut de `config.py` |
| `python tools/fill_drafts.py ewondo` | ✅ 90 brouillons écrits (7 ignorés : jetons/chiffres/copie) |
| `python tools/export_xlsx.py` | ✅ `validation_traductions.xlsx` prêt pour le locuteur |
| `python tools/import_xlsx.py` | ✅ refuse une validation sans nom de locuteur |
| `python scripts/calibrate.py ewondo` | ⏸ exige ≥ 5 traductions VALIDÉES : à lancer après la validation humaine |
| `uvicorn main:app` | ✅ API sur `127.0.0.1:8000`, `/translate`, `/health`, `/languages`, `/reload` testés au curl |
| `python -m pytest tests -q` | ✅ 57 tests passent |
| Chaîne module 1 ↔ module 2 | ✅ `integration/e2e_node_test.js` : masquage → API → validate/restore, aucune fuite |

**Qualité du modèle (constat réel)** : entraîné sur des textes bibliques, il produit un ewondo
biblique sur les phrases financières (« Solde disponible » → phrase biblique). Le validateur
rejette donc la MT hors mémoire validée (`back_translation_low`, `length_ratio`) et le moteur
renvoie le texte français d'origine : **c'est le comportement voulu** (jamais de montant faux
à l'écran). Les écrans ne traduisent que ce que les locuteurs auront validé dans la mémoire,
plus les brouillons si `SAFINUM_ALLOW_DRAFT_MEMORY=1` (mode démo, marqué « à relire »).

## Ce qui est livré

| Livrable du cahier | Fichier(s) | État |
|---|---|---|
| 1. Mémoire de traduction | `memory.json` + `memory.py` | 68 phrases (59 vues sur le site + 9 anticipées, français masqué), **0 traduction** : à faire valider |
| 2. Glossaire multilingue | `glossary.json` + `glossary.py` | 35 termes (29 à traduire, 6 noms propres/sigles gardés tels quels), **0 traduction** |
| 3. Moteur Marian | `translator.py` (+ `config.py`, `textutil.py`) | code complet, testé avec un faux moteur |
| 4. Module de validation | `validator.py` | règles dures + rétro-traduction |
| 5. API de traduction | `main.py` (+ `pipeline.py`, `guard.py`) | FastAPI, testée |

**Important : aucune traduction ewondo/bulu n'a été inventée.** `memory.json` et `glossary.json` contiennent
les textes français et des cases vides (`status: "todo"`). Les traductions viennent du modèle (brouillons) puis
des locuteurs (validation). Le moteur n'utilise par défaut que les traductions `validated`.

**Non testé ici : le vrai modèle** (sans accès à Hugging Face). Le code qui l'appelle reprend l'exemple de la fiche
du modèle et est vérifié avec de faux modules `ctranslate2` / `transformers` (`tests/test_ct2_glue.py`).
Premier réflexe sur votre machine : `python scripts/check_directions.py --translate`.

## Les 8 étapes du cahier (pipeline.py)

1. chercher la phrase dans `memory.json` → 2. si elle existe, renvoyer la traduction humaine →
3-4. sinon, remplacer les termes du glossaire par des jetons `⟦G1⟧` → 5. envoyer le texte protégé à Marian →
6. réinsérer les termes validés → 7. vérifier jetons + rétro-traduction → 8. renvoyer la traduction **ou le texte français d'origine**.

Ajouts par rapport au cahier (voir « Corrections ») : garde-fou sensible, politique des avertissements, pivot anglais,
format de jetons configurable.

## Installation et premiers tests (dans cet ordre)

```bash
python -m venv .venv && source .venv/bin/activate        # Windows : .venv\Scripts\activate
pip install -r requirements.txt

# 1. Qu'y a-t-il VRAIMENT dans le modèle ? (ne rien supposer)
python scripts/check_directions.py                       # liste les directions et vérifie ewondo/bulu/anglais
python scripts/check_directions.py --translate           # télécharge et teste 3 phrases + rétro-traduction

# 2. Quel format de jeton le modèle conserve-t-il ?  (tâche 6)
python scripts/test_token_formats.py ewondo
export SAFINUM_TOKEN_FORMAT=square                       # ou celui qui gagne : native | square | brace | alnum

# 3. Brouillons du modèle → validation par un locuteur  (tâche 4)
python tools/fill_drafts.py ewondo                       # statut « draft » (jamais utilisé tant que non validé)
python tools/export_xlsx.py                              # → validation_traductions.xlsx
#    le locuteur corrige « traduction », met « statut » = validated et son nom dans « validé par »
python tools/import_xlsx.py validation_traductions.xlsx  # refuse : pas de nom, jetons changés, statut invalide
curl -X POST http://127.0.0.1:8000/reload                # ou redémarrer l'API

# 4. Calibrer la rétro-traduction (≥ 30 phrases validées)  (tâche 11)
python scripts/calibrate.py ewondo                       # suggère SAFINUM_MIN_BT

# 5. Lancer l'API
uvicorn main:app --host 127.0.0.1 --port 8000            # docs : http://127.0.0.1:8000/docs
```

Pour la démo, télécharger les modèles à l'avance (pas de réseau le jour J) :
`huggingface-cli download flagship-ai/cameroon-int8 --include "francais-ewondo/*" "ewondo-francais/*" --local-dir models`
puis `export SAFINUM_MODELS_DIR=$PWD/models`. `SAFINUM_WARMUP=1` charge les directions au démarrage.

## L'API

`POST /translate`
```json
{ "lang": "ewondo",
  "items": [ { "id": "sl1", "text": "Frais : ⟦M1⟧", "lang": "fr", "ctx": { "tag": "span", "step": 2, "alert": null } } ] }
```
Les `items` sont exactement les *payloads* du module 1. Réponse :
```json
{ "lang": "ewondo",
  "results": [ { "id": "sl1", "text": "…", "status": "ok", "source": "memory|memory_draft|glossary|mt|none",
                 "confidence": 0.93, "needs_review": false, "reasons": [], "back_translation": null } ] }
```
`status` : `ok` · `fallback` (texte d'origine renvoyé, voir `reasons`) · `passthrough` (rien à traduire) · `rejected` (donnée sensible reçue).
`GET /health` (directions disponibles, politique, compteurs) · `GET /languages` · `POST /reload`.

Brancher l'extension : `integration/background.js` + `integration/transport.js` + `integration/manifest.example.json`
(non testé dans Chrome ; le service worker évite les problèmes de CORS depuis la page https).

## Corrections apportées au cahier

1. **Collision de jetons.** Le module 1 utilise `⟦M1⟧ ⟦P1⟧ ⟦T1⟧ ⟦A1⟧ ⟦R1⟧ ⟦D1⟧ ⟦E1⟧ ⟦N1⟧ ⟦X1⟧`. Les jetons du glossaire
   utilisent la lettre **G** (`⟦G1⟧`), réservée. Tous les jetons doivent revenir intacts, une fois chacun, et ceux de
   Marian sont toujours résolus avant la réponse.
2. **Format de jeton.** `⟦ ⟧` n'est probablement pas dans le vocabulaire de Marian (caractère inconnu = jeton perdu). Le moteur
   convertit les jetons à l'entrée et à la sortie (`TokenCodec`) : on peut changer de format sans toucher au module 1. Par défaut
   `square` (`[[M1]]`), à confirmer par `test_token_formats.py`.
3. **Glossaire généré par le modèle.** Le cahier autorise le modèle à proposer les traductions du glossaire ; elles restent
   `draft` tant qu'une personne compétente ne les a pas validées. Un terme financier faux est un « défaut majeur » (critère 8).
4. **Avertissements de sécurité.** Un texte marqué `ctx.alert = warning|error` n'est **jamais** traduit automatiquement sans
   validation : mémoire validée ou repli en français (`SAFINUM_STRICT_ALERT=0` pour l'assouplir, déconseillé).
5. **Rétro-traduction.** Le modèle a appris sur des textes bibliques dans les deux sens : sa rétro-traduction est bruitée.
   Les seuils (`min_bt_score` 0.40, `min_bt_score_short` 0.60 pour moins de 3 mots) sont des valeurs de départ à calibrer.
   La rétro-traduction ne remplace pas la validation humaine : elle sert à refuser, pas à garantir.
6. **Textes en anglais** (le site a un bouton EN) : pas de traduction directe anglais → langue locale. On cherche d'abord
   la mémoire (`en`), sinon pivot anglais → français → mémoire. Une traduction automatique issue du pivot est refusée par
   défaut (`SAFINUM_ALLOW_PIVOT_MT=1` pour l'accepter, marquée « à relire »). Il faut renseigner `en` dans `memory.json`
   avec les vraies pages en mode EN, et confirmer le nom du dossier `english-francais` (`config.EN_TO_FR_PAIR`).
7. **Garde-fou côté serveur** (`guard.py`) : si un texte contient encore un montant, un téléphone, un compte, une référence ou
   un e-mail, il n'est ni traduit ni journalisé (`status: rejected`).
8. **Journal des phrases inédites** : les textes masqués qui n'ont pas de traduction validée sont notés dans `unseen.jsonl`
   pour être donnés aux locuteurs (jamais de donnée sensible dedans).

## Correspondance avec les 12 tâches

| N° | Tâche | Où |
|---|---|---|
| 1 | Étudier Cameroon-INT8 | `translator.py` (en-tête), `scripts/check_directions.py` |
| 2 | Installer et tester Marian | `CT2MarianBackend`, `check_directions.py --translate` |
| 3 | Mémoire de traduction | `memory.json`, `memory.py` |
| 4 | Glossaire français/ewondo | `glossary.json`, `tools/fill_drafts.py`, `tools/export_xlsx.py`, `tools/import_xlsx.py` |
| 5 | Remplacer les termes par des jetons | `Glossary.protect` |
| 6 | Tester les formats de jetons | `scripts/test_token_formats.py`, `TokenCodec` |
| 7 | Traduire les phrases inédites | `Translator`, `pipeline.py` |
| 8 | Réinsérer les termes validés | `Glossary.reinsert` |
| 9 | Vérifier les jetons | `Validator.static_checks` |
| 10 | Rétro-traduction | `Translator.back_translate`, `Validator.evaluate` |
| 11 | Détecter les traductions douteuses | règles de `validator.py`, `scripts/calibrate.py` |
| 12 | Retourner le texte original | repli de `pipeline.py` (texte masqué du module 1 → l'écran ne change pas) |

## Limites connues

* Qualité du modèle inconnue : entraîné sur des données bibliques d'après vos informations, aucun score publié. Les phrases
  financières hors mémoire peuvent être refusées souvent ; la parade est de **valider davantage de phrases** (mémoire), pas
  d'assouplir les seuils.
* Les phrases « anticipées » de `memory.json` (id `anticipe.*`, dont « Veuillez confirmer votre opération. ») n'ont pas été vues
  sur le site : à confirmer avec les vraies pages d'erreur et le protocole de test.
* La mémoire ne cherche que des correspondances exactes (insensibles à la casse, aux espaces et au point final) : une phrase
  proche mais différente n'est jamais renvoyée avec la traduction d'une autre (risque de contresens).
* Le glossaire ne contient que les noms, adjectifs et l'infinitif « confirmer » : les verbes conjugués sont laissés au modèle.
* Licence du modèle : **CC BY-NC 4.0** (usage non commercial). À déclarer dans la note technique ; tout usage commercial demande
  l'accord des titulaires.

## Tests

`python -m pytest tests -q` → 49 tests : mémoire, glossaire, jetons, validation, repli, sécurité, anglais, API (CORS inclus),
outils Excel, colle CTranslate2 et aller-retour avec le vrai `privacy.js` du module 1 (si `node` et `../safinum-module1` sont présents).
