"""Orchestration du moteur — traduction français/anglais ↔ ewondo.

  1. chercher la phrase dans memory.json (dans le bon sens)
  2. si elle existe : renvoyer la traduction humaine
  3. sinon chercher les termes dans glossary.json
  4. remplacer les termes connus par des jetons
  5. envoyer le texte protégé à Marian (pivot français pour l'anglais)
  6. réinsérer les traductions du glossaire
  7. vérifier les jetons et effectuer la rétro-traduction
  8. renvoyer la traduction OU le texte source original

Le texte « original » renvoyé en cas d'échec est le texte masqué reçu du module 1
(jetons inclus) : le module 1 y remet les vraies valeurs et l'écran reste inchangé.
"""
from __future__ import annotations

import json
import logging
import threading
import time
from collections import Counter
from dataclasses import dataclass, field

from config import LANGUAGES, SOURCE_LANGUAGES, TARGET_LANGUAGES, Settings
from glossary import Glossary, TermUse
from guard import sensitive_kinds
from memory import TranslationMemory
from textutil import find_tokens, has_letters
from translator import Translator
from validator import Validator

log = logging.getLogger("safinum.pipeline")


@dataclass
class Item:
    id: str
    text: str
    lang: str | None = None          # langue source : 'fr' | 'en' | 'ewondo' | None (= fr)
    ctx: dict = field(default_factory=dict)


@dataclass
class Result:
    id: str
    text: str
    status: str                      # ok | fallback | passthrough | rejected
    source: str                      # memory | memory_draft | glossary | mt | none
    confidence: float = 0.0
    needs_review: bool = False
    reasons: list[str] = field(default_factory=list)
    back_translation: str | None = None


@dataclass
class _Work:
    item: Item
    source: str                      # langue source effective (celle du texte d'origine)
    target: str                      # langue cible
    mt_source: str                   # langue réellement envoyée au modèle
    text_mt: str                     # texte source (ou pivot français) avant glossaire
    pivoted: bool = False
    protected: str = ""
    mapping: dict[str, TermUse] = field(default_factory=dict)
    result: Result | None = None


