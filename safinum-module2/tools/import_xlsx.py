"""Réimporte les corrections des locuteurs (Excel) dans memory.json et glossary.json.

    python tools/import_xlsx.py validation_traductions.xlsx
Règles de sécurité :
 - une traduction « validated » doit avoir un nom dans « validé par » ;
 - une traduction de la mémoire doit contenir exactement les mêmes jetons ⟦…⟧ que la source ;
 - tout le reste est refusé et listé.
Après l'import : POST /reload (ou redémarrer l'API).
"""
from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path

from openpyxl import load_workbook

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from textutil import find_tokens  # noqa: E402

OK_STATUS = {"todo", "draft", "validated", "rejected"}


def main(xlsx: Path) -> int:
    mem_path, glo_path = ROOT / "memory.json", ROOT / "glossary.json"
    mem = json.loads(mem_path.read_text(encoding="utf-8"))
    glo = json.loads(glo_path.read_text(encoding="utf-8"))
    entries = {e["id"]: e for e in mem["entries"]}
    terms = {t["id"]: t for t in glo["terms"]}
    wb = load_workbook(xlsx, data_only=True)
    today, problems, changed = dt.date.today().isoformat(), [], 0

    for ws in wb.worksheets:
        kind, _, lang = ws.title.partition("_")
        if kind not in {"memoire", "glossaire"}:
            continue
        for row in ws.iter_rows(min_row=2, values_only=True):
            rid = row[0]
            text, status, by = (row[3] or "").strip(), (row[4] or "todo").strip(), (row[5] or "").strip()
            target = (entries if kind == "memoire" else terms).get(rid)
            if target is None:
                problems.append(f"{ws.title}/{rid} : id inconnu")
                continue
            if status not in OK_STATUS:
                problems.append(f"{ws.title}/{rid} : statut invalide {status!r}")
                continue
            if status in {"draft", "validated"} and not text:
                problems.append(f"{ws.title}/{rid} : statut {status} sans traduction")
                continue
            if status == "validated" and not by:
                problems.append(f"{ws.title}/{rid} : « validé par » obligatoire")
                continue
            if kind == "memoire" and text and find_tokens(text) != find_tokens(target["fr"]):
                problems.append(f"{ws.title}/{rid} : jetons ⟦…⟧ différents de la source")
                continue
            rec = target.setdefault("translations", {}).setdefault(lang, {})
            new = {"text": text or None, "status": status, "validated_by": by or None,
                   "validated_on": today if status == "validated" else rec.get("validated_on")}
            if any(rec.get(k) != v for k, v in new.items()):
                rec.update(new)
                changed += 1

    mem_path.write_text(json.dumps(mem, ensure_ascii=False, indent=1), encoding="utf-8")
    glo_path.write_text(json.dumps(glo, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{changed} traductions mises à jour")
    for p in problems:
        print("REFUSÉ :", p)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1])))
