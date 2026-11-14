import { useCallback, useEffect, useRef, useState } from "react";
import LanguageSelector from "./components/LanguageSelector";
import TranslationStatus from "./components/TranslationStatus";
import TranslationToggle from "./components/TranslationToggle";
import UnderstandPanel from "./components/UnderstandPanel";
import { isApiReachable, requestLanguages } from "../services/translation-api";
import { sendToTab } from "../services/tab-messaging";
import type { Language, StepInfo, TabState } from "../types/translation";

const SOURCE_NAME = "Français";
const INCOMPATIBLE = "Page non compatible. Rechargez la page, puis rouvrez l'extension.";

export default function App() {
  const [tabId, setTabId] = useState<number | null>(null);
  const [languages, setLanguages] = useState<Language[]>([]);
  const [lang, setLang] = useState("");
  const [tabState, setTabState] = useState<TabState | null>(null);
  const [mock, setMock] = useState(true);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [view, setView] = useState<"controls" | "understand">("controls");
  const [step, setStep] = useState<StepInfo | null>(null);
  const busyRef = useRef(false);

  const loadLanguages = useCallback(async () => {
    // Dès que le backend (module 2) répond, on quitte automatiquement le mode
    // simulation : la case reste cochable si l'on veut tester sans API.
    if (await isApiReachable()) {
      const { mockMode } = await chrome.storage.local.get({ mockMode: true });
      if (mockMode) {
        await chrome.storage.local.set({ mockMode: false });
        setMock(false);
      }
    }
    const res = await requestLanguages();
    if (!res || !res.ok) {
      setLanguages([]);
      setLang("");
      setMessage((res && !res.ok && res.error) || "API injoignable. Activez le mode simulation pour tester.");
      return;
    }
    setLanguages(res.languages);
    const saved = String((await chrome.storage.local.get({ lang: "" })).lang);
    setLang(res.languages.some((l) => l.code === saved && l.available) ? saved : "");
  }, []);

  const refresh = useCallback(async () => {
    if (tabId === null || busyRef.current) return;
    const s = await sendToTab<TabState>(tabId, { type: "GET_STATE" });
    if (s) setTabState(s);
  }, [tabId]);

  const apply = useCallback(
    async (enabled: boolean, nextLang: string, force = false) => {
      if (tabId === null || busyRef.current) return;
      if (enabled && !nextLang) {
        setMessage("Choisissez d'abord une langue.");
        return;
      }
      setMessage("");
      busyRef.current = true;
      setBusy(true);
      if (nextLang) await chrome.storage.local.set({ lang: nextLang });
      const s = await sendToTab<TabState>(tabId, { type: "SET_STATE", enabled, lang: nextLang || null, force });
      busyRef.current = false;
      setBusy(false);
      if (s) setTabState(s);
      else setMessage(INCOMPATIBLE);
    },
    [tabId]
  );

  const loadStep = useCallback(async () => {
    if (tabId === null) return;
    const info = await sendToTab<StepInfo>(tabId, { type: "GET_STEP_INFO" });
    setStep(info);
    if (!info) setMessage(INCOMPATIBLE);
  }, [tabId]);

  useEffect(() => {
    (async () => {
      const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
      setTabId(tab?.id ?? null);
      const { mockMode } = await chrome.storage.local.get({ mockMode: true });
      setMock(Boolean(mockMode));
      await loadLanguages();
    })();
  }, [loadLanguages]);

  // Suit les contenus dynamiques tant que le popup est ouvert.
  useEffect(() => {
    refresh();
    const id = setInterval(refresh, 1500);
    return () => clearInterval(id);
  }, [refresh]);

  const enabled = tabState?.enabled ?? false;
  const headline = busy
    ? "Traduction en cours…"
    : enabled
      ? `${SOURCE_NAME} → ${languages.find((l) => l.code === tabState?.lang)?.name ?? tabState?.lang}`
      : "Traduction désactivée";

  return (
    <main>
      <header>
        <h1>SAFINUM Langues</h1>
        <p className="muted" aria-live="polite">{headline}</p>
      </header>

      {view === "controls" ? (
        <>
          <TranslationToggle checked={enabled} disabled={busy} onChange={(c) => apply(c, lang)} />
          <LanguageSelector
            languages={languages}
            value={lang}
            disabled={busy}
            onChange={(code) => {
              setLang(code);
              if (enabled && code) apply(true, code);
            }}
          />
          <TranslationStatus state={tabState} />
          <p className="msg" role="status">{message}</p>

          <div className="actions">
            <button
              type="button"
              disabled={tabId === null}
              onClick={async () => {
                setMessage("");
                const s = tabId !== null ? await sendToTab<TabState>(tabId, { type: "RESTORE" }) : null;
                if (s) setTabState(s);
                else setMessage(INCOMPATIBLE);
              }}
            >
              Restaurer l'original
            </button>
            <button
              type="button"
              className="primary"
              disabled={tabId === null}
              onClick={async () => {
                setMessage("");
                setView("understand");
                await loadStep();
              }}
            >
              Comprendre cette étape
            </button>
          </div>

          <label className="mock">
            <input
              type="checkbox"
              checked={mock}
              onChange={async (e) => {
                setMock(e.target.checked);
                await chrome.storage.local.set({ mockMode: e.target.checked });
                setMessage("");
                await loadLanguages();
                if (enabled) apply(true, lang, true);
              }}
            />
            <span>Mode simulation (sans API) : les textes sont préfixés [SIM]</span>
          </label>
        </>
      ) : (
        <UnderstandPanel info={step} onRefresh={loadStep} onClose={() => setView("controls")} />
      )}
    </main>
  );
}
