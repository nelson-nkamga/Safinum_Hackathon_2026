"""Livrable 1 (code) : mémoire de traduction.

memory.json contient les phrases de SAFINUM déjà traduites ET validées par des
locuteurs. Les phrases sont stockées sous leur forme *masquée* (avec les jetons du
module 1), par exemple « Frais : ⟦M1⟧ » : la même entrée sert donc quelle que soit
la valeur du montant.

Statuts d'une traduction : todo (rien) · draft (proposée par le modèle) ·
validated (validée par un locuteur) · rejected.
Par défaut seules les traductions « validated » sont utilisées.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path

from config import LANGUAGES
from textutil import find_tokens, normalize_key

log = logging.getLogger("safinum.memory")


@dataclass
class MemoryHit:
    entry_id: str
    text: str
    status: str            # validated | draft
    tags: list[str]

    @property
    def is_draft(self) -> bool:
        return self.status != "validated"


class TranslationMemory:
    def __init__(self, path: Path, allow_draft: bool = False):
        self.path = Path(path)
        self.allow_draft = allow_draft
        self.entries: list[dict] = []
        self._index: dict[str, dict] = {}
        self._reverse: dict[str, dict[str, tuple[dict, str]]] = {}
        self.warnings: list[str] = []
        self.load()

    def load(self) -> None:
        data = json.loads(self.path.read_text(encoding="utf-8"))
        self.entries = data.get("entries", [])
        self._index = {}
        self._reverse = {}
        self.warnings = []
        for e in self.entries:
            for field in ("fr", "en"):
                src = e.get(field)
                if src:
                    key = normalize_key(src)
                    if key in self._index and self._index[key] is not e:
                        self.warnings.append(f"clé en double : {src!r} ({self._index[key]['id']} / {e['id']})")
                    self._index[key] = e
            # une traduction doit contenir exactement les mêmes jetons que sa source
            for lang, tr in (e.get("translations") or {}).items():
                text = tr.get("text")
                if text and find_tokens(text) != find_tokens(e.get("fr", "")):
                    self.warnings.append(f"{e['id']}/{lang} : jetons différents de la source → entrée ignorée")
                    tr["status"] = "rejected"
                # index inverse : ewondo → français/anglais (pour le sens inverse)
                if text and lang in LANGUAGES and tr.get("status") in ("validated", "draft"):
                    key = normalize_key(text)
                    slot = self._reverse.setdefault(lang, {})
                    if key in slot and slot[key][0] is not e:
                        self.warnings.append(f"traduction en double : {text!r} ({slot[key][0]['id']} / {e['id']})")
                    else:
                        slot[key] = (e, tr.get("status"))
        for w in self.warnings:
            log.warning(w)

    def lookup(self, text: str, lang: str) -> MemoryHit | None:
        e = self._index.get(normalize_key(text))
        if not e:
            return None
        tr = (e.get("translations") or {}).get(lang) or {}
        status, out = tr.get("status"), tr.get("text")
        if not out:
            return None
        if status == "validated" or (self.allow_draft and status == "draft"):
            return MemoryHit(e["id"], out, status, e.get("tags", []))
        return None

    def lookup_direction(self, text: str, source: str, target: str) -> MemoryHit | None:
        """Mémoire de traduction dans n'importe quelle direction.

        - vers l'ewondo : la clé est le texte source (français/anglais) et la valeur
          est `translations.ewondo` (comportement historique) ;
        - depuis l'ewondo : la clé est la traduction ewondo validée et la valeur est
          le champ `fr` (ou `en` quand disponible) de l'entrée ;
        - français ↔ anglais : la clé est le champ source et la valeur l'autre champ.
        """
        if source == target:
            return None

        # vers la langue nationale : index des textes sources fr/en
        if target in LANGUAGES:
            return self.lookup(text, target)

        # depuis la langue nationale : index inverse construit sur les traductions validées
        if source in LANGUAGES:
            hit = self._reverse.get(source, {}).get(normalize_key(text))
            if not hit:
                return None
            e, status = hit
            if not (status == "validated" or (self.allow_draft and status == "draft")):
                return None
            out = e.get(target) if target in ("fr", "en") else None
            if not out:
                return None
            return MemoryHit(e["id"], out, status or "validated", e.get("tags", []))

        # français ↔ anglais : la clé est le champ source, la valeur l'autre champ
        e = self._index.get(normalize_key(text))
        if not e:
            return None
        out = e.get(target) if target in ("fr", "en") else None
        if not out or normalize_key(out) == normalize_key(text):
            return None
        return MemoryHit(e["id"], out, "validated", e.get("tags", []))

    def stats(self) -> dict:
        langs: dict[str, dict[str, int]] = {}
        for e in self.entries:
            for lang, tr in (e.get("translations") or {}).items():
                langs.setdefault(lang, {}).setdefault(tr.get("status", "todo"), 0)
                langs[lang][tr.get("status", "todo")] += 1
        return {"entries": len(self.entries), "by_language": langs, "warnings": len(self.warnings)}
