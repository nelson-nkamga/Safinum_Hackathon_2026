#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# SAFINUM — lancement tout-en-un
#
#   ./start.sh               lance tout (API + page de test) et affiche la suite
#   ./start.sh --production  force le mode production (traductions validées uniquement)
#   ./start.sh --demo        force le mode démonstration (brouillons « à relire »)
#   ./start.sh --tests       exécute les tests automatiques (57 tests + chaîne e2e)
#   ./start.sh --stop        arrête API et serveur de démonstration
#
# Le script est IDEMPOTENT : le relancer ne casse rien (il remplace l'instance en cours).
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
M2="$ROOT/safinum-module2"
EXT="$ROOT/safinum-extension-react/safinum-react-release"
PORT_API=8000
PORT_DEMO=8080
LOG_API=/tmp/safinum-api.log
LOG_DEMO=/tmp/safinum-demo.log

say()  { printf '\033[1;35m[safinum]\033[0m %s\n' "$*"; }
ok()   { printf '\033[1;32m  ✔\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m  ⚠\033[0m %s\n' "$*"; }
die()  { printf '\033[1;31m  ✘ %s\033[0m\n' "$*"; exit 1; }

MODE=auto
for arg in "$@"; do
  case "$arg" in
    --demo)       MODE=demo ;;
    --production) MODE=prod ;;
    --stop)
      pkill -f "uvicorn main:app" 2>/dev/null && warn "API arrêtée" || say "aucune API en cours"
      pkill -f "http.server $PORT_DEMO" 2>/dev/null && warn "serveur de démonstration arrêté" || true
      exit 0 ;;
    --tests) MODE=tests ;;
    *) say "usage : ./start.sh [--demo|--production|--tests|--stop]"; exit 0 ;;
  esac
done

# ── 0. Python ────────────────────────────────────────────────────────────────
command -v python3 >/dev/null 2>&1 || die "python3 introuvable — installez Python 3.11 ou plus récent"
VMAJ=$(python3 -c 'import sys; print("%d%02d" % sys.version_info[:2])')
[ "$VMAJ" -ge 311 ] || die "Python 3.11+ requis (trouvé : $(python3 -V))"
say "Python $(python3 -V | cut -d' ' -f2) détecté"

# ── 1. Environnement virtuel (créé une seule fois) ───────────────────────────
if [ ! -x "$M2/.venv/bin/python" ]; then
  say "Création de l'environnement Python (une seule fois, ~10 s)…"
  python3 -m venv "$M2/.venv" || die "échec de création du venv (paquet python3-venv requis)"
fi
PY="$M2/.venv/bin/python"

# ── 2. Dépendances (installées une seule fois) ───────────────────────────────
if ! "$PY" -c "import ctranslate2, fastapi, uvicorn, openpyxl" >/dev/null 2>&1; then
  say "Installation des dépendances (une seule fois, ~2 min)…"
  "$PY" -m pip install --quiet --upgrade pip
  "$PY" -m pip install --quiet -r "$M2/requirements.txt" || die "échec d'installation — voir la sortie ci-dessus"
fi
ok "Dépendances Python prêtes"

# ── 3. Modèles Marian ────────────────────────────────────────────────────────
for pair in francais-ewondo ewondo-francais english-francais francais-english; do
  [ -f "$M2/models/$pair/model.bin" ] || die "modèle manquant : models/$pair — voir README §Dépannage (téléchargement)"
done
ok "Modèles Marian présents (4 directions)"

