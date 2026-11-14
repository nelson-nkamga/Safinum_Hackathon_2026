"""Tâche 6 : choisir le format de jeton que le modèle conserve le mieux.

    python scripts/test_token_formats.py ewondo
Pour chaque format (native ⟦M1⟧, square [[M1]], brace {M1}, alnum QM1Q,
num NUM1001Z, numdash NUM-1001), traduit des phrases contenant des jetons et
mesure le taux de jetons conservés (une fois chacun, aucun inventé).
Le moteur réessaie automatiquement les formats quand un jeton disparaît ; ce
script mesure le format brut, sans ce filet de sécurité.

Règle de décision : prendre le format avec le meilleur taux, puis
    export SAFINUM_TOKEN_FORMAT=<format>
Le module 1 n'a pas à changer : le moteur convertit les jetons à l'entrée et à la sortie.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from config import LANGUAGES, Settings  # noqa: E402
from textutil import TokenCodec, find_tokens  # noqa: E402
from translator import CT2MarianBackend, Translator  # noqa: E402

SENTENCES = [
    "Frais : ⟦M1⟧",
    "Total à débiter : ⟦M1⟧",
    "Solde après opération : ⟦M1⟧",
    "Numéro de compte : ⟦A1⟧",
    "Bonjour, ⟦N1⟧",
    "Vous envoyez ⟦M1⟧ à ⟦N1⟧.",
    "Le transfert de ⟦M1⟧ vers ⟦T1⟧ a été effectué le ⟦D1⟧.",
    "Référence : ⟦R1⟧",
    "Frais de ⟦P1⟧ soit ⟦M1⟧.",
    "Veuillez vérifier ⟦T1⟧ avant de confirmer.",
    "Votre solde est de ⟦M1⟧ au ⟦D1⟧.",
    "Opération : ⟦G1⟧ ⟦M1⟧",
]


def main(lang: str) -> None:
    if lang not in LANGUAGES:
        sys.exit(f"langue inconnue : {lang} (choix : {', '.join(LANGUAGES)})")
    s = Settings()
    backend = CT2MarianBackend(s)
    tr = Translator(backend, s)
    pair = LANGUAGES[lang]["fr_to"]
    if not backend.has_pair(pair):
        sys.exit(f"modèle absent : {pair}. Lancez scripts/download_model.py --lang {lang}")
    print(f"{len(SENTENCES)} phrases, direction fr→{lang}, modèle réel\n")
    best = None
    for fmt in TokenCodec.FORMATS:
        codec = TokenCodec(fmt)
        try:
            outs = tr._backend_call(pair, SENTENCES, codec)
        except Exception as exc:
            print(f"{fmt:8s}  ERREUR  {type(exc).__name__}: {exc}")
            continue
        ok = sum(find_tokens(o.text) == find_tokens(src) for src, o in zip(SENTENCES, outs))
        rate = ok / len(SENTENCES)
        print(f"{fmt:8s}  {ok:2d}/{len(SENTENCES)}  ({rate:.0%})")
        for src, o in list(zip(SENTENCES, outs))[:3]:
            print(f"          {src}  →  {o.text}")
        if best is None or rate > best[1]:
            best = (fmt, rate)
    if best:
        print(f"\nMeilleur format : {best[0]} ({best[1]:.0%})  →  export SAFINUM_TOKEN_FORMAT={best[0]}")
        if best[1] < 0.9:
            print("ATTENTION : < 90 %. Le moteur réessaiera les autres formats et, en dernier recours,\n"
                  "renverra le texte source (jamais un montant faux à l'écran).")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "ewondo")
