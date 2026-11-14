"""Livrable 5 : API de traduction (FastAPI + Pydantic).

Lancer :   uvicorn main:app --host 127.0.0.1 --port 8000
Docs :     http://127.0.0.1:8000/docs

Deux contrats sont acceptés sur POST /translate :

1) Contrat canonique (module 1 → module 2) :

   { "source": "fr", "target": "ewondo",
     "items": [ {"id": "sl1", "text": "Frais : ⟦M1⟧", "lang": "fr", "ctx": {...}} ] }

   → { "source": "fr", "target": "ewondo", "results": [ {...} ], "translations": [ {...} ] }

2) Ancien contrat de l'extension React (conservé pour compatibilité) :

   { "source_language": "fr", "target_language": "ewondo",
     "texts": [ {"id": "t1", "text": "Continuer"} ] }

`items` sont exactement les payloads produits par le module 1 (id, text masqué,
lang, ctx) ; la réponse contient `id` et `text` comme l'attend
`observer.setTransport(...)`. Le champ `translations` est la vue simplifiée
attendue par l'extension (id, original, translated, status, warning).
"""
from __future__ import annotations

import inspect
import logging
import os
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, model_validator

from config import (LANGUAGES, SOURCE_LANGUAGES, TARGET_LANGUAGES, Settings,
                    all_model_pairs, supported_directions)
from glossary import Glossary
from memory import TranslationMemory
from pipeline import Item, TranslationPipeline
from translator import CT2MarianBackend, MTBackend, Translator
from validator import Validator

log = logging.getLogger("safinum.api")


class ItemIn(BaseModel):
    id: str = Field(min_length=1, max_length=64)
    text: str = Field(max_length=2000)
    lang: Literal["fr", "en", "ewondo"] | None = None
    ctx: dict = Field(default_factory=dict)


class TranslateIn(BaseModel):
    # contrat canonique
    source: str | None = Field(default=None, description="fr | en | ewondo | auto")
    target: str | None = Field(default=None, description="ewondo | fr | en")
    items: list[ItemIn] | None = None

    # ancien contrat de l'extension (toléré)
    lang: str | None = Field(default=None, description="compatibilité : langue cible locale")
    source_language: str | None = None
    target_language: str | None = None
    texts: list[ItemIn | str] | None = None

    @model_validator(mode="after")
    def _normalize(self):
        target = self.target or self.target_language or self.lang
        source = self.source or self.source_language
        if source in ("", "auto", "detect"):
            source = None
        if self.items is None:
            if not self.texts:
                raise ValueError("fournir au moins un « item » ou un « texte »")
            converted: list[ItemIn] = []
            for i, t in enumerate(self.texts):
                if isinstance(t, str):
                    converted.append(ItemIn(id=f"t{i + 1}", text=t, lang=source))  # type: ignore[arg-type]
                else:
                    converted.append(t)
            self.items = converted
        if not self.items:
            raise ValueError("la liste de textes est vide")
        if target is None:
            raise ValueError("langue cible manquante : « target » (ou « lang »)")
        target = target.lower()
        source = source.lower() if isinstance(source, str) else None
        if target not in TARGET_LANGUAGES:
            raise ValueError(f"langue cible non prise en charge : {target} (choix : {', '.join(TARGET_LANGUAGES)})")
        if source is not None and source not in SOURCE_LANGUAGES:
            raise ValueError(f"langue source non prise en charge : {source} (choix : {', '.join(SOURCE_LANGUAGES)})")
        self.target, self.source = target, source
        return self

    @property
    def effective_target(self) -> str:
        return self.target or "ewondo"


class ResultOut(BaseModel):
    id: str
    text: str
    status: Literal["ok", "fallback", "passthrough", "rejected"]
    source: str
    confidence: float
    needs_review: bool
    reasons: list[str]
    back_translation: str | None = None


class LegacyResultOut(BaseModel):
    """Vue simplifiée consommée par le module 3 (extension React)."""
    id: str
    original: str
    translated: str
    status: Literal["human_validated", "model_generated", "mock", "pending", "unavailable", "error"]
    warning: str | None = None


class TranslateOut(BaseModel):
    lang: str | None = None
    source: str | None = None
    target: str
    results: list[ResultOut]
    translations: list[LegacyResultOut] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


def _legacy_status(r: ResultOut) -> str:
    if r.status == "ok":
        if r.source == "memory" and not r.needs_review:
            return "human_validated"
        return "model_generated"
    if r.status == "passthrough":
        return "unavailable"
    if r.status == "rejected":
        return "unavailable"
    return "unavailable"


def build_pipeline(settings: Settings, backend: MTBackend | None = None) -> TranslationPipeline:
    backend = backend or CT2MarianBackend(settings)
    translator = Translator(backend, settings)
    return TranslationPipeline(
        settings,
        TranslationMemory(settings.memory_path, settings.allow_draft_memory),
        Glossary(settings.glossary_path, settings.allow_draft_glossary),
        translator,
        Validator(settings, translator),
    )


