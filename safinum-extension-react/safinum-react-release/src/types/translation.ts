// Contrat commun entre les trois modules (à valider avec les membres 1 et 2).

export type TranslationStatus =
  | "human_validated"
  | "model_generated"
  | "mock"
  | "pending"
  | "unavailable"
  | "error";

export interface TextItem {
  id: string;
  text: string;
  /** Langue détectée par le module 1 : 'fr' | 'en' | null (null = français). */
  lang?: string | null;
  /** Contexte du segment (tag, alert, step…) : sert aux règles de sécurité du module 2. */
  ctx?: Record<string, unknown>;
}

export interface TranslationResult {
  id: string;
  original: string;
  translated: string;
  status: TranslationStatus;
  warning?: string;
}

export interface Language { code: string; name: string; available: boolean }

export type Stats = Record<TranslationStatus, number>;

export interface TabState { enabled: boolean; lang: string | null; stats: Stats }

// Panneau « Comprendre cette étape » : valeurs lues localement dans la page, jamais envoyées à l'API.
export interface StepInfo { stepId: string; values: Record<string, string | null> }

export interface TemplateField { key: string; label: string; labels: string[] }
export interface TemplateStep {
  id: string;
  title: string;
  intro: string;
  keywords: string[];
  fields: TemplateField[];
}
export interface Templates { notice: string; notIndicated: string; steps: TemplateStep[] }

// Popup -> content script
export type TabMessage =
  | { type: "GET_STATE" }
  | { type: "SET_STATE"; enabled: boolean; lang: string | null; force?: boolean }
  | { type: "RESTORE" }
  | { type: "GET_STEP_INFO" };

// Content script / popup -> service worker
export type BackgroundMessage =
  | { type: "TRANSLATE"; texts: TextItem[]; source?: string | null; target: string }
  | { type: "LANGUAGES" };

export type ApiResponse<T> = ({ ok: true } & T) | { ok: false; error: string };