# ── 4. Mode : production si une traduction validée existe, sinon démonstration
if [ "$MODE" = "auto" ]; then
  DRAFT=$("$PY" -c '
import json, sys
d = json.load(open(sys.argv[1], encoding="utf-8"))
n = sum(1 for e in d.get("entries", []) if ((e.get("translations") or {}).get("ewondo") or {}).get("status") == "validated")
print("1" if n == 0 else "0")' "$M2/memory.json")
elif [ "$MODE" = "demo" ]; then DRAFT=1; else DRAFT=0; fi

# ── 5. Arrêter l'instance précédente ────────────────────────────────────────
pkill -f "uvicorn main:app" 2>/dev/null && warn "ancienne API arrêtée" || true
sleep 1

# ── 6. Démarrer l'API ────────────────────────────────────────────────────────
say "Démarrage de l'API et chargement des modèles (~20-30 s, un appel du navigateur peut prendre jusqu'à 90 s au 1er appel)…"
if [ "$DRAFT" = "1" ]; then
  warn "aucune traduction validée par un locuteur → mode DÉMONSTRATION (brouillons du modèle, marqués « à relire »)"
  ( cd "$M2" && SAFINUM_WARMUP=1 SAFINUM_ALLOW_DRAFT_MEMORY=1 setsid nohup "$PY" -m uvicorn main:app --host 127.0.0.1 --port "$PORT_API" > "$LOG_API" 2>&1 < /dev/null & )
else
  ok "mode PRODUCTION (seules les traductions validées s'affichent)"
  ( cd "$M2" && SAFINUM_WARMUP=1 setsid nohup "$PY" -m uvicorn main:app --host 127.0.0.1 --port "$PORT_API" > "$LOG_API" 2>&1 < /dev/null & )
fi

# ── 7. Attendre que l'API réponde ───────────────────────────────────────────
READY=0
for _ in $(seq 1 60); do
  if curl -sf "http://127.0.0.1:$PORT_API/health" >/dev/null 2>&1; then READY=1; break; fi
  sleep 2
done
[ "$READY" = "1" ] || { warn "l'API n'a pas répondu — journal : $LOG_API"; tail -5 "$LOG_API" || true; exit 1; }
ok "API prête : http://127.0.0.1:$PORT_API  (documentation interactive : /docs)"

# ── 8. Page de test locale ──────────────────────────────────────────────────
if curl -sf "http://127.0.0.1:$PORT_DEMO/demo/live-test.html" -o /dev/null 2>/dev/null; then
  ok "Page de test déjà servie : http://127.0.0.1:$PORT_DEMO/demo/live-test.html"
else
  ( setsid nohup python3 -m http.server "$PORT_DEMO" --bind 127.0.0.1 --directory "$EXT" > "$LOG_DEMO" 2>&1 < /dev/null & )
  sleep 1
  curl -sf "http://127.0.0.1:$PORT_DEMO/demo/live-test.html" -o /dev/null 2>/dev/null \
    && ok "Page de test servie : http://127.0.0.1:$PORT_DEMO/demo/live-test.html" \
    || warn "serveur de démonstration non démarré — journal : $LOG_DEMO"
fi

# ── 9. Tests (option --tests) ───────────────────────────────────────────────
if [ "$MODE" = "tests" ]; then
  say "Tests du backend (57 attendus)…"
  ( cd "$M2" && "$PY" -m pytest tests -q ) || die "des tests échouent"
  ok "Tests backend"
  command -v node >/dev/null 2>&1 && {
    say "Chaîne de bout en bout (masquage → API → restauration)…"
    ( cd "$M2" && node integration/e2e_node_test.js > /dev/null ) && ok "Chaîne e2e sans fuite" || die "chaîne e2e en échec"
  }
fi

# ── 10. La suite, sans réfléchir ────────────────────────────────────────────
cat <<'FIN'

──────────────────────────────────────────────────────────────────────────────
  ✔ LANCEMENT TERMINÉ — la suite se passe dans Chrome :

  1. Ouvrir :  chrome://extensions
  2. Activer   « Mode développeur » (interrupteur en haut à droite)
  3. Cliquer   « Charger l'extension non empaquetée »
  4. Choisir le dossier :  safinum-extension-react/safinum-react-release/dist
  5. Ouvrir le site de test :  https://safinum.cm/hackathon-test
     (ou, sans le site :  http://127.0.0.1:8080/demo/live-test.html  → bouton « Traduire (ewondo) »)
  6. Cliquer l'icône SAFINUM dans la barre d'extensions
  7. Choisir   « Ewondo »  puis activer la traduction

  Détails et dépannage :  README.md  (racine du projet)
  Note technique :        NOTE_TECHNIQUE.pdf
──────────────────────────────────────────────────────────────────────────────
FIN
