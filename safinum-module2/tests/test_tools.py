import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from openpyxl import load_workbook

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def sandbox(tmp_path):
    dst = tmp_path / "m2"
    shutil.copytree(ROOT, dst, ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache", "*.xlsx", "unseen.jsonl"))
    return dst


def run(sandbox, script, *args):
    return subprocess.run([sys.executable, f"tools/{script}", *args], cwd=sandbox, capture_output=True, text=True)


def test_excel_roundtrip_validation_workflow(sandbox):
    r = run(sandbox, "export_xlsx.py", "val.xlsx")
    assert r.returncode == 0, r.stderr
    wb = load_workbook(sandbox / "val.xlsx")
    assert {"memoire_ewondo", "glossaire_ewondo"} == set(wb.sheetnames)
    ws = wb["memoire_ewondo"]
    rows = {ws.cell(r, 1).value: r for r in range(2, ws.max_row + 1)}

    # relecteur : une traduction valide, une sans nom, une qui perd un jeton, un statut invalide
    def fill(row, text, status, by):
        ws.cell(row, 4).value, ws.cell(row, 5).value, ws.cell(row, 6).value = text, status, by
    fill(rows["nav.continuer"], "TRAD-CONTINUER", "validated", "Marie K.")
    fill(rows["nav.retour"], "TRAD-RETOUR", "validated", "")
    fill(rows["anticipe.frais_mm"], "FRAIS sans jeton", "validated", "Marie K.")
    fill(rows["nav.modifier"], "TRAD-MODIFIER", "approuvé", "Marie K.")
    gs = wb["glossaire_ewondo"]
    grow = next(r for r in range(2, gs.max_row + 1) if gs.cell(r, 1).value == "solde")
    gs.cell(grow, 4).value, gs.cell(grow, 5).value, gs.cell(grow, 6).value = "nsolo", "validated", "Marie K."
    wb.save(sandbox / "val.xlsx")

    r = run(sandbox, "import_xlsx.py", "val.xlsx")
    assert r.returncode == 1                       # des refus ont eu lieu
    assert "« validé par » obligatoire" in r.stdout and "jetons ⟦…⟧ différents" in r.stdout and "statut invalide" in r.stdout
    mem = {e["id"]: e for e in json.loads((sandbox / "memory.json").read_text(encoding="utf-8"))["entries"]}
    assert mem["nav.continuer"]["translations"]["ewondo"]["status"] == "validated"
    assert mem["nav.continuer"]["translations"]["ewondo"]["validated_on"]
    # refusées → la traduction n'a PAS été remplacée (elle garde son statut et son texte d'avant)
    assert mem["nav.retour"]["translations"]["ewondo"]["text"] != "TRAD-RETOUR"
    assert mem["anticipe.frais_mm"]["translations"]["ewondo"]["text"] != "FRAIS sans jeton"
    assert mem["nav.modifier"]["translations"]["ewondo"]["status"] != "validated"
    glo = {t["id"]: t for t in json.loads((sandbox / "glossary.json").read_text(encoding="utf-8"))["terms"]}
    got = glo["solde"]["translations"]["ewondo"]
    assert (got["text"], got["status"], got["validated_by"]) == ("nsolo", "validated", "Marie K.")
    assert got["validated_on"]


def test_shipped_data_contains_no_validated_or_invented_translation():
    """Les données embarquées ne contiennent AUCUNE traduction validée par un humain.

    Des brouillons issus du modèle (status "draft", jamais utilisés par défaut)
    sont autorisés : c'est la sortie normale de tools/fill_drafts.py.
    """
    mem = json.loads((ROOT / "memory.json").read_text(encoding="utf-8"))
    glo = json.loads((ROOT / "glossary.json").read_text(encoding="utf-8"))
    for e in mem["entries"]:
        for lang, t in e["translations"].items():
            assert t["status"] in ("todo", "draft"), (e["id"], lang)
            assert t.get("validated_by") is None and t.get("validated_on") is None, (e["id"], lang)
    for t in glo["terms"]:
        if t["policy"] == "translate":
            for lang, v in t["translations"].items():
                assert v["status"] in ("todo", "draft"), (t["id"], lang)
                assert v.get("validated_by") is None and v.get("validated_on") is None, (t["id"], lang)
