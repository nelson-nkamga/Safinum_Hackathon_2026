"""Tâche 11 : calibrer les seuils de la rétro-traduction.

    python scripts/calibrate.py ewondo
Utilise les entrées VALIDÉES de la mémoire (phrase source + traduction humaine) :
 - compare la traduction automatique à la traduction humaine (chrF) → qualité réelle ;
 - calcule le score de rétro-traduction de la traduction AUTOMATIQUE et de la traduction HUMAINE.
Le seuil min_bt_score doit se situer entre les deux distributions : assez bas pour accepter
les bonnes traductions, assez haut pour refuser les mauvaises.
Plus il y a d'entrées validées, plus la calibration est fiable (viser au moins 30).
"""
from __future__ import annotations

import json
import statistics as st
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from config import Settings  # noqa: E402
from main import build_pipeline  # noqa: E402
from textutil import chrf, find_tokens  # noqa: E402


def main(lang: str) -> None:
    s = Settings()
    pipe = build_pipeline(s)
    tr = pipe.translator
    mem = json.loads((ROOT / "memory.json").read_text(encoding="utf-8"))
    pairs = [(e["fr"], e["translations"][lang]["text"]) for e in mem["entries"]
             if (e["translations"].get(lang) or {}).get("status") == "validated"]
    if len(pairs) < 5:
        sys.exit(f"seulement {len(pairs)} traductions validées : validez-en davantage avant de calibrer")
    srcs = [p[0] for p in pairs]
    if not tr.has_direction("fr", lang) or not tr.has_direction(lang, "fr"):
        sys.exit("direction indisponible : lancez scripts/download_model.py")
    mt = tr.translate_path("fr", lang, srcs)
    bt_mt = tr.translate_path(lang, "fr", [o.text for o in mt])
    bt_h = tr.translate_path(lang, "fr", [p[1] for p in pairs])
    q = [chrf(o.text, h) for o, (_, h) in zip(mt, pairs)]
    s_mt = [chrf(b.text, src) for b, src in zip(bt_mt, srcs)]
    s_h = [chrf(b.text, src) for b, src in zip(bt_h, srcs)]
    tok_ok = sum(find_tokens(o.text) == find_tokens(src) for o, src in zip(mt, srcs)) / len(srcs)
    f = lambda xs: f"moy {st.mean(xs):.2f}  min {min(xs):.2f}  méd {st.median(xs):.2f}"  # noqa: E731
    print(f"{len(pairs)} phrases validées ({lang})")
    print(f"qualité MT vs humain (chrF)              : {f(q)}")
    print(f"rétro-traduction de la traduction HUMAINE : {f(s_h)}")
    print(f"rétro-traduction de la traduction AUTO    : {f(s_mt)}")
    print(f"jetons conservés par la MT                : {tok_ok:.0%}")
    print(f"\nSuggestion : min_bt_score ≈ {max(0.2, st.mean(s_h) - st.pstdev(s_h)):.2f} "
          f"(export SAFINUM_MIN_BT=...). Si la qualité MT est basse, ne pas assouplir : "
          f"compléter la mémoire validée à la place.")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "ewondo")
