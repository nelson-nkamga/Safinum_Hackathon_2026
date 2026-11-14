import { fetchLanguages, translateTexts } from "../services/translation-api";
import type { BackgroundMessage } from "../types/translation";

chrome.runtime.onMessage.addListener((msg: BackgroundMessage, _sender, sendResponse) => {
  let job: Promise<object>;
  if (msg.type === "TRANSLATE") {
    job = translateTexts(msg.texts, msg.source ?? null, msg.target).then((translations) => ({ translations }));
  } else if (msg.type === "LANGUAGES") {
    job = fetchLanguages().then((languages) => ({ languages }));
  } else {
    return false;
  }
  job
    .then((r) => sendResponse({ ok: true, ...r }))
    .catch((e: unknown) => sendResponse({ ok: false, error: e instanceof Error ? e.message : String(e) }));
  return true; // réponse asynchrone
});
