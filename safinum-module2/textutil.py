"""Utilitaires partagés : jetons, normalisation, score chrF, découpage en phrases.

Contrat avec le module 1
------------------------
Le module 1 envoie des textes déjà masqués avec des jetons « natifs » ⟦M1⟧ ⟦T1⟧ …
(codes réservés au module 1 : M P T A R D E N X). Le module 2 ajoute ses propres
jetons de glossaire avec le code **G** (⟦G1⟧) : aucun risque de collision.
Les jetons doivent revenir intacts, une seule fois chacun, dans la réponse.
"""
from __future__ import annotations

import re
import unicodedata
from collections import Counter

NATIVE_OPEN, NATIVE_CLOSE = "⟦", "⟧"
NATIVE_RE = re.compile(r"⟦([A-Z])(\d{1,3})⟧")
_SPACES = re.compile(r"[\s\u00A0\u202F\u2009]+")


def native(code: str, n: int) -> str:
    return f"{NATIVE_OPEN}{code}{n}{NATIVE_CLOSE}"


def find_tokens(text: str) -> Counter:
    """Multiensemble des jetons natifs présents dans le texte."""
    return Counter(m.group(0) for m in NATIVE_RE.finditer(text))


def strip_tokens(text: str, repl: str = " ") -> str:
    return NATIVE_RE.sub(repl, text)


def has_letters(text: str) -> bool:
    """Reste-t-il au moins un mot (2 lettres) une fois les jetons retirés ?"""
    return re.search(r"[^\W\d_]{2,}", strip_tokens(text)) is not None


def words(text: str) -> list[str]:
    return re.findall(r"[^\W_]+(?:['’-][^\W_]+)*", strip_tokens(text))


def clean_spaces(text: str) -> str:
    return _SPACES.sub(" ", text).strip()


def normalize_key(text: str) -> str:
    """Clé de recherche dans la mémoire : insensible à la casse, aux espaces,
    aux apostrophes typographiques et au point final. Les accents sont conservés."""
    t = unicodedata.normalize("NFC", text)
    t = t.replace("’", "'").replace("‘", "'").replace("«", '"').replace("»", '"')
    t = clean_spaces(t).casefold()
    t = re.sub(r"\s*:\s*", " : ", t)
    return t.rstrip(" .")


def digit_runs(text: str) -> Counter:
    """Suites de chiffres hors jetons : elles ne doivent jamais changer à la traduction."""
    return Counter(re.findall(r"\d+", strip_tokens(text)))


# --------------------------------------------------------------------------- chrF
def _ngrams(s: str, n: int) -> Counter:
    return Counter(s[i:i + n] for i in range(len(s) - n + 1))


def chrf(hyp: str, ref: str, max_n: int = 6, beta: float = 2.0) -> float:
    """Score chrF simplifié (0..1) entre deux textes, jetons ignorés."""
    h = clean_spaces(strip_tokens(hyp)).casefold()
    r = clean_spaces(strip_tokens(ref)).casefold()
    if not h and not r:
        return 1.0
    if not h or not r:
        return 0.0
    precs, recs = [], []
    for n in range(1, max_n + 1):
        hn, rn = _ngrams(h, n), _ngrams(r, n)
        if not hn or not rn:
            continue
        overlap = sum((hn & rn).values())
        precs.append(overlap / sum(hn.values()))
        recs.append(overlap / sum(rn.values()))
    if not precs:
        return 0.0
    p, rc = sum(precs) / len(precs), sum(recs) / len(recs)
    if p + rc == 0:
        return 0.0
    return (1 + beta ** 2) * p * rc / (beta ** 2 * p + rc)


# ------------------------------------------------------------------- phrases
_SENT_SPLIT = re.compile(r"(?<=[.!?…])\s+(?=[A-ZÀ-ÖØ-Þ⟦])")


def split_sentences(text: str) -> list[str]:
    parts = [p for p in _SENT_SPLIT.split(text.strip()) if p]
    return parts or [text]


# ------------------------------------------------------------ format des jetons
# Ordre stable des codes du module 1. Il sert au format numérique « NUM1001Z » :
# 1001 = code M (1) × 1000 + numéro 1. Le modèle Marian conserve beaucoup mieux
# ces jetons numériques que « ⟦M1⟧ », absent de son vocabulaire.
TOKEN_CODES = "MPTARDENXG"
_CODE_INDEX = {code: i + 1 for i, code in enumerate(TOKEN_CODES)}
_INDEX_CODE = {i + 1: code for i, code in enumerate(TOKEN_CODES)}


class TokenCodec:
    """Convertit les jetons natifs ⟦M1⟧ vers le format envoyé au modèle, et inversement.

    Le vocabulaire de Marian ne contient probablement pas « ⟦ ⟧ » : un caractère inconnu
    serait perdu → texte rejeté. Le format se choisit donc par test
    (scripts/test_token_formats.py) sans toucher au module 1.
    """
    FORMATS = {
        "native": ("⟦{c}{n}⟧", re.compile(r"⟦\s*([A-Z])\s*(\d{1,3})\s*⟧")),
        "square": ("[[{c}{n}]]", re.compile(r"\[\[\s*([A-Z])\s*(\d{1,3})\s*\]\]")),
        "brace": ("{{{c}{n}}}", re.compile(r"\{\s*([A-Z])\s*(\d{1,3})\s*\}")),
        "alnum": ("Q{c}{n}Q", re.compile(r"Q([A-Z])(\d{1,3})Q")),
        "num": ("NUM{idx}Z", re.compile(r"NUM\s*(\d{4,6})\s*Z", re.IGNORECASE)),
        "numdash": ("NUM-{idx}", re.compile(r"NUM\s*-\s*(\d{4,6})", re.IGNORECASE)),
    }

    def __init__(self, fmt: str = "num"):
        if fmt not in self.FORMATS:
            raise ValueError(f"format de jeton inconnu : {fmt} (choix : {', '.join(self.FORMATS)})")
        self.fmt = fmt
        self._tpl, self._re = self.FORMATS[fmt]

    @staticmethod
    def _index(code: str, number: int) -> int:
        return _CODE_INDEX[code] * 1000 + number

    def _encode_one(self, code: str, number: int) -> str:
        if self.fmt in ("num", "numdash"):
            return self._tpl.format(idx=self._index(code, number))
        return self._tpl.format(c=code, n=number)

    def _decode_one(self, number: int) -> str | None:
        if self.fmt in ("num", "numdash"):
            code = _INDEX_CODE.get(number // 1000)
            n = number % 1000
            return native(code, n) if code and n else None
        # formats à lettre : le numéro est le groupe 2
        return None

    def encode(self, text: str) -> str:
        return NATIVE_RE.sub(lambda m: self._encode_one(m.group(1), int(m.group(2))), text)

    def decode(self, text: str) -> str:
        def repl(m: re.Match) -> str:
            if self.fmt in ("num", "numdash"):
                tok = self._decode_one(int(m.group(1)))
                return tok if tok else m.group(0)
            return native(m.group(1), int(m.group(2)))

        out = self._re.sub(repl, text)
        # tolère aussi le format natif abîmé par des espaces
        return self.FORMATS["native"][1].sub(lambda m: native(m.group(1), int(m.group(2))), out)
