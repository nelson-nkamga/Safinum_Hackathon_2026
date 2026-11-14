/*!
 * SAFINUM Langues — Module 1 / Livrable 3 : observer.js
 * ---------------------------------------------------------------------------
 * Rôle : détecter les nouveaux contenus affichés par SAFINUM (site Inertia/Vue :
 * les étapes Solde → Frais → Bénéficiaire → Récapitulatif → Confirmation
 * changent sans recharger la page) et faire passer chaque nouveau texte par le
 * pipeline :
 *
 *   MutationObserver → extractor.collect() → toPayload() (masqué + contrôlé)
 *     → transport(payloads)  [fourni par le module 2/3 : API de traduction]
 *     → privacy.validate() → privacy.restore() → extractor.apply()
 *
 * Points d'attention :
 *  - anti-boucle : nos propres écritures sont ignorées (on déconnecte
 *    l'observateur pendant l'écriture ET la signature de contenu du nœud
 *    reconnaît le texte qu'on vient d'écrire) ;
 *  - Vue peut réécrire un nœud en place : le nœud est ré-extrait seulement si
 *    son contenu a réellement changé ;
 *  - si la traduction a perdu un jeton (montant, numéro…), on garde le français.
 *
 * Dépend de : privacy.js, extractor.js (chargés avant).
 */
