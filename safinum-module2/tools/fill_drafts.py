"""Demande au modèle un BROUILLON pour chaque entrée « todo » (mémoire et glossaire).

    python tools/fill_drafts.py ewondo       # nécessite le modèle (voir README)

Les brouillons reçoivent le statut « draft » : ils ne sont PAS utilisés par défaut tant
qu'un locuteur ne les a pas validés. La rétro-traduction est ajoutée en commentaire pour
aider le relecteur. Les brouillons qui perdent un jeton, changent un chiffre ou sont
manifestement vides / copiés sont ignorés.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from config import LANGUAGES, Settings  # noqa: E402
from main import build_pipeline  # noqa: E402
from textutil import chrf, find_tokens  # noqa: E402


def main(lang: str) -> None:
    if lang not in LANGUAGES:
        sys.exit(f"langue inconnue : {lang} (choix : {', '.join(LANGUAGES)})")
    pipe = build_pipeline(Settings())
    tr = pipe.translator
    if not tr.has_direction("fr", lang) or not tr.has_direction(lang, "fr"):
        sys.exit("direction indisponible : lancez scripts/download_model.py et vérifiez SAFINUM_MODELS_DIR")

    mem_path, glo_path = ROOT / "memory.json", ROOT / "glossary.json"
    mem = json.loads(mem_path.read_text(encoding="utf-8"))
    glo = json.loads(glo_path.read_text(encoding="utf-8"))

    def todo(rec):
        return (rec.get("translations", {}).get(lang) or {}).get("status", "todo") == "todo"

    work = [(e, e["fr"]) for e in mem["entries"] if todo(e)]
    work += [(t, t["fr"][0]) for t in glo["terms"] if t.get("policy") == "translate" and todo(t)]
    print(f"{len(work)} éléments à brouillonner en {lang}")
    written = skipped = 0
    for i in range(0, len(work), 16):
        chunk = work[i:i + 16]
        srcs = [src for _, src in chunk]
        outs = tr.translate_path("fr", lang, srcs)
        backs = tr.translate_path(lang, "fr", [o.text for o in outs])
        for (obj, src), o, b in zip(chunk, outs, backs):
            static = pipe.validator.static_checks(src, o.text)
            if static or find_tokens(o.text) != find_tokens(src):
                skipped += 1
                continue
            rec = obj["translations"].setdefault(lang, {})
            rec.update({
                "text": o.text,
                "status": "draft",
                "validated_by": None,
                "validated_on": None,
                "draft_back_translation": b.text,
                "draft_quality": round(chrf(b.text, src), 3),
            })
            written += 1
    mem_path.write_text(json.dumps(mem, ensure_ascii=False, indent=1), encoding="utf-8")
    glo_path.write_text(json.dumps(glo, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{written} brouillons écrits, {skipped} ignorés (jetons/chiffres/copie)")
    print("terminé : exportez avec tools/export_xlsx.py pour la relecture par un locuteur")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "ewondo")
