"""Exporte memory.json et glossary.json vers un classeur Excel pour les locuteurs.

    python tools/export_xlsx.py            # crée validation_traductions.xlsx
Colonnes à remplir/corriger par le relecteur : « traduction » et « statut »
(todo / draft / validated / rejected), puis « validé par ».
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.worksheet.datavalidation import DataValidation

ROOT = Path(__file__).resolve().parent.parent
LANGS = ["ewondo"]
STATUS = "todo,draft,validated,rejected"


def _sheet(wb, title, headers):
    ws = wb.create_sheet(title)
    ws.append(headers)
    for c in ws[1]:
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor="2D1B69")
    ws.freeze_panes = "A2"
    return ws


def _finish(ws, status_col: str, widths) -> None:
    dv = DataValidation(type="list", formula1=f'"{STATUS}"', allow_blank=False)
    ws.add_data_validation(dv)
    dv.add(f"{status_col}2:{status_col}{max(ws.max_row, 2)}")
    for col, w in zip("ABCDEFG", widths):
        ws.column_dimensions[col].width = w
    for row in ws.iter_rows(min_row=2):
        for c in row:
            c.alignment = Alignment(wrap_text=True, vertical="top")


def main(out: Path) -> None:
    mem = json.loads((ROOT / "memory.json").read_text(encoding="utf-8"))
    glo = json.loads((ROOT / "glossary.json").read_text(encoding="utf-8"))
    wb = Workbook()
    wb.remove(wb.active)
    for lang in LANGS:
        ws = _sheet(wb, f"memoire_{lang}", ["id", "français (source, garder les jetons ⟦…⟧)", "origine", "traduction", "statut", "validé par"])
        for e in mem["entries"]:
            t = (e.get("translations") or {}).get(lang, {})
            ws.append([e["id"], e["fr"], e.get("origin", ""), t.get("text") or "", t.get("status", "todo"), t.get("validated_by") or ""])
        _finish(ws, "E", (28, 60, 12, 60, 12, 18))
    for lang in LANGS:
        ws = _sheet(wb, f"glossaire_{lang}", ["id", "français", "politique", "traduction", "statut", "validé par", "notes"])
        for t in glo["terms"]:
            if t.get("policy") == "keep":
                continue
            tr = (t.get("translations") or {}).get(lang, {})
            ws.append([t["id"], " / ".join(t["fr"]), t["policy"], tr.get("text") or "", tr.get("status", "todo"), tr.get("validated_by") or "", t.get("notes", "")])
        _finish(ws, "E", (22, 28, 12, 40, 12, 18, 40))
    wb.save(out)
    print("écrit :", out)


if __name__ == "__main__":
    main(Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "validation_traductions.xlsx")
