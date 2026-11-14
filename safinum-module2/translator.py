"""Livrable 3 : moteur Marian (CTranslate2).

Le dépôt flagship-ai/cameroon-int8 contient un dossier par direction de traduction
(`francais-ewondo`, `ewondo-francais`, `english-francais`, `francais-english`).
Ce projet n'active qu'une langue nationale : l'ewondo. Les textes anglais passent
par le pivot français (anglais → français → ewondo, et l'inverse).

Ce fichier contient :
 - MTBackend : interface (permet de tester sans le modèle) ;
 - CT2MarianBackend : implémentation réelle, qui reprend l'exemple de la fiche du modèle ;
 - Translator : encode/décode les jetons, découpe en phrases, enchaîne les directions
   et réessaie un autre format de jeton si le modèle en a perdu.
"""
from __future__ import annotations

import logging
import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

from config import LANGUAGES, Settings, direction_path
from textutil import TokenCodec, find_tokens, split_sentences

log = logging.getLogger("safinum.translator")


@dataclass
class MTOutput:
    text: str
    score: float | None = None      # score CTranslate2 de la meilleure hypothèse (indicatif)


class MTBackend(ABC):
    @abstractmethod
    def translate(self, pair: str, texts: list[str]) -> list[MTOutput]: ...

    @abstractmethod
    def has_pair(self, pair: str) -> bool: ...


class CT2MarianBackend(MTBackend):
    """Charge les directions à la demande (un dossier du dépôt = une direction)."""

    def __init__(self, settings: Settings):
        self.s = settings
        self._models: dict[str, tuple] = {}
        self._lock = threading.Lock()
        self._remote_pairs: set[str] | None = None
        self.load_errors: dict[str, str] = {}

    # -- disponibilité ------------------------------------------------------
    def has_pair(self, pair: str) -> bool:
        if self.s.models_dir:
            return (Path(self.s.models_dir) / pair / "model.bin").exists()
        if self._remote_pairs is None:
            try:
                from huggingface_hub import list_repo_files
                files = list_repo_files(self.s.hf_repo)
                self._remote_pairs = {f.split("/")[0] for f in files if f.endswith("/model.bin")}
            except Exception as exc:  # hors ligne : on suppose présent, l'erreur viendra au chargement
                log.warning("liste des directions indisponible (%s)", exc)
                return True
        return pair in self._remote_pairs

    def loaded_pairs(self) -> list[str]:
        return sorted(self._models)

    # -- chargement ---------------------------------------------------------
    def _path(self, pair: str) -> str:
        if self.s.models_dir:
            return str(Path(self.s.models_dir) / pair)
        from huggingface_hub import snapshot_download
        local = snapshot_download(repo_id=self.s.hf_repo, allow_patterns=[f"{pair}/*"])
        return str(Path(local) / pair)

    def _load(self, pair: str):
        with self._lock:
            if pair not in self._models:
                import ctranslate2
                from transformers import MarianTokenizer
                path = self._path(pair)
                log.info("chargement de %s depuis %s", pair, path)
                tokenizer = MarianTokenizer.from_pretrained(path)
                try:
                    translator = ctranslate2.Translator(
                        path,
                        device=self.s.device,
                        compute_type=self.s.compute_type,
                        inter_threads=self.s.inter_threads,
                    )
                except TypeError:       # ancienne version / faux moteur de test
                    translator = ctranslate2.Translator(
                        path, device=self.s.device, compute_type=self.s.compute_type,
                    )
                self._models[pair] = (tokenizer, translator)
                self.load_errors.pop(pair, None)
            return self._models[pair]

    def warmup(self, pairs: list[str]) -> dict[str, str]:
        """Charge les directions demandées. Retourne {direction: erreur} pour les échecs."""
        errors: dict[str, str] = {}
        for p in pairs:
            if not self.has_pair(p):
                errors[p] = "model.bin absent"
                continue
            try:
                self._load(p)
            except Exception as exc:       # modèle corrompu, lib manquante, mémoire insuffisante…
                errors[p] = f"{type(exc).__name__}: {exc}"
                self.load_errors[p] = errors[p]
                log.exception("chargement impossible de %s", p)
        return errors

    # -- traduction ---------------------------------------------------------
    def translate(self, pair: str, texts: list[str]) -> list[MTOutput]:
        if not texts:
            return []
        tokenizer, translator = self._load(pair)
        sources = [tokenizer.convert_ids_to_tokens(tokenizer.encode(t)) for t in texts]
        results = translator.translate_batch(
            sources,
            beam_size=self.s.beam_size,
            max_decoding_length=self.s.max_decoding_length,
            no_repeat_ngram_size=self.s.no_repeat_ngram_size,
            repetition_penalty=self.s.repetition_penalty,
            return_scores=True,
        )
        out: list[MTOutput] = []
        for r in results:
            hyp = r.hypotheses[0]
            text = tokenizer.decode(tokenizer.convert_tokens_to_ids(hyp), skip_special_tokens=True)
            score = r.scores[0] if getattr(r, "scores", None) else None
            out.append(MTOutput(text=text.strip(), score=score))
        return out


