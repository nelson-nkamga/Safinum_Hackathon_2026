import json
import os
import re
import shutil
import sys
from pathlib import Path

os.environ.setdefault("SAFINUM_NO_AUTOSTART", "1")
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pytest  # noqa: E402

from config import Settings  # noqa: E402
from main import build_pipeline  # noqa: E402
from translator import MTBackend, MTOutput  # noqa: E402

PREFIX = {"francais-ewondo": "[ew] "}
ALL_PAIRS = {"francais-ewondo", "ewondo-francais", "english-francais", "francais-english"}
_TOKENS = re.compile(r"\[\[[A-Z]\d+\]\]|\{\{?[A-Z]\d+\}?\}|Q[A-Z]\d+Q|NUM-?\d{4,6}Z?|⟦[A-Z]\d+⟧")


class FakeBackend(MTBackend):
    """Faux moteur : préfixe le texte à l'aller, le retire au retour. Modes de panne :
    drop_tokens, garbage, bad_back, copy, digits."""

    def __init__(self, pairs=None, mode="ok", en_fr=None, fr_en=None):
        self.pairs = set(ALL_PAIRS if pairs is None else pairs)
        self.mode = mode
        self.en_fr = en_fr or {}
        self.fr_en = fr_en or {}
        self.calls = []

    def has_pair(self, pair):
        return pair in self.pairs

    def translate(self, pair, texts):
        self.calls.append((pair, list(texts)))
        out = []
        for t in texts:
            if pair == "english-francais":
                out.append(MTOutput(self.en_fr.get(t, t), -0.1))
            elif pair == "francais-english":
                out.append(MTOutput(self.fr_en.get(t, "EN " + t), -0.1))
            elif pair in PREFIX:
                m = self.mode
                if m == "garbage":
                    r = "zzz zzz zzz zzz zzz zzz"
                elif m == "copy":
                    r = t
                elif m == "digits":
                    r = PREFIX[pair] + t.replace("2", "3")
                elif m == "drop_tokens":
                    r = PREFIX[pair] + _TOKENS.sub("", t)
                elif m == "drop_square":
                    r = PREFIX[pair] + re.sub(r"\[\[[A-Z]\d+\]\]", "", t)
                elif t.startswith("[fr] "):
                    r = t[len("[fr] "):]         # rétro-traduction : retour vers l'ewondo
                else:
                    r = PREFIX[pair] + t
                out.append(MTOutput(r, -0.2))
            else:   # ewondo → français
                if self.mode == "bad_back":
                    r = "texte totalement différent sans rapport"
                elif t.startswith("[ew] "):
                    r = t[len("[ew] "):]          # rétro-traduction du texte déjà traduit
                else:
                    r = "[fr] " + t              # traduction directe : jamais une copie
                out.append(MTOutput(r, -0.2))
        return out


def edit_memory(path, entry_id, lang, text, status="validated"):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    for e in data["entries"]:
        if e["id"] == entry_id:
            e["translations"][lang].update({"text": text, "status": status, "validated_by": "test"})
            break
    else:
        raise KeyError(entry_id)
    Path(path).write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def edit_glossary(path, term_id, lang, text, status="validated"):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    for t in data["terms"]:
        if t["id"] == term_id:
            t["translations"][lang].update({"text": text, "status": status, "validated_by": "test"})
            break
    else:
        raise KeyError(term_id)
    Path(path).write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


@pytest.fixture
def env(tmp_path):
    shutil.copy(ROOT / "memory.json", tmp_path / "memory.json")
    shutil.copy(ROOT / "glossary.json", tmp_path / "glossary.json")

    class Env:
        dir = tmp_path
        memory = tmp_path / "memory.json"
        glossary = tmp_path / "glossary.json"
        unseen = tmp_path / "unseen.jsonl"

        def build(self, mode="ok", pairs=None, en_fr=None, fr_en=None, **kw):
            s = Settings(memory_path=self.memory, glossary_path=self.glossary, unseen_log=self.unseen, **kw)
            backend = FakeBackend(pairs=pairs, mode=mode, en_fr=en_fr, fr_en=fr_en)
            pipe = build_pipeline(s, backend)
            return pipe, backend, s

    return Env()
