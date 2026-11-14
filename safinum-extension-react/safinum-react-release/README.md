# SAFINUM Langues — module 3 (React + TypeScript, Manifest V3)

Suit la Directive technique SAFINUM :
- popup et panneau « Comprendre cette étape » : React + TypeScript (Vite)
- content script (`src/content`) et service worker (`src/background`) : TypeScript natif, sans React

## Construire et installer
1. `npm install` puis `npm run build` (deux builds : popup + service worker, puis content script en IIFE).
2. `chrome://extensions` → mode développeur → « Charger l'extension non empaquetée » → dossier `dist/`.
3. Page de test : `cd demo && python3 -m http.server 8080` → http://localhost:8080/safinum-test.html

Mode simulation activé par défaut (textes préfixés `[SIM]`, aucune vraie traduction).
Décocher pour utiliser l'API du membre 2 (`API_BASE` dans `src/services/translation-api.ts`, défaut http://localhost:8000).

## Contrat avec l'API (à valider avec les membres 1 et 2) — voir `src/types/translation.ts`
- `POST /translate` : `{ "texts": [{"id","text"}], "source_language": "fr", "target_language": "<code>" }`
  → `{ "translations": [{"id","original","translated","status","warning?"}] }`
- `GET /languages` → `{ "languages": [{"code","name","available"}] }`
- statuts : `human_validated`, `model_generated`, `unavailable`, `error` (`mock` = simulation locale)

## Structure
```
public/manifest.json, public/display.css
src/popup/{main.tsx, App.tsx, popup.css, components/{LanguageSelector,TranslationToggle,TranslationStatus,UnderstandPanel}.tsx}
src/content/{index.ts, display.ts, step-info.ts}
src/background/service-worker.ts
src/services/{translation-api.ts, tab-messaging.ts}
src/types/translation.ts
src/data/{templates.json, templates.ts}
```

## Garde-fous
- Aucun texte contenant un chiffre, un e-mail, un lien, ni une valeur placée après « Libellé : », n'est envoyé ni modifié.
- Aucune valeur de formulaire ni mot de passe n'est envoyé à l'API ; le panneau les lit localement, en lecture seule.
- « non indiqué » si une information est absente ; aucune opération exécutée.
- `display.ts` contient une extraction/protection minimale, à remplacer par les modules du membre 1.
- Restreindre `matches` (`<all_urls>`) à l'URL de SAFINUM dans `public/manifest.json` avant la démo.
