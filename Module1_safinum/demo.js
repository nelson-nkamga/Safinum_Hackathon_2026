/*!
 * SAFINUM Langues — Module 1 : demo.js (BANC D'ESSAI, pas un livrable final)
 * ---------------------------------------------------------------------------
 * Branche extractor + privacy + observer sur le site de test avec un
 * « faux moteur de traduction » local : il préfixe chaque texte par "[ew] "
 * et conserve les jetons. Il permet de vérifier, sans le vrai moteur, que :
 *   - les textes sont extraits à chaque écran,
 *   - les données sensibles ne sortent JAMAIS (voir outbox / leakScan),
 *   - les valeurs d'origine reviennent exactement à l'écran après « traduction ».
 *
 * Le module 2/3 remplace `mockTransport` par l'appel réel :
 *   SafinumLang.observer.setTransport(async (payloads) => [{ id, text }, ...])
 *
 * Console : sélectionner le contexte de l'extension dans le menu déroulant
 * « top ▾ » des DevTools pour accéder à SafinumLang.
 */
(function (root) {
  'use strict';
  const L = root.SafinumLang;
  if (!L || !L.observer) return;

  const demo = {
    latencyMs: 40,   // latence simulée
    failRate: 0,     // 0..1 : probabilité que le « moteur » perde les jetons d'un texte
    outbox: [],      // tout ce qui est « envoyé » (textes masqués uniquement)
  };

  async function mockTransport(payloads) {
    for (const p of payloads) {
      const check = L.privacy.assertSafe(p.text);
      if (!check.safe) console.error('[SafinumLang] FUITE détectée avant envoi', p.id, check.leaks);
      demo.outbox.push({ id: p.id, text: p.text, lang: p.lang, ctx: p.ctx });
    }
    await new Promise((r) => setTimeout(r, demo.latencyMs));
    return payloads.map((p) => ({
      id: p.id,
      text: Math.random() < demo.failRate ? p.text.replace(/⟦[A-Z]\d+⟧/g, '') : '[ew] ' + p.text,
    }));
  }

  L.observer.start({
    transport: mockTransport,
    onFallback: (seg, report) => console.warn('[SafinumLang] jeton perdu → français conservé :', seg.core, report),
    onBlocked: (seg) => console.error('[SafinumLang] envoi bloqué (donnée sensible) :', seg.id),
  });

  L.demo = demo;
  L.debug = {
    /** Tableau des 30 derniers textes « envoyés ». */
    report() { console.table(demo.outbox.slice(-30).map((o) => ({ id: o.id, texte_envoyé: o.text, étape: o.ctx.step, alerte: o.ctx.alert }))); },
    /** Compteurs : extraits, traduits, ignorés car déjà vus, replis, bloqués… */
    stats() { const s = L.observer.stats(); console.log(JSON.stringify(s, null, 2)); return s; },
    /** Vérifie qu'aucune valeur donnée n'est jamais sortie. leakScan(['25 000','Mbarga']) → [] attendu. */
    leakScan(values) { return demo.outbox.filter((o) => (values || []).some((v) => o.text.includes(v))); },
    /** Revient au français / relance la traduction. */
    revert() { return L.observer.setEnabled(false); },
    apply() { return L.observer.setEnabled(true); },
  };

  console.log('[SafinumLang] Module 1 actif. Essayez SafinumLang.debug.report() / stats() / leakScan([...]).');
})(typeof globalThis !== 'undefined' ? globalThis : this);