class Translator:
    """Traduit des textes déjà protégés (jetons natifs ⟦…⟧) et renvoie des textes à jetons natifs."""

    def __init__(self, backend: MTBackend, settings: Settings):
        self.backend = backend
        self.s = settings
        self.codec = TokenCodec(settings.token_format)

    # -- disponibilité ------------------------------------------------------
    def has_pair(self, pair: str) -> bool:
        return self.backend.has_pair(pair)

    def has_direction(self, source: str, target: str) -> bool:
        try:
            path = direction_path(source, target)
        except KeyError:
            return False
        return all(self.backend.has_pair(p) for p in path)

    def has_local_direction(self, lang: str) -> bool:
        """Compatibilité : français ↔ langue locale."""
        return self.has_direction("fr", lang) and self.has_direction(lang, "fr")

    def has_en_pivot(self) -> bool:
        return self.backend.has_pair(LANGUAGES["ewondo"]["en_to"])

    def direction_status(self) -> dict[str, dict]:
        out: dict[str, dict] = {}
        for code, meta in LANGUAGES.items():
            out[code] = {
                "label": meta["label"],
                "fr_to_local": self.backend.has_pair(meta["fr_to"]),
                "local_to_fr": self.backend.has_pair(meta["to_fr"]),
                "en_to_local": self.backend.has_pair(meta["en_to"]) and self.backend.has_pair(meta["fr_to"]),
                "local_to_en": self.backend.has_pair(meta["to_fr"]) and self.backend.has_pair(meta["to_en"]),
            }
        return out

    # -- formats de jetons --------------------------------------------------
    def _candidate_codecs(self) -> list[TokenCodec]:
        names: list[str] = []
        for fmt in (self.codec.fmt, *self.s.token_retry_formats, "native"):
            if fmt in TokenCodec.FORMATS and fmt not in names:
                names.append(fmt)
        return [TokenCodec(fmt) for fmt in names]

    def _backend_call(self, pair: str, texts: list[str], codec: TokenCodec) -> list[MTOutput]:
        encoded = [codec.encode(t) for t in texts]
        outs = self.backend.translate(pair, encoded)
        if len(outs) != len(texts):
            raise RuntimeError(f"{pair} : {len(outs)} sorties pour {len(texts)} entrées")
        return [MTOutput(codec.decode(o.text), o.score) for o in outs]

    def _translate_flat(self, pair: str, texts: list[str]) -> list[MTOutput]:
        """Traduit une liste de phrases ; si un jeton disparaît, essaie un autre format.

        Le format choisi par défaut (numérique) est celui que le modèle Marian réel
        conserve le mieux. Les phrases sans jeton passent du premier coup.
        """
        pending = list(range(len(texts)))
        results: list[MTOutput | None] = [None] * len(texts)
        last: list[MTOutput | None] = [None] * len(texts)

        for codec in self._candidate_codecs():
            if not pending:
                break
            subset = [texts[i] for i in pending]
            try:
                outs = self._backend_call(pair, subset, codec)
            except Exception:
                if codec.fmt == self.codec.fmt:
                    raise
                log.warning("nouvel essai avec le format %s impossible", codec.fmt, exc_info=True)
                continue
            still: list[int] = []
            for i, out in zip(pending, outs):
                last[i] = out
                if out.text.strip() and find_tokens(out.text) == find_tokens(texts[i]):
                    results[i] = out
                else:
                    still.append(i)
            pending = still
        for i in range(len(texts)):
            if results[i] is None:
                results[i] = last[i] or MTOutput("")
        return [r for r in results if r is not None]

    # -- phrases ------------------------------------------------------------
    def _run(self, pair: str, texts: list[str]) -> list[MTOutput]:
        # 1 texte → n phrases (le modèle est plus fiable phrase par phrase)
        flat: list[str] = []
        spans: list[tuple[int, int]] = []
        for t in texts:
            parts = split_sentences(t)
            spans.append((len(flat), len(flat) + len(parts)))
            flat.extend(parts)
        outs = self._translate_flat(pair, flat)
        merged: list[MTOutput] = []
        for a, b in spans:
            chunk = outs[a:b]
            text = " ".join(o.text for o in chunk).strip()
            scores = [o.score for o in chunk if o.score is not None]
            merged.append(MTOutput(text=text, score=min(scores) if scores else None))
        return merged

    # -- directions ---------------------------------------------------------
    def translate_path(self, source: str, target: str, texts: list[str]) -> list[MTOutput]:
        """Traduit dans une direction quelconque, en enchaînant les pivots si besoin."""
        if source == target:
            return [MTOutput(t) for t in texts]
        path = direction_path(source, target)
        current = list(texts)
        min_score: float | None = None
        for pair in path:
            outs = self._run(pair, current)
            current = [o.text for o in outs]
            scores = [o.score for o in outs if o.score is not None]
            if scores:
                s = min(scores)
                min_score = s if min_score is None else min(min_score, s)
        return [MTOutput(t, min_score) for t in current]

    def translate_direction(self, source: str, target: str, texts: list[str]) -> list[MTOutput]:
        return self.translate_path(source, target, texts)

    # -- compatibilité avec l'ancienne API du module ------------------------
    def translate(self, lang: str, texts: list[str]) -> list[MTOutput]:
        return self.translate_path("fr", lang, texts)

    def back_translate(self, lang: str, texts: list[str]) -> list[MTOutput]:
        return self.translate_path(lang, "fr", texts)

    def en_to_fr(self, texts: list[str]) -> list[MTOutput]:
        return self.translate_path("en", "fr", texts)
