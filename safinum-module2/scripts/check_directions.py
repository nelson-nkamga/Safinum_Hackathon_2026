"""Tâches 1-2 : vérifier ce que le dépôt contient VRAIMENT, puis tester le modèle réel.

    python scripts/check_directions.py                 # liste les directions disponibles
    python scripts/check_directions.py --translate     # traduit et rétro-traduit des phrases réelles

La seule langue activée est l'ewondo. Les directions testées sont :
français → ewondo, ewondo → français, anglais → ewondo, ewondo → anglais.
Ne rien supposer : la fiche du modèle ne publie aucun score de qualité. Les
résultats doivent être relus par un locuteur ewondo.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from config import LANGUAGES, Settings, all_model_pairs, direction_path  # noqa: E402

FR_SAMPLES = [
    "Solde disponible",
    "Veuillez confirmer votre opération.",
    "Vérifiez toujours le nom et le numéro du bénéficiaire avant de confirmer un transfert.",
]
EN_SAMPLES = [
    "Available balance",
    "Please confirm your transaction.",
    "Always check the recipient name and number before confirming a transfer.",
]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--translate", action="store_true")
    ap.add_argument("--lang", default="ewondo", choices=list(LANGUAGES))
    args = ap.parse_args()
    s = Settings()

    if s.models_dir:
        pairs = sorted(p.name for p in Path(s.models_dir).iterdir() if (p / "model.bin").exists())
    else:
        from huggingface_hub import list_repo_files
        pairs = sorted({f.split("/")[0] for f in list_repo_files(s.hf_repo) if f.endswith("/model.bin")})
    print(f"{len(pairs)} directions dans {s.models_dir or s.hf_repo}")
    wanted = all_model_pairs()
    for w in wanted:
        print(f"  {'OK ' if w in pairs else 'ABSENT'}  {w}")
    if s.models_dir is None:
        print("\nAucun modèle local : lancez  python scripts/download_model.py --lang ewondo")

    if args.translate:
        from translator import CT2MarianBackend, Translator
        backend = CT2MarianBackend(s)
        tr = Translator(backend, s)
        plans = [
            ("fr", args.lang, FR_SAMPLES),
            (args.lang, "fr", None),
            ("en", args.lang, EN_SAMPLES),
            (args.lang, "en", None),
        ]
        for source, target, samples in plans:
            if not tr.has_direction(source, target):
                print(f"\n[{source} → {target}] direction incomplète, test ignoré")
                continue
            if samples is None:
                # phrase ewondo produite par le modèle à l'aller, puis retour
                fwd0 = tr.translate_path("fr", args.lang, [FR_SAMPLES[0]])[0]
                samples = [fwd0.text]
            fwd = tr.translate_path(source, target, samples)
            back = tr.translate_path(target, source, [o.text for o in fwd])
            print(f"\n=== {source} → {target} ===")
            for src, f, b in zip(samples, fwd, back):
                print(f"{source.upper():7s}: {src}\n{target.upper():7s}: {f.text}   (score {f.score})\nRT     : {b.text}\n")

        print("Directions chargées :", [p.name for p in Path(s.models_dir).iterdir()
                                         if (p / "model.bin").exists()] if s.models_dir else "dépôt distant")


if __name__ == "__main__":
    main()
