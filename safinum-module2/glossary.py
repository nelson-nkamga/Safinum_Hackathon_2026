"""Livrable 2 (code) : glossaire multilingue + remplacement des termes par des jetons.

glossary.json : termes spécialisés (solde, frais, bénéficiaire…) et leur traduction.
 - policy "translate" : terme traduit (utilisable seulement si la traduction est validée)
 - policy "keep"      : nom propre / sigle laissé tel quel (FCFA, Mobile Money, Safinum…)

Avant d'envoyer un texte au modèle, les termes connus sont remplacés par des jetons
⟦G1⟧ ⟦G2⟧ …; après traduction, chaque jeton est remplacé par la traduction validée.
Le modèle ne peut donc pas déformer un terme financier du glossaire.

Le glossaire fonctionne dans les deux sens : français/anglais → ewondo (protect)
et ewondo → français/anglais (protect_reverse, sur les traductions validées).
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from textutil import NATIVE_RE, native, normalize_key


@dataclass
class TermUse:
    term_id: str
    surface: str        # forme trouvée dans le texte source
    replacement: str    # texte réinséré après traduction
    policy: str
    draft: bool = False


def _match_case(surface: str, replacement: str) -> str:
    if surface[:1].isupper() and replacement[:1].islower():
        return replacement[:1].upper() + replacement[1:]
    return replacement


class Glossary:
    def __init__(self, path: Path, allow_draft: bool = False):
        self.path = Path(path)
        self.allow_draft = allow_draft
        self.terms: list[dict] = []
        self._by_form: dict[str, dict] = {}          # formes françaises (compatibilité)
        self._by_form_en: dict[str, dict] = {}       # formes anglaises
        self._reverse: dict[str, dict[str, tuple[dict, str, bool]]] = {}
        self._regex: re.Pattern | None = None
        self._regex_en: re.Pattern | None = None
        self._regex_reverse: dict[str, re.Pattern] = {}
        self.load()

    @staticmethod
    def _compile(forms: list[str]) -> re.Pattern | None:
        if not forms:
            return None
        alt = "|".join(re.escape(f).replace(r"\ ", r"\s+") for f in forms)
        return re.compile(rf"(?<![\w])(?:{alt})(?![\w])", re.IGNORECASE | re.UNICODE)

    def load(self) -> None:
        data = json.loads(self.path.read_text(encoding="utf-8"))
        self.terms = data.get("terms", [])
        self._by_form = {}
        self._by_form_en = {}
        self._reverse = {}
        for t in self.terms:
            for form in t.get("fr", []):
                self._by_form[form.casefold()] = t
            for form in t.get("en", []):
                self._by_form_en[form.casefold()] = t
            if t.get("policy") == "keep":
                continue
            for lang, tr in (t.get("translations") or {}).items():
                text, status = tr.get("text"), tr.get("status")
                if not text or status not in ("validated", "draft"):
                    continue
                slot = self._reverse.setdefault(lang, {})
                slot[normalize_key(text)] = (t, status, status != "validated")

        self._regex = self._compile(sorted(self._by_form, key=len, reverse=True))
        self._regex_en = self._compile(sorted(self._by_form_en, key=len, reverse=True))
        self._regex_reverse = {
            lang: self._compile(sorted(slot, key=len, reverse=True))
            for lang, slot in self._reverse.items()
            if slot
        }

    def _replacement(self, term: dict, lang: str) -> tuple[str, bool] | None:
        if term.get("policy") == "keep":
            return None  # remplacé par la forme d'origine (voir protect)
        tr = (term.get("translations") or {}).get(lang) or {}
        text, status = tr.get("text"), tr.get("status")
        if text and (status == "validated" or (self.allow_draft and status == "draft")):
            return text, status != "validated"
        return None

    def _sub_outside_tokens(self, text: str, rx: re.Pattern, repl) -> str:
        """Applique `rx` sans jamais toucher l'intérieur des jetons du module 1."""
        out, last = [], 0
        for tm in NATIVE_RE.finditer(text):
            out.append(rx.sub(repl, text[last:tm.start()]))
            out.append(tm.group(0))
            last = tm.end()
        out.append(rx.sub(repl, text[last:]))
        return "".join(out)

    def protect(self, text: str, lang: str, source: str = "fr") -> tuple[str, dict[str, TermUse]]:
        """Remplace les termes connus par ⟦G1⟧, ⟦G2⟧… → (texte protégé, {jeton: TermUse})."""
        rx = self._regex_en if source == "en" else self._regex
        forms = self._by_form_en if source == "en" else self._by_form
        if not rx:
            return text, {}
        mapping: dict[str, TermUse] = {}
        by_key: dict[tuple, str] = {}
        counter = 0

        def repl(m: re.Match) -> str:
            nonlocal counter
            surface = m.group(0)
            term = forms.get(re.sub(r"\s+", " ", surface).casefold())
            if term is None:
                return surface
            if term.get("policy") == "keep":
                replacement, draft = surface, False
            else:
                r = self._replacement(term, lang)
                if r is None:
                    return surface  # pas de traduction validée : on laisse le modèle traduire
                replacement, draft = _match_case(surface, r[0]), r[1]
            key = (term["id"], replacement)
            if key not in by_key:
                counter += 1
                tok = native("G", counter)
                by_key[key] = tok
                mapping[tok] = TermUse(term["id"], surface, replacement, term.get("policy", "translate"), draft)
            return by_key[key]

        return self._sub_outside_tokens(text, rx, repl), mapping

    def protect_reverse(self, text: str, source_lang: str, target: str) -> tuple[str, dict[str, TermUse]]:
        """Protège les termes ewondo connus avant une traduction vers fr/en.

        La forme trouvée est le terme ewondo validé, la réinsertion est le terme
        français (ou anglais si disponible). Sans traduction validée, le texte
        est laissé au modèle : aucun terme financier n'est inventé.
        """
        rx = self._regex_reverse.get(source_lang)
        if not rx:
            return text, {}
        mapping: dict[str, TermUse] = {}
        by_key: dict[tuple, str] = {}
        counter = 0

        def repl(m: re.Match) -> str:
            nonlocal counter
            surface = m.group(0)
            hit = self._reverse[source_lang].get(normalize_key(surface))
            if not hit:
                return surface
            term, status, draft = hit
            if draft and not self.allow_draft:
                return surface
            if target == "en" and term.get("en"):
                replacement = term["en"][0]
            else:
                replacement = (term.get("fr") or [surface])[0]
            replacement = _match_case(surface, replacement)
            key = (term["id"], replacement)
            if key not in by_key:
                counter += 1
                tok = native("G", counter)
                by_key[key] = tok
                mapping[tok] = TermUse(term["id"], surface, replacement, "translate", draft)
            return by_key[key]

        return self._sub_outside_tokens(text, rx, repl), mapping

    @staticmethod
    def reinsert(text: str, mapping: dict[str, TermUse]) -> str:
        for tok, use in mapping.items():
            text = text.replace(tok, use.replacement)
        return text

    def stats(self) -> dict:
        by: dict[str, dict[str, int]] = {}
        for t in self.terms:
            if t.get("policy") == "keep":
                by.setdefault("keep", {}).setdefault("validated", 0)
                by["keep"]["validated"] += 1
                continue
            for lang, tr in (t.get("translations") or {}).items():
                by.setdefault(lang, {}).setdefault(tr.get("status", "todo"), 0)
                by[lang][tr.get("status", "todo")] += 1
        return {"terms": len(self.terms), "by_language": by}
