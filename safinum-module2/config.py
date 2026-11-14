"""Configuration du moteur de traduction SAFINUM (module 2).

Tout se règle par variables d'environnement (préfixe SAFINUM_) ou en créant
un objet Settings à la main (utile pour les tests).

Le projet ne sert qu'une langue nationale : l'EWONDO. Les directions exposées
sont français ↔ ewondo et anglais ↔ ewondo (l'anglais passe par le pivot
français fourni par le dépôt flagship-ai/cameroon-int8).
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent


def _bool(name: str, default: bool) -> bool:
    v = os.getenv(name)
    return default if v is None else v.strip().lower() in {"1", "true", "yes", "oui", "on"}


def _float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, default))
    except ValueError:
        return default


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except ValueError:
        return default


def _models_dir() -> str | None:
    """Dossier du modèle : SAFINUM_MODELS_DIR, sinon ./models s'il est déjà téléchargé."""
    explicit = os.getenv("SAFINUM_MODELS_DIR")
    if explicit:
        return explicit
    default = BASE_DIR / "models"
    if (default / "francais-ewondo" / "model.bin").exists():
        return str(default)
    return None


# Langues nationales prises en charge. Les noms de dossiers sont ceux du dépôt
# flagship-ai/cameroon-int8 (un dossier = une direction, pivot français).
LANGUAGES = {
    "ewondo": {
        "label": "Ewondo",
        "fr_to": "francais-ewondo",
        "to_fr": "ewondo-francais",
        "en_to": "english-francais",      # pivot anglais → français
        "to_en": "francais-english",      # pivot français → anglais
    },
}

LANGUAGE_LABELS = {
    "fr": "Français",
    "en": "English",
    **{code: meta["label"] for code, meta in LANGUAGES.items()},
}

EN_TO_FR_PAIR = LANGUAGES["ewondo"]["en_to"]
FR_TO_EN_PAIR = LANGUAGES["ewondo"]["to_en"]

# Codes acceptés par l'API.
SOURCE_LANGUAGES = tuple(LANGUAGE_LABELS)
TARGET_LANGUAGES = tuple(LANGUAGE_LABELS)


def direction_path(source: str, target: str) -> list[str]:
    """Dossiers du modèle à enchaîner pour traduire de `source` vers `target`.

    Lève KeyError si la direction n'existe pas. Une liste vide signifie que la
    source et la cible sont identiques (aucun modèle à appeler).
    """
    if source == target:
        return []
    if source == "fr" and target in LANGUAGES:
        return [LANGUAGES[target]["fr_to"]]
    if source == "en" and target in LANGUAGES:
        return [EN_TO_FR_PAIR, LANGUAGES[target]["fr_to"]]
    if source in LANGUAGES and target == "fr":
        return [LANGUAGES[source]["to_fr"]]
    if source in LANGUAGES and target == "en":
        return [LANGUAGES[source]["to_fr"], FR_TO_EN_PAIR]
    if source == "en" and target == "fr":
        return [EN_TO_FR_PAIR]
    if source == "fr" and target == "en":
        return [FR_TO_EN_PAIR]
    raise KeyError(f"direction non prise en charge : {source} → {target}")


def all_model_pairs() -> list[str]:
    """Tous les dossiers de modèle utiles (évite de télécharger les 119 langues)."""
    pairs: list[str] = []
    for source in SOURCE_LANGUAGES:
        for target in TARGET_LANGUAGES:
            try:
                pairs.extend(direction_path(source, target))
            except KeyError:
                pass
    # garde l'ordre, supprime les doublons
    return list(dict.fromkeys(pairs))


