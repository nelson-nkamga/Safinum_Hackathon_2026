// Content script (à charger APRÈS observer.js et à la place du faux moteur de demo.js).
// Branche l'API de traduction sur le module 1 :
//   payloads du module 1 → service worker → POST /translate → résultats → module 1
(function (root) {
  const L = root.SafinumLang;
  if (!L || !L.observer) return;
  L.targetLang = L.targetLang || 'ewondo';   // 'ewondo' | 'bulu' ; à brancher sur le sélecteur de langue (module 3)

  L.observer.setTransport(async (payloads) => {
    const res = await chrome.runtime.sendMessage({ type: 'sl-translate', lang: L.targetLang, items: payloads });
    if (!res || !res.ok) throw new Error((res && res.error) || 'API injoignable'); // → français conservé
    // status "fallback"/"rejected" : le moteur renvoie le texte masqué d'origine → l'écran ne change pas
    return res.results.map((r) => ({ id: r.id, text: r.text }));
  });
})(globalThis);
