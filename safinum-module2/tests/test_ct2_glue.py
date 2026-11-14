"""Le vrai modèle n'est pas téléchargeable ici : on vérifie la colle autour de CTranslate2
avec de faux modules `ctranslate2` et `transformers` qui reproduisent l'API utilisée dans la fiche du modèle."""
import sys
import types

from config import Settings
from translator import CT2MarianBackend, Translator


class _Res:
    def __init__(self, tokens, score):
        self.hypotheses, self.scores = [tokens], [score]


def _install_fakes(monkeypatch, record):
    ct2 = types.ModuleType("ctranslate2")

    class FakeCT2Translator:
        def __init__(self, path, device, compute_type):
            record["init"] = (path, device, compute_type)

        def translate_batch(self, sources, **kw):
            record["batch"] = (sources, kw)
            return [_Res(["▁ew"] + s[:-1], -0.3) for s in sources]   # retire </s>, ajoute un jeton

    ct2.Translator = FakeCT2Translator
    tf = types.ModuleType("transformers")

    class FakeTok:
        def encode(self, text):
            return list(range(len(text.split()) + 1))
        def convert_ids_to_tokens(self, ids):
            return [f"t{i}" for i in ids[:-1]] + ["</s>"]
        def convert_tokens_to_ids(self, toks):
            return list(range(len(toks)))
        def decode(self, ids, skip_special_tokens=True):
            record["decoded"] = (ids, skip_special_tokens)
            return "  sortie decodée  "

    class MarianTokenizer:
        @staticmethod
        def from_pretrained(path):
            record["tok_path"] = path
            return FakeTok()

    tf.MarianTokenizer = MarianTokenizer
    monkeypatch.setitem(sys.modules, "ctranslate2", ct2)
    monkeypatch.setitem(sys.modules, "transformers", tf)


def test_backend_loads_local_pair_once_and_passes_decoding_options(tmp_path, monkeypatch):
    (tmp_path / "francais-ewondo").mkdir()
    (tmp_path / "francais-ewondo" / "model.bin").write_bytes(b"x")
    rec = {}
    _install_fakes(monkeypatch, rec)
    s = Settings(models_dir=str(tmp_path), beam_size=5, max_decoding_length=99)
    b = CT2MarianBackend(s)
    assert b.has_pair("francais-ewondo") and not b.has_pair("ewondo-francais")
    out = b.translate("francais-ewondo", ["bonjour le monde", "merci"])
    assert [o.text for o in out] == ["sortie decodée", "sortie decodée"] and out[0].score == -0.3
    assert rec["init"] == (str(tmp_path / "francais-ewondo"), "cpu", "int8")
    assert rec["tok_path"] == str(tmp_path / "francais-ewondo")
    sources, kw = rec["batch"]
    assert sources[0][-1] == "</s>"                                  # comme dans l'exemple de la fiche
    assert kw["beam_size"] == 5 and kw["max_decoding_length"] == 99 and kw["return_scores"] is True
    assert kw["no_repeat_ngram_size"] == 3
    assert rec["decoded"][1] is True                                 # skip_special_tokens
    rec.clear()
    b.translate("francais-ewondo", ["encore"])                       # 2e appel : pas de rechargement
    assert "init" not in rec


def test_translator_uses_token_format_around_backend(tmp_path, monkeypatch):
    (tmp_path / "francais-ewondo").mkdir()
    (tmp_path / "francais-ewondo" / "model.bin").write_bytes(b"x")
    seen = {}

    class Spy(CT2MarianBackend):
        def translate(self, pair, texts):
            seen["texts"] = texts
            from translator import MTOutput
            return [MTOutput(t.replace("Frais", "FRAIS-EW")) for t in texts]

    s = Settings(models_dir=str(tmp_path), token_format="square")
    tr = Translator(Spy(s), s)
    out = tr.translate("ewondo", ["Frais : ⟦M1⟧. Merci ⟦N1⟧"])
    assert seen["texts"] == ["Frais : [[M1]].", "Merci [[N1]]"]       # jetons ASCII et phrase par phrase
    assert out[0].text == "FRAIS-EW : ⟦M1⟧. Merci ⟦N1⟧"