def create_app(settings: Settings | None = None, backend: MTBackend | None = None) -> FastAPI:
    settings = settings or Settings()
    pipe = build_pipeline(settings, backend)
    app = FastAPI(title="SAFINUM — moteur de traduction français/anglais ↔ ewondo", version="1.0.0")
    app.state.pipeline = pipe

    # L'extension (page https://safinum.cm ou service worker) appelle l'API locale.
    cors = dict(
        allow_origin_regex=r"^(https://safinum\.cm|chrome-extension://[a-z]+|http://(localhost|127\.0\.0\.1)(:\d+)?)$",
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )
    # Chrome exige « Private Network Access » pour une page publique qui appelle localhost.
    if "allow_private_network" in inspect.signature(CORSMiddleware.__init__).parameters:
        cors["allow_private_network"] = True
        app.add_middleware(CORSMiddleware, **cors)
    else:  # Starlette ancien : on ajoute l'en-tête nous-mêmes
        app.add_middleware(CORSMiddleware, **cors)

        @app.middleware("http")
        async def private_network_access(request: Request, call_next):
            response = await call_next(request)
            if request.headers.get("access-control-request-private-network"):
                response.headers["Access-Control-Allow-Private-Network"] = "true"
            return response

    def model_status() -> dict:
        return {
            "repo": settings.hf_repo,
            "models_dir": settings.models_dir,
            "device": settings.device,
            "compute_type": settings.compute_type,
            "pairs": {p: pipe.translator.backend.has_pair(p) for p in all_model_pairs()},
            "loaded": (pipe.translator.backend.loaded_pairs()
                       if isinstance(pipe.translator.backend, CT2MarianBackend) else []),
        }

    @app.get("/")
    def root():
        return {
            "name": "SAFINUM traduction",
            "language": "ewondo",
            "directions": supported_directions(),
            "docs": "/docs",
        }

    @app.get("/health")
    def health():
        return {
            "status": "ok",
            "token_format": settings.token_format,
            "policy": {"allow_draft_memory": settings.allow_draft_memory,
                       "allow_draft_glossary": settings.allow_draft_glossary,
                       "strict_alert": settings.strict_alert, "allow_pivot_mt": settings.allow_pivot_mt,
                       "min_bt_score": settings.min_bt_score},
            "languages": pipe.translator.direction_status(),
            "directions": supported_directions(),
            "model": model_status(),
            "memory": pipe.memory.stats(),
            "glossary": pipe.glossary.stats(),
            "counters": pipe.stats(),
        }

    @app.get("/languages")
    def languages():
        out = []
        for code, meta in LANGUAGES.items():
            status = pipe.translator.direction_status()[code]
            out.append({
                "code": code,
                "name": meta["label"],
                "available": status["fr_to_local"] and status["local_to_fr"],
                "directions": status,
            })
        return {"languages": out, "directions": supported_directions()}

    @app.get("/model/status")
    def model_status_endpoint():
        return model_status()

    @app.post("/translate", response_model=TranslateOut)
    def translate(req: TranslateIn):
        target = req.effective_target
        if len(req.items) > settings.max_items:      # type: ignore[union-attr]
            raise HTTPException(status_code=413, detail=f"trop de textes (max {settings.max_items})")
        items = [Item(i.id, i.text, i.lang, i.ctx) for i in req.items]  # type: ignore[union-attr]
        results = pipe.translate_items(req.source, target, items)
        out_results = [ResultOut(**r.__dict__) for r in results]
        legacy = [
            LegacyResultOut(
                id=r.id,
                original=it.text,
                translated=r.text,
                status=_legacy_status(r),  # type: ignore[arg-type]
                warning="; ".join(r.reasons) or None,
            )
            for r, it in zip(out_results, items)
        ]
        return TranslateOut(
            lang=target if target in LANGUAGES else None,
            source=req.source,
            target=target,
            results=out_results,
            translations=legacy,
        )

    @app.post("/reload")
    def reload_data():
        """Recharge memory.json et glossary.json après une validation (sans redémarrer)."""
        pipe.memory.load()
        pipe.glossary.load()
        return {"memory": pipe.memory.stats(), "glossary": pipe.glossary.stats(),
                "memory_warnings": pipe.memory.warnings}

    if os.getenv("SAFINUM_WARMUP") == "1" and isinstance(pipe.translator.backend, CT2MarianBackend):
        errors = pipe.translator.backend.warmup(settings.model_pairs())
        if errors:
            log.warning("directions non chargées : %s", errors)
    return app


# En production : uvicorn main:app — le modèle ne se charge qu'au premier appel.
app = create_app() if os.getenv("SAFINUM_NO_AUTOSTART") != "1" else None
