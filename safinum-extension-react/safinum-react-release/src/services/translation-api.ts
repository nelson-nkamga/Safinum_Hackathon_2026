// Service de communication avec le backend (membre 2).
// - côté service worker : translateTexts / fetchLanguages (fetch)
// - côté content script et popup : requestTranslation / requestLanguages (messages d'extension)
import type {
  ApiResponse, BackgroundMessage, Language, TextItem, TranslationResult
} from "../types/translation";

const API_BASE = "http://localhost:8000"; // si changé, mettre à jour host_permissions dans public/manifest.json
// Le premier appel charge les modèles Marian en mémoire (~1 min à froid) : délai large.
const TIMEOUT_MS = 90000;
const MAX_BATCH = 50;

const MOCK_LANGUAGES: Language[] = [
  { code: "ewondo", name: "Ewondo", available: true },
  { code: "duala", name: "Duala", available: true },
  { code: "bassa", name: "Bassa", available: true }
];

async function callApi<T>(path: string, init?: RequestInit): Promise<T> {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), TIMEOUT_MS);
  try {
    const res = await fetch(API_BASE + path, {
      ...init,
      headers: { "Content-Type": "application/json" },
      signal: ctrl.signal
    });
    if (!res.ok) throw new Error("API : HTTP " + res.status);
    return (await res.json()) as T;
  } catch (e) {
    if (e instanceof DOMException && e.name === "AbortError") throw new Error("API : délai dépassé");
    throw new Error("API injoignable (" + (e instanceof Error ? e.message : String(e)) + ")");
  } finally {
    clearTimeout(timer);
  }
}

async function isMockMode(): Promise<boolean> {
  const { mockMode } = await chrome.storage.local.get({ mockMode: true });
  return Boolean(mockMode);
}

// Le backend (module 2) est-il joignable ? Utilisé pour désactiver le mode
// simulation automatiquement dès que le vrai moteur tourne.
export async function isApiReachable(): Promise<boolean> {
  try {
    await callApi<{ languages: Language[] }>("/languages");
    return true;
  } catch {
    return false;
  }
}

// --- Service worker ---

export async function translateTexts(texts: TextItem[], source: string | null, target: string): Promise<TranslationResult[]> {
  if (await isMockMode()) {
    return texts.map((t) => {
      const normalized = String(t.text ?? "");
      const translated = normalized.includes("[SIM]") ? normalized : "[SIM] " + normalized;
      return { id: t.id, original: t.text, translated, status: "mock" as const };
    });
  }
  const out: TranslationResult[] = [];
  for (let i = 0; i < texts.length; i += MAX_BATCH) {
    const batch = texts.slice(i, i + MAX_BATCH);
    // `source` n'est PAS imposé ici : le backend utilise la langue détectée par le
    // module 1 sur chaque item (fr / en), le français restant la valeur par défaut.
    const body: Record<string, unknown> = { texts: batch, target_language: target };
    if (source) body.source_language = source;
    const data = await callApi<{ translations: TranslationResult[] }>("/translate", {
      method: "POST",
      body: JSON.stringify(body)
    });
    out.push(...data.translations);
  }
  return out;
}

export async function fetchLanguages(): Promise<Language[]> {
  if (await isMockMode()) return MOCK_LANGUAGES;
  return (await callApi<{ languages: Language[] }>("/languages")).languages;
}

// --- Content script / popup ---

const send = <T>(msg: BackgroundMessage) => chrome.runtime.sendMessage(msg) as Promise<ApiResponse<T>>;

export const requestTranslation = (texts: TextItem[], source: string, target: string) =>
  send<{ translations: TranslationResult[] }>({ type: "TRANSLATE", texts, source, target });

export const requestLanguages = () => send<{ languages: Language[] }>({ type: "LANGUAGES" });
