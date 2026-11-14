"""Télécharge uniquement les directions ewondo utiles (≈ 310 Mo, pas les 119 langues).

    python scripts/download_model.py                 # français ↔ ewondo + pivot anglais
    python scripts/download_model.py --lang ewondo --dest models
    python scripts/download_model.py --list          # affiche les dossiers attendus

Le dossier `models/` est détecté automatiquement par config.py :
aucun export SAFINUM_MODELS_DIR n'est nécessaire s'il se trouve à la racine
du module 2.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from config import LANGUAGES, all_model_pairs, direction_path  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--lang", default="ewondo", choices=list(LANGUAGES))
    ap.add_argument("--dest", default=str(ROOT / "models"))
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--repo", default="flagship-ai/cameroon-int8")
    args = ap.parse_args()

    needed: list[str] = []
    for source, target in (("fr", args.lang), (args.lang, "fr"),
                           ("en", args.lang), (args.lang, "en")):
        needed.extend(direction_path(source, target))
    needed = list(dict.fromkeys(needed))
    if args.list:
        print("\n".join(needed))
        return

    from huggingface_hub import snapshot_download
    dest = Path(args.dest).resolve()
    dest.mkdir(parents=True, exist_ok=True)
    print(f"Dépôt   : {args.repo}")
    print(f"Dossier : {dest}")
    print("Directions :", ", ".join(needed))
    snapshot_download(
        repo_id=args.repo,
        allow_patterns=[f"{p}/*" for p in needed],
        local_dir=str(dest),
    )
    missing = [p for p in needed if not (dest / p / "model.bin").exists()]
    if missing:
        sys.exit("Téléchargement incomplet : " + ", ".join(missing))
    total = sum((dest / p / "model.bin").stat().st_size for p in needed)
    print(f"OK — {len(needed)} directions, {total / 1e6:.0f} Mo de modèles.")


if __name__ == "__main__":
    main()