@dataclass
class Settings:
    memory_path: Path = BASE_DIR / "memory.json"
    glossary_path: Path = BASE_DIR / "glossary.json"
    unseen_log: Path = BASE_DIR / "unseen.jsonl"   # phrases masquées à faire traduire par les locuteurs

    # --- Modèle -----------------------------------------------------------
    hf_repo: str = field(default_factory=lambda: os.getenv("SAFINUM_HF_REPO", "flagship-ai/cameroon-int8"))
    models_dir: str | None = field(default_factory=_models_dir)
    device: str = field(default_factory=lambda: os.getenv("SAFINUM_DEVICE", "cpu"))
    compute_type: str = field(default_factory=lambda: os.getenv("SAFINUM_COMPUTE_TYPE", "int8"))
    beam_size: int = field(default_factory=lambda: _int("SAFINUM_BEAM", 4))
    max_decoding_length: int = field(default_factory=lambda: _int("SAFINUM_MAX_LEN", 160))
    no_repeat_ngram_size: int = 3
    repetition_penalty: float = 1.1
    inter_threads: int = field(default_factory=lambda: _int("SAFINUM_INTER_THREADS", 2))

    # --- Jetons envoyés au modèle ----------------------------------------
    # native = ⟦M1⟧ (format du module 1) | square = [[M1]] | brace = {M1} | alnum = QM1Q
    # numdash = NUM-1001 : meilleur taux de conservation mesuré sur le VRAI modèle
    # (75 %, contre 0 % pour ⟦M1⟧). Le moteur réessaie automatiquement un autre
    # format si un jeton disparaît (scripts/test_token_formats.py pour re-mesurer).
    token_format: str = field(default_factory=lambda: os.getenv("SAFINUM_TOKEN_FORMAT", "numdash"))
    token_retry_formats: tuple[str, ...] = ("num", "numdash", "square", "alnum", "native")

    # --- Politique de qualité --------------------------------------------
    allow_draft_memory: bool = field(default_factory=lambda: _bool("SAFINUM_ALLOW_DRAFT_MEMORY", False))
    allow_draft_glossary: bool = field(default_factory=lambda: _bool("SAFINUM_ALLOW_DRAFT_GLOSSARY", False))
    # Avertissements / erreurs (ctx.alert) : jamais de traduction automatique non validée.
    strict_alert: bool = field(default_factory=lambda: _bool("SAFINUM_STRICT_ALERT", True))
    # Textes anglais : le pivot anglais → français → ewondo est autorisé, mais marqué
    # « à relire ». Mettre 0 pour n'accepter que la mémoire/le glossaire validés.
    allow_pivot_mt: bool = field(default_factory=lambda: _bool("SAFINUM_ALLOW_PIVOT_MT", True))

    # Rétro-traduction : score chrF (0..1) minimal pour accepter. À calibrer (scripts/calibrate.py).
    min_bt_score: float = field(default_factory=lambda: _float("SAFINUM_MIN_BT", 0.40))
    min_bt_score_short: float = field(default_factory=lambda: _float("SAFINUM_MIN_BT_SHORT", 0.60))
    short_words: int = 3                 # en dessous : seuil « short »
    review_below: float = 0.65           # accepté mais marqué « à relire » sous ce score
    max_len_ratio: float = 3.5
    min_len_ratio: float = 0.25

    log_unseen: bool = True
    log_texts: bool = field(default_factory=lambda: _bool("SAFINUM_LOG_TEXTS", False))
    max_items: int = 100

    def pairs_for(self, lang: str) -> dict:
        if lang not in LANGUAGES:
            raise KeyError(lang)
        return LANGUAGES[lang]

    def model_pairs(self) -> list[str]:
        return all_model_pairs()


def supported_directions() -> list[dict]:
    """Directions à afficher dans /health et dans l'extension."""
    out = []
    for source in SOURCE_LANGUAGES:
        for target in TARGET_LANGUAGES:
            if source == target:
                continue
            try:
                path = direction_path(source, target)
            except KeyError:
                continue
            out.append({
                "source": source,
                "target": target,
                "path": path,
                "pivot": len(path) > 1,
            })
    return out
