import pytest

from config import Settings
from textutil import TokenCodec, chrf, digit_runs, find_tokens, has_letters, normalize_key
from translator import Translator
from validator import Validator
from conftest import FakeBackend


@pytest.mark.parametrize("fmt", list(TokenCodec.FORMATS))
def test_codec_roundtrip_and_tolerance(fmt):
    c = TokenCodec(fmt)
    text = "Frais : ⟦M1⟧ vers ⟦N2⟧ via ⟦G1⟧"
    enc = c.encode(text)
    assert (fmt == "native") or "⟦" not in enc
    assert c.decode(enc) == text


def test_codec_tolerates_spaces_inside_tokens():
    assert TokenCodec("square").decode("a [[ M1 ]] b") == "a ⟦M1⟧ b"
    with pytest.raises(ValueError):
        TokenCodec("nope")


def test_normalize_key_and_helpers():
    assert normalize_key("  Frais   :  ⟦M1⟧. ") == normalize_key("frais : ⟦m1⟧")
    assert normalize_key("L’opération") == normalize_key("L'opération")
    assert not has_letters("⟦G1⟧ ⟦M2⟧") and has_letters("⟦G1⟧ de ⟦M2⟧")
    assert dict(digit_runs("Étape 2 sur 15 ⟦M1⟧")) == {"2": 1, "15": 1}
    assert chrf("solde disponible", "Solde disponible") == 1.0
    assert chrf("abc", "xyz") < 0.2


def _validator(**kw):
    s = Settings(**kw)
    return Validator(s, Translator(FakeBackend(), s)), s


def test_validator_static_rules():
    v, _ = _validator()
    assert v.static_checks("Frais : ⟦M1⟧", "Frais ew : ⟦M1⟧") == []
    assert v.static_checks("Frais : ⟦M1⟧", "Frais ew")[0].startswith("token_missing")
    assert v.static_checks("Frais : ⟦M1⟧", "Frais ⟦M1⟧ ⟦M1⟧")[0].startswith("token_duplicated")
    assert v.static_checks("Frais : ⟦M1⟧", "Frais ⟦M1⟧ ⟦M9⟧")[0].startswith("token_extra")
    assert "digits_changed" in v.static_checks("Étape 2", "Étape 3")
    assert v.static_checks("x y z", "") == ["empty_output"]
    assert "unknown_symbols" in v.static_checks("Bonjour tout le monde", "ab <unk> cd")
    assert "repetition" in v.static_checks("Bonjour tout le monde", "ab ab ab ab ab cd")
    assert any(r.startswith("length_ratio") for r in v.static_checks("Veuillez confirmer votre opération", "ab"))


def test_validator_short_text_uses_stricter_threshold():
    v, s = _validator()
    assert s.min_bt_score_short > s.min_bt_score
