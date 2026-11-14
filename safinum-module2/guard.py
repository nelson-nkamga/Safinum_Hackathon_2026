"""Garde-fou côté serveur (défense en profondeur).

Le module 1 masque déjà les données sensibles. Si malgré tout un texte reçu en
contient (montant, téléphone, compte, e-mail, référence…), le serveur refuse de le
traduire, de le journaliser, et renvoie le texte tel quel.
"""
from __future__ import annotations

import re

from textutil import strip_tokens

_S = r"[ \u00A0\u202F\u2009]"
_PATTERNS = {
    "email": re.compile(r"[\w.%+-]+@[\w-]+(?:\.[\w-]+)+"),
    "amount": re.compile(rf"\d[\d .,\u00A0\u202F\u2009]*{_S}?(?:FCFA|F\s?CFA|XAF|XOF|CFA|EUR|USD|€|\$)", re.I),
    "phone": re.compile(r"\+\d{1,3}(?:[ \u00A0\u202F.\-]?\d){6,12}"),
    "account": re.compile(rf"\b[A-Z]{{2}}(?:{_S}?\d{{2,6}}){{3,}}\b"),
    "reference": re.compile(r"(?<![\w-])(?=[A-Z0-9-]*\d)[A-Z]{2,6}(?:-[A-Z0-9]{2,12}){1,4}(?![\w-])"),
    "long_number": re.compile(r"(?<!\w)\d(?:[ \u00A0\u202F.\-]?\d){7,}(?!\w)"),
}


def sensitive_kinds(text: str) -> list[str]:
    """Types de données sensibles encore présentes dans le texte (jetons exclus)."""
    t = strip_tokens(text)
    return [k for k, rx in _PATTERNS.items() if rx.search(t)]
