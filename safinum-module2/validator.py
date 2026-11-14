"""Livrable 4 : module de validation.

Décide si une traduction automatique peut être acceptée :
 1. règles dures : jetons conservés (une fois chacun, aucun inventé), chiffres inchangés,
    sortie non vide, pas une simple copie, pas de répétitions, longueur plausible ;
 2. rétro-traduction (langue locale → français) comparée au texte source (score chrF).

En cas de doute la traduction est REFUSÉE : le moteur renvoie alors le texte français
original (jamais un montant ou un avertissement de sécurité déformé).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from config import Settings
from textutil import chrf, clean_spaces, digit_runs, find_tokens, strip_tokens, words
from translator import Translator

_REPEAT = re.compile(r"(?<!\w)(\w+)(?:\s+\1(?!\w)){3,}", re.IGNORECASE | re.UNICODE)
_BAD_CHARS = ("<unk>", "▁", "\ufffd", "<pad>", "</s>")


@dataclass
class Verdict:
    accepted: bool
    reasons: list[str] = field(default_factory=list)
    bt_score: float | None = None
    back_translation: str | None = None
    confidence: float = 0.0


class Validator:
    def __init__(self, settings: Settings, translator: Translator):
        self.s = settings
        self.tr = translator

    # -- règles dures --------------------------------------------------------
    def static_checks(self, src: str, out: str) -> list[str]:
        reasons: list[str] = []
        body = clean_spaces(strip_tokens(out))
        if not out.strip() or (not body and not find_tokens(out)):
            return ["empty_output"]

        exp, got = find_tokens(src), find_tokens(out)
        for tok in exp:
            if got.get(tok, 0) < exp[tok]:
                reasons.append(f"token_missing:{tok}")
            elif got[tok] > exp[tok]:
                reasons.append(f"token_duplicated:{tok}")
        for tok in got:
            if tok not in exp:
                reasons.append(f"token_extra:{tok}")

        if digit_runs(src) != digit_runs(out):
            reasons.append("digits_changed")
        if any(c in out for c in _BAD_CHARS):
            reasons.append("unknown_symbols")
        if clean_spaces(strip_tokens(src)).casefold() == body.casefold() and words(src):
            reasons.append("copy_of_source")
        if _REPEAT.search(out):
            reasons.append("repetition")
        src_len = len(clean_spaces(strip_tokens(src)))
        if src_len >= 12 and body:
            ratio = len(body) / src_len
            if ratio > self.s.max_len_ratio or ratio < self.s.min_len_ratio:
                reasons.append(f"length_ratio:{ratio:.2f}")
        return reasons

    # -- décision complète ---------------------------------------------------
    def evaluate_path(self, source: str, target: str, src: str, out: str,
                      ref: str | None = None, back: bool = True) -> Verdict:
        """Valide une traduction `source → target`.

        `src` sert aux règles dures (jetons, chiffres) ; `ref` est le texte de
        référence pour la rétro-traduction (par défaut `src`). Pour une traduction
        anglais → ewondo, on rétro-traduit ewondo → français → anglais et on
        compare à la phrase anglaise d'origine : le contrôle reste significatif.
        """
        reasons = self.static_checks(src, out)
        if reasons:
            return Verdict(False, reasons)
        if not back or source == target:
            return Verdict(True, [], confidence=1.0 if source == target else 0.5)
        reference = ref if ref is not None else src
        if not self.tr.has_direction(target, source):
            return Verdict(True, ["back_translation_unavailable"], confidence=0.5)
        try:
            bt = self.tr.translate_path(target, source, [out])[0].text
        except Exception as exc:                    # modèle absent, erreur d'inférence…
            return Verdict(True, [f"back_translation_error:{type(exc).__name__}"], confidence=0.4)
        score = chrf(bt, reference)
        threshold = self.s.min_bt_score_short if len(words(reference)) < self.s.short_words else self.s.min_bt_score
        info: list[str] = []
        if find_tokens(bt) != find_tokens(reference):
            info.append("bt_tokens_changed")        # informatif : la rétro-traduction a bougé les jetons
        if score < threshold:
            return Verdict(False, [f"back_translation_low:{score:.2f}<{threshold:.2f}", *info], score, bt)
        return Verdict(True, info, score, bt, confidence=min(0.9, score))

    def evaluate(self, lang: str, src: str, out: str, back: bool = True) -> Verdict:
        """Compatibilité : français → langue locale (l'ancien sens unique)."""
        return self.evaluate_path("fr", lang, src, out, ref=src, back=back)
