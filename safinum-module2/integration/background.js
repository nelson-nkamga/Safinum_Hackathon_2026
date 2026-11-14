// Service worker de l'extension : relaie les textes masqués du module 1 vers l'API locale (module 2).
// Pourquoi un service worker : un content script soumis aux règles CORS de la page https://safinum.cm
// ne devrait pas appeler http://127.0.0.1 directement ; le service worker, lui, a des host_permissions.
const API = 'http://127.0.0.1:8000';

chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  if (!msg || msg.type !== 'sl-translate') return false;
  fetch(API + '/translate', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ lang: msg.lang, items: msg.items }),
  })
    .then((r) => (r.ok ? r.json() : Promise.reject(new Error('HTTP ' + r.status))))
    .then((data) => sendResponse({ ok: true, results: data.results }))
    .catch((e) => sendResponse({ ok: false, error: String(e) }));
  return true; // réponse asynchrone
});
