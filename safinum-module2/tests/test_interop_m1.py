"""Interopérabilité avec le module 1 : on fait masquer le texte par le vrai privacy.js (Node),
traduire par le moteur (faux modèle), puis valider/restaurer par privacy.js."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from conftest import FakeBackend  # noqa: F401
from pipeline import Item

_ROOT = Path(__file__).resolve().parents[2]
M1 = _ROOT / "safinum-module1" / "privacy.js"
if not M1.exists():
    M1 = _ROOT / "Module1_safinum" / "privacy.js"
pytestmark = pytest.mark.skipif(not (shutil.which("node") and M1.exists()), reason="node ou module 1 absent")

JS_MASK = """
const p = require(process.argv[1]);
const r = p.mask(process.argv[2]);
console.log(JSON.stringify({masked: r.masked, vault: [...r.vault.entries()]}));
"""
JS_RESTORE = """
const p = require(process.argv[1]);
const d = JSON.parse(process.argv[2]);
const vault = new Map(d.vault);
console.log(JSON.stringify({ok: p.validate(d.masked, d.out, vault), text: p.restore(d.out, vault)}));
"""


def node(code, *args):
    r = subprocess.run(["node", "-e", code, str(M1), *args], capture_output=True, text=True, check=True)
    return json.loads(r.stdout)


@pytest.mark.parametrize("src, must_survive, must_not_leave", [
    ("Frais : 375 FCFA débités avant le 12/11/2026 pour la banque", ["375 FCFA", "12/11/2026"], ["375", "FCFA", "12/11"]),
    ("Le transfert de 25 000 FCFA vers +237 6 99 12 34 56 est prêt à partir", ["25 000 FCFA", "+237 6 99 12 34 56"], ["25 000", "FCFA", "6 99", "237"]),
])
def test_round_trip_with_module1_masking(env, src, must_survive, must_not_leave):
    pipe, backend, _ = env.build(token_format="square")
    m = node(JS_MASK, src)
    res = pipe.translate_batch("ewondo", [Item("x", m["masked"], "fr", {})])[0]
    assert res.status == "ok", res.reasons
    sent = " ".join(t for _, texts in backend.calls for t in texts)          # tout ce que le modèle a reçu
    for leak in must_not_leave:
        assert leak not in sent, f"{leak!r} a atteint le modèle"
    out = node(JS_RESTORE, json.dumps({"masked": m["masked"], "vault": m["vault"], "out": res.text}))
    assert out["ok"]["ok"] is True
    assert out["text"].startswith("[ew] ")
    for value in must_survive:
        assert value in out["text"], f"{value!r} perdu après restauration"


def test_fallback_text_is_restored_by_module1_to_the_exact_original(env):
    pipe, _, _ = env.build(mode="drop_tokens")
    src = "Vous allez envoyer 25 000 FCFA vers la banque"
    m = node(JS_MASK, src)
    res = pipe.translate_batch("ewondo", [Item("x", m["masked"], "fr", {})])[0]
    assert res.status == "fallback"
    out = node(JS_RESTORE, json.dumps({"masked": m["masked"], "vault": m["vault"], "out": res.text}))
    assert out["ok"]["ok"] is True and out["text"] == src      # l'écran reste identique