(function (root) {
  'use strict';

  const NS = (root.SafinumLang = root.SafinumLang || {});
  const privacy = NS.privacy;
  const extractor = NS.extractor;
  if (!privacy || !extractor) {
    throw new Error('[SafinumLang] privacy.js et extractor.js doivent être chargés avant observer.js');
  }

  const defaults = {
    root: null,            // défaut : document.body
    debounceMs: 120,       // regroupe les rafales de mutations
    batchSize: 40,         // nombre max de textes par appel au transport
    transport: null,       // async (payloads) => [{id, text}] — fourni par le module de traduction
    onSegments: null,      // (segments) => void — tous les segments extraits (débogage / module 3)
    onApplied: null,       // (segment, texteTraduit) => void
    onFallback: null,      // (segment, rapportValidation) => void — jeton perdu : français conservé
    onBlocked: null,       // (segment) => void — donnée sensible détectée : envoi annulé
    watchInputs: true,     // apprend les noms/téléphones saisis (lecture seule, mémoire locale)
    rescanOnClickMs: 250,  // filet de sécurité après un clic
  };

  const st = {
    mutations: 0, flushes: 0, segments: 0, batches: 0,
    translated: 0, fallback: 0, blockedUnsafe: 0, stale: 0, errors: 0,
  };

  let cfg = null;
  let mo = null;
  let timer = null;
  let enabled = true;
  let obsOptions = null;
  const pending = new Set();
  const listeners = [];

  // ───────────────────────────── Mutations ──────────────────────────────────
  function queue(n) {
    if (n && (n.nodeType === 1 || n.nodeType === 3)) pending.add(n);
  }

  function ingest(records) {
    st.mutations += records.length;
    for (const r of records) {
      if (r.type === 'childList') r.addedNodes.forEach(queue);
      else queue(r.target); // characterData (Text) ou attributes (Element)
    }
    schedule();
  }

  function schedule() {
    if (timer) return;
    timer = setTimeout(flush, cfg.debounceMs);
  }

  // Retire les nœuds déjà couverts par un ancêtre de la file, et les nœuds détachés.
  function prune(nodes) {
    const set = new Set(nodes);
    return nodes.filter((n) => {
      if (!n.isConnected) return false;
      for (let p = n.parentNode; p; p = p.parentNode) if (set.has(p)) return false;
      return true;
    });
  }

  function flush() {
    timer = null;
    st.flushes++;
    const nodes = prune([...pending]);
    pending.clear();
    if (!nodes.length) return;
    process(nodes, false).catch(() => { st.errors++; });
  }

  async function process(nodes, force) {
    const segs = [];
    for (const n of nodes) {
      if (n.isConnected) segs.push(...extractor.collect(n, { force }));
    }
    if (!segs.length) return;
    st.segments += segs.length;
    if (cfg.onSegments) { try { cfg.onSegments(segs); } catch (_) { /* callback tiers */ } }
    if (!enabled || !cfg.transport) return;
    await translate(segs);
  }

  // ───────────────────────────── Pipeline ───────────────────────────────────
  function normalizeResults(results) {
    const map = new Map();
    if (Array.isArray(results)) results.forEach((r) => r && map.set(r.id, r));
    else if (results && typeof results === 'object') {
      Object.keys(results).forEach((id) => {
        const v = results[id];
        map.set(id, typeof v === 'string' ? { id, text: v } : v);
      });
    }
    return map;
  }

  async function translate(segs) {
    const todo = [];
    const payloads = [];
    for (const s of segs) {
      if (!s.translatable) continue;
      const p = extractor.toPayload(s);
      if (!p) continue;
      if (p.blocked) {
        st.blockedUnsafe++;
        if (cfg.onBlocked) { try { cfg.onBlocked(s); } catch (_) { /* callback tiers */ } }
        continue; // jamais envoyé
      }
      todo.push(s);
      payloads.push(p);
    }
    for (let i = 0; i < payloads.length; i += cfg.batchSize) {
      const pChunk = payloads.slice(i, i + cfg.batchSize);
      const sChunk = todo.slice(i, i + cfg.batchSize);
      let results;
      try {
        results = await cfg.transport(pChunk);
        st.batches++;
      } catch (_) {
        st.errors++;
        continue; // français conservé
      }
      const byId = normalizeResults(results);
      withPaused(() => {
        for (const s of sChunk) {
          const r = byId.get(s.id);
          if (!r || typeof r.text !== 'string') { st.fallback++; continue; }
          const report = privacy.validate(s.masked, r.text, s.vault);
          if (!report.ok) {
            st.fallback++;
            if (cfg.onFallback) { try { cfg.onFallback(s, report); } catch (_) { /* callback tiers */ } }
            continue;
          }
          const finalText = privacy.restore(r.text, s.vault);
          if (extractor.apply(s, finalText)) {
            st.translated++;
            if (cfg.onApplied) { try { cfg.onApplied(s, finalText); } catch (_) { /* callback tiers */ } }
          } else st.stale++;
        }
      });
    }
  }

  // Écrit dans le DOM sans que l'observateur ne voie nos propres changements.
  function withPaused(fn) {
    if (!mo) return fn();
    const rec = mo.takeRecords();   // ne pas perdre les mutations de Vue déjà en attente
    if (rec.length) ingest(rec);
    mo.disconnect();
    try { return fn(); } finally { mo.observe(cfg.root, obsOptions); }
  }

  // ───────────────────────────── Écouteurs ──────────────────────────────────
  function listen(target, type, fn, opts) {
    target.addEventListener(type, fn, opts);
    listeners.push([target, type, fn, opts]);
  }

  function rescanSoon(delay) {
    setTimeout(() => { if (cfg) { pending.add(cfg.root); schedule(); } }, delay || 0);
  }

  // Apprend les valeurs saisies (LECTURE SEULE, mémoire locale) pour pouvoir les
  // masquer si le site les réaffiche plus tard dans une phrase.
  function onInput(e) {
    const el = e.target;
    if (!el || (el.localName !== 'input' && el.localName !== 'textarea')) return;
    if (el.type === 'password') return;
    const v = (el.value || '').trim();
    if (v.length < 3) return;
    if (el.type === 'tel') { privacy.registerSensitive(v, 'phone'); return; }
    const kind = extractor.kindFromLabel(extractor.labelOfControl(el));
    if (kind === 'name' || kind === 'phone' || kind === 'email' || kind === 'account') {
      privacy.registerSensitive(v, kind);
    }
  }

  // ───────────────────────────── API publique ───────────────────────────────
  function start(options) {
    if (mo) stop();
    cfg = Object.assign({}, defaults, options || {});
    cfg.root = cfg.root || root.document.body;
    obsOptions = {
      childList: true,
      subtree: true,
      characterData: true,
      attributes: true,
      attributeFilter: extractor.config.attributes.slice(),
    };
    enabled = true;
    mo = new root.MutationObserver(ingest);
    mo.observe(cfg.root, obsOptions);

    // Navigation Inertia / historique : re-scan complet (les textes inchangés sont ignorés).
    const d = root.document;
    ['inertia:navigate', 'inertia:success', 'inertia:finish'].forEach((ev) => listen(d, ev, () => rescanSoon(30)));
    listen(root, 'popstate', () => rescanSoon(30));
    listen(root, 'hashchange', () => rescanSoon(30));
    if (cfg.rescanOnClickMs) listen(d, 'click', () => rescanSoon(cfg.rescanOnClickMs), { capture: true, passive: true });
    if (cfg.watchInputs) {
      listen(d, 'input', onInput, { capture: true, passive: true });
      listen(d, 'change', onInput, { capture: true, passive: true });
    }

    pending.add(cfg.root); // scan initial
    schedule();
    return api;
  }

  function stop() {
    if (mo) { mo.disconnect(); mo = null; }
    if (timer) { clearTimeout(timer); timer = null; }
    listeners.splice(0).forEach(([t, ty, fn, o]) => t.removeEventListener(ty, fn, o));
    pending.clear();
  }

  /** Force un re-scan (force=true : ré-extrait aussi les textes déjà vus). */
  function scan(force) {
    if (!cfg) return Promise.resolve();
    return process([cfg.root], !!force);
  }

  /** false → revient au français et suspend la traduction ; true → relance. */
  function setEnabled(on) {
    enabled = !!on;
    if (!cfg) return Promise.resolve();
    if (!enabled) { withPaused(() => extractor.revertAll(cfg.root)); return Promise.resolve(); }
    return process([cfg.root], true);
  }

  function setTransport(fn) { if (cfg) cfg.transport = fn; return api; }

  const getStats = () => Object.assign({}, st, { extractor: extractor.stats(), pending: pending.size });

  const api = { start, stop, scan, setEnabled, setTransport, withPaused, stats: getStats, flush };
  NS.observer = api;
})(typeof globalThis !== 'undefined' ? globalThis : this);