class TranslationPipeline:
    def __init__(self, settings: Settings, memory: TranslationMemory, glossary: Glossary,
                 translator: Translator, validator: Validator):
        self.s, self.memory, self.glossary = settings, memory, glossary
        self.translator, self.validator = translator, validator
        self.counters: Counter = Counter()
        self._unseen: set[tuple[str, str]] = set()
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ utilitaires
    def _fallback(self, item: Item, reasons: list[str], bt: str | None = None) -> Result:
        return Result(item.id, item.text, "fallback", "none", 0.0, False, reasons, bt)

    def _log_unseen(self, lang: str, text: str, ctx: dict) -> None:
        """Garde la trace (texte masqué uniquement) des phrases à faire traduire par les locuteurs."""
        if not self.s.log_unseen:
            return
        key = (lang, text)
        with self._lock:
            if key in self._unseen:
                return
            self._unseen.add(key)
            try:
                with open(self.s.unseen_log, "a", encoding="utf-8") as f:
                    rec = {"lang": lang, "fr": text, "alert": ctx.get("alert"), "step": ctx.get("step"), "ts": int(time.time())}
                    f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            except OSError as exc:
                log.warning("journal des phrases inédites indisponible : %s", exc)

    # ------------------------------------------------------------------ étape A
    def _prepare(self, source_req: str | None, target: str, it: Item) -> _Work:
        source = (source_req or it.lang or "fr").lower()
        w = _Work(it, source, target, source, it.text)

        kinds = sensitive_kinds(it.text)
        if kinds:   # le module 1 aurait dû masquer : on ne traduit ni ne journalise
            w.result = Result(it.id, it.text, "rejected", "none", 0.0, False, [f"sensitive:{','.join(kinds)}"])
            return w
        if not has_letters(it.text):
            w.result = Result(it.id, it.text, "passthrough", "none", 1.0, False, ["nothing_to_translate"])
            return w
        if source == target:
            w.result = Result(it.id, it.text, "passthrough", "none", 1.0, False, ["same_language"])
            return w
        if source not in SOURCE_LANGUAGES or target not in TARGET_LANGUAGES:
            w.result = self._fallback(it, [f"unsupported_direction:{source}->{target}"])
            return w
        if not self.translator.has_direction(source, target):
            reason = "pivot_en_unavailable" if source == "en" else "direction_unavailable"
            w.result = self._fallback(it, [reason])
            return w

        # 1-2. mémoire dans le bon sens (clé française, anglaise ou ewondo)
        hit = self.memory.lookup_direction(it.text, source, target)
        if hit:
            src = "memory_draft" if hit.is_draft else "memory"
            w.result = Result(it.id, hit.text, "ok", src, 0.5 if hit.is_draft else 1.0,
                              hit.is_draft, [f"memory:{hit.entry_id}"])
            return w

        # 3-4. anglais → ewondo : pivot vers le français pour retrouver mémoire/glossaire
        if source == "en" and target in LANGUAGES:
            if not self.translator.has_direction("en", "fr"):
                w.result = self._fallback(it, ["pivot_en_unavailable"])
                return w
            pivot = self.translator.translate_path("en", "fr", [it.text])[0]
            if not pivot.text.strip() or find_tokens(pivot.text) != find_tokens(it.text):
                w.result = self._fallback(it, ["pivot_en_failed"])
                return w
            w.text_mt, w.pivoted = pivot.text, True
            w.mt_source = "fr"
            hit = self.memory.lookup_direction(w.text_mt, "fr", target)
            if hit:
                src = "memory_draft" if hit.is_draft else "memory"
                w.result = Result(it.id, hit.text, "ok", src, 0.5 if hit.is_draft else 0.9,
                                  True, [f"memory:{hit.entry_id}", "via_pivot_en"])
                return w

        # 3-4. glossaire (français/anglais → ewondo, ou ewondo → fr/en)
        if target in LANGUAGES:
            w.protected, w.mapping = self.glossary.protect(w.text_mt, target, source=w.mt_source)
        elif source in LANGUAGES:
            w.protected, w.mapping = self.glossary.protect_reverse(it.text, source, target)
        else:
            w.protected, w.mapping = it.text, {}

        if not has_letters(w.protected):                     # tout le texte est du glossaire
            final = self.glossary.reinsert(w.protected, w.mapping)
            if find_tokens(final) != find_tokens(it.text):
                w.result = self._fallback(it, ["tokens_after_reinsert"])
                return w
            draft = any(u.draft for u in w.mapping.values())
            w.result = Result(it.id, final, "ok", "glossary", 0.5 if draft else 0.95, draft,
                              ["via_pivot_en"] if w.pivoted else [])
            return w

        if target in LANGUAGES:
            self._log_unseen(target, w.text_mt, it.ctx)
        if self.s.strict_alert and it.ctx.get("alert") in ("warning", "error"):
            w.result = self._fallback(it, ["alert_requires_validated_translation"])
            return w
        if w.pivoted and not self.s.allow_pivot_mt:
            w.result = self._fallback(it, ["pivot_en_unvalidated"])
        return w

    # ------------------------------------------------------------------ API publique
    def translate_items(self, source: str | None, target: str, items: list[Item]) -> list[Result]:
        works = [self._prepare(source, target, it) for it in items]

        # 5. traduction automatique en lot, groupée par direction réelle
        groups: dict[tuple[str, str], list[_Work]] = {}
        for w in works:
            if w.result is None:
                groups.setdefault((w.mt_source, w.target), []).append(w)

        for (mt_source, mt_target), group in groups.items():
            try:
                outs = self.translator.translate_path(mt_source, mt_target, [w.protected for w in group])
            except Exception as exc:                        # modèle absent, mémoire insuffisante…
                log.exception("échec du moteur de traduction (%s → %s)", mt_source, mt_target)
                for w in group:
                    w.result = self._fallback(w.item, [f"engine_error:{type(exc).__name__}"])
                continue
            for w, o in zip(group, outs):
                w.result = self._finish(w, o.text)

        results = [w.result for w in works]
        for r in results:
            self.counters[f"status:{r.status}"] += 1
            self.counters[f"source:{r.source}"] += 1
        return results

    def translate_batch(self, lang: str, items: list[Item]) -> list[Result]:
        """Compatibilité : cible = langue locale, source = `item.lang` (ou français)."""
        return self.translate_items(None, lang, items)

    # 6-8. réinsertion, validation, décision
    def _finish(self, w: _Work, out: str) -> Result:
        it = w.item
        verdict = self.validator.evaluate_path(w.source, w.target, w.protected, out, ref=it.text)
        if not verdict.accepted:
            return self._fallback(it, verdict.reasons, verdict.back_translation)
        final = self.glossary.reinsert(out, w.mapping)
        if find_tokens(final) != find_tokens(it.text):
            return self._fallback(it, ["tokens_after_reinsert"], verdict.back_translation)
        draft = any(u.draft for u in w.mapping.values())
        review = draft or verdict.confidence < self.s.review_below or w.pivoted
        reasons = list(verdict.reasons) + (["via_pivot_en"] if w.pivoted else [])
        return Result(it.id, final, "ok", "mt", round(verdict.confidence, 3), review, reasons,
                      verdict.back_translation)

    def stats(self) -> dict:
        return dict(self.counters)
