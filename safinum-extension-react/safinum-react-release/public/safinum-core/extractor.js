/*!
 * SAFINUM Langues — Module 1 / Livrable 1 : extractor.js
 * ---------------------------------------------------------------------------
 * Rôle : parcourir le DOM de SAFINUM, récupérer les textes à traduire
 * (titres, paragraphes, boutons, libellés, options, placeholder, aria-label,
 * title, alt), les masquer via privacy.js et les rendre sous forme de
 * « segments » prêts à être envoyés au moteur de traduction.
 *
 * Règles de sécurité (exigences 4 du cahier du Module 1) :
 *  - on ne LIT jamais .value : les valeurs saisies ne sont ni extraites ni
 *    modifiées ; on ne touche ni aux champs, ni aux cases, ni aux boutons
 *    (sauf leur TEXTE affiché), ni aux gestionnaires d'événements ;
 *  - on n'écrit que dans des nœuds texte et dans placeholder/aria-label/title/alt ;
 *  - un texte déjà traité n'est pas ré-extrait tant que son contenu n'a pas
 *    changé (WeakSet + signature de contenu, voir `unchanged()`).
 *
 * Dépend de : privacy.js (chargé avant).
 */
(function (root) {
  'use strict';

  const NS = (root.SafinumLang = root.SafinumLang || {});
  const privacy = NS.privacy;
  if (!privacy) throw new Error('[SafinumLang] privacy.js doit être chargé avant extractor.js');

  // ─────────────────────────── Configuration ────────────────────────────────
  const config = {
    // Attributs traduisibles (jamais "value" : voir règle de sécurité).
    attributes: ['placeholder', 'aria-label', 'title', 'alt'],
    // Balises dont le contenu n'est jamais traduit.
    skipTags: [
      'script', 'style', 'noscript', 'template', 'textarea', 'code', 'pre',
      'kbd', 'samp', 'svg', 'canvas', 'iframe', 'object', 'head', 'title',
      'meta', 'link',
    ],
    // Zones ignorées : balisage standard + notre propre interface.
    ignoreSelector:
      '[translate="no"], .notranslate, [data-sl-ignore], #safinum-lang-overlay, [data-safinum-lang-ui]',
  };

  // Valeur affichée dans un <dd> selon le libellé du <dt> voisin : on masque
  // TOUTE la valeur (même si le format n'est pas reconnu par les regex).
  const LABEL_RULES = [
    { re: /b[ée]n[ée]ficiaire|destinataire|recipient|beneficiary|payee|\bnom\b|\bname\b/i, kind: 'name' },
    { re: /t[ée]l[ée]phone|phone|mobile|portable|\btel\b/i, kind: 'phone' },
    { re: /r[ée]f[ée]rence|\bref\b|transaction id|n° de transaction/i, kind: 'reference' },
    { re: /e-?mail|courriel/i, kind: 'email' },
    { re: /\bcompte\b|account|\biban\b|\brib\b/i, kind: 'account' },
  ];

  // ─────────────────────────── État (WeakMap/WeakSet) ───────────────────────
  // Rien n'empêche le ramasse-miettes : Vue peut détruire des nœuds librement.
  const known = new WeakSet();          // nœuds déjà vus (WeakSet)
  const signatures = new WeakMap();     // Text → dernier contenu traité
  const attrSignatures = new WeakMap(); // Element → Map(attr → dernier contenu)
  const originals = new WeakMap();      // Text → texte français d'origine
  const attrOriginals = new WeakMap();  // Element → Map(attr → texte d'origine)

  const stats = {
    scanned: 0, extracted: 0, skippedSeen: 0, skippedEmpty: 0,
    withTokens: 0, forcedByLabel: 0, nameGuesses: 0,
  };
  let seq = 0;

  // ───────────────────────────── Utilitaires ────────────────────────────────
  const clean = (s) => String(s == null ? '' : s).replace(/[\u00A0\u202F\u2009]/g, ' ').replace(/\s+/g, ' ').trim();
  const hasLetters = (s) => /\p{L}{2,}/u.test(s);
  const doc = () => root.document;

  function isIgnored(el) {
    if (!el || el.nodeType !== 1) return false;
    if (config.skipTags.includes(el.localName)) return true;
    try {
      return !!el.closest(config.ignoreSelector) || !!el.closest('svg');
    } catch (_) { return false; }
  }

  // Initiales d'avatar / abréviations ("AN", "EN") : pas du texte à traduire.
  const isAbbreviation = (s) => /^[\p{Lu}]{1,3}$/u.test(s);

  function detectLang(text) {
    const t = ' ' + text.toLowerCase().replace(/[^\p{L}\s']/gu, ' ') + ' ';
    const score = (words) => words.reduce((n, w) => n + (t.includes(' ' + w + ' ') ? 1 : 0), 0);
    const fr = score(['le', 'la', 'les', 'des', 'du', 'de', 'un', 'une', 'et', 'est', 'pour', 'vous', 'votre', 'avec', 'sur', 'dans', 'avant', 'sans', 'ce', 'cette', 'ou', 'au', 'aux', 'pas', 'à', 'sont', 'ont', 'vos']);
    const en = score(['the', 'and', 'is', 'for', 'you', 'your', 'with', 'on', 'in', 'before', 'without', 'this', 'that', 'or', 'to', 'of', 'are', 'not', 'a', 'an', 'has', 'have', 'been']);
    if (fr === 0 && en === 0) return null;
    return fr >= en ? 'fr' : 'en';
  }

  function kindFromLabel(label) {
    if (!label) return null;
    const rule = LABEL_RULES.find((r) => r.re.test(label));
    return rule ? rule.kind : null;
  }

  // Libellé associé à un nœud texte : <dt> voisin d'un <dd>.
  function labelOf(node) {
    const el = node.parentElement;
    if (!el) return null;
    const dd = el.closest('dd');
    if (dd && dd.previousElementSibling && dd.previousElementSibling.localName === 'dt') {
      return clean(dd.previousElementSibling.textContent);
    }
    return null;
  }

  // Libellé d'un champ de formulaire (pour apprendre les valeurs saisies).
  function labelOfControl(input) {
    if (!input) return null;
    const d = doc();
    if (input.id) {
      const l = d.querySelector('label[for="' + input.id.replace(/"/g, '') + '"]');
      if (l) return clean(l.textContent);
    }
    let p = input.parentElement;
    for (let i = 0; p && i < 4; i++, p = p.parentElement) {
      const l = p.querySelector(':scope > label');
      if (l) return clean(l.textContent);
    }
    return null;
  }

  // Niveau d'alerte du bloc qui contient le texte (utile pour prioriser les
  // avertissements de sécurité côté traduction).
  function alertLevelOf(el) {
    for (let p = el, i = 0; p && p.nodeType === 1 && i < 5; p = p.parentElement, i++) {
      const role = p.getAttribute('role');
      if (role === 'alert' || role === 'alertdialog') return 'error';
      const cls = typeof p.className === 'string' ? p.className : '';
      if (/\b(?:border|bg)-(?:red|rose)-/.test(cls)) return 'error';
      if (/\b(?:border|bg)-(?:amber|yellow|orange)-/.test(cls)) return 'warning';
    }
    return null;
  }

  // Étape courante du parcours (adaptateur propre au site de test : lecture seule).
  function getStep() {
    const d = doc();
    if (!d) return null;
    const ol = [...d.querySelectorAll('ol')].find((o) => o.querySelectorAll(':scope > li').length >= 3);
    if (ol) {
      const items = [...ol.querySelectorAll(':scope > li')];
      const idx = items.findIndex((li) => {
        const first = li.firstElementChild;
        return first && typeof first.className === 'string' && first.className.includes('bg-[#00BFFF]');
      });
      if (idx >= 0) {
        const spans = items[idx].querySelectorAll('span');
        return { index: idx + 1, total: items.length, label: clean(spans[1] ? spans[1].textContent : '') };
      }
    }
    return null;
  }

  // ───────────────────────────── Parcours du DOM ────────────────────────────
  function gatherTextNodes(base) {
    const out = [];
    if (base.nodeType === 3) {
      if (base.parentElement && !isIgnored(base.parentElement)) out.push(base);
      return out;
    }
    if (base.nodeType !== 1 || isIgnored(base)) return out;
    const walker = doc().createTreeWalker(base, 5 /* ELEMENT | TEXT */, {
      acceptNode(n) {
        if (n.nodeType === 1) {
          // 2 = FILTER_REJECT (saute le sous-arbre), 3 = FILTER_SKIP
          return config.skipTags.includes(n.localName) || (n.matches && n.matches(config.ignoreSelector)) ? 2 : 3;
        }
        return n.nodeValue && n.nodeValue.trim() ? 1 : 3;
      },
    });
    let n;
    while ((n = walker.nextNode())) out.push(n);
    return out;
  }

  function gatherAttrTargets(base) {
    const out = [];
    const el = base.nodeType === 1 ? base : null;
    if (!el || isIgnored(el)) return out;
    const sel = config.attributes.map((a) => '[' + a + ']').join(',');
    const list = [el, ...el.querySelectorAll(sel)];
    for (const e of list) {
      if (isIgnored(e)) continue;
      for (const a of config.attributes) {
        if (e.hasAttribute(a)) out.push({ el: e, attr: a });
      }
    }
    return out;
  }

  // Le nœud est-il inchangé depuis son dernier traitement ?
  function unchanged(node, attr) {
    if (!known.has(node)) return false;
    if (attr) {
      const m = attrSignatures.get(node);
      return !!m && m.get(attr) === node.getAttribute(attr);
    }
    return signatures.get(node) === node.nodeValue;
  }

  function remember(node, attr, value) {
    known.add(node);
    if (attr) {
      let m = attrSignatures.get(node);
      if (!m) attrSignatures.set(node, (m = new Map()));
      m.set(attr, value);
    } else {
      signatures.set(node, value);
    }
  }

  // ───────────────────────────── Extraction ─────────────────────────────────
  /**
   * Extrait les segments d'un nœud (ou de tout le <body>).
   * @param {Node} [rootNode]
   * @param {{force?: boolean}} [opts] force : ignore la mémoire des textes déjà vus
   * @returns {Segment[]}
   *
   * Segment = {
   *   id, type: 'text'|'attr', node, attr?,
   *   original,   // contenu brut d'origine (avec espaces)
   *   core,       // texte nettoyé (sans espaces de bord) avant masquage
   *   lead, trail,// espaces de bord conservés pour la réécriture
   *   masked,     // texte à jetons : SEUL texte autorisé à sortir du navigateur
   *   vault,      // Map jeton → valeur d'origine (reste local)
   *   translatable, lang, hasTokens,
   *   ctx: { tag, attr?, label?, alert?, step? }
   * }
   */
  function collect(rootNode, opts) {
    opts = opts || {};
    const base = rootNode || (doc() && doc().body);
    if (!base) return [];
    const force = !!opts.force;

    // 1) Candidats
    const cands = [];
    for (const node of gatherTextNodes(base)) {
      stats.scanned++;
      if (!force && unchanged(node)) { stats.skippedSeen++; continue; }
      const raw = node.nodeValue;
      const core = clean(raw);
      if (!core || !hasLetters(core) || isAbbreviation(core)) {
        stats.skippedEmpty++;
        continue;
      }
      cands.push({ type: 'text', node, raw, core, label: labelOf(node) });
    }
    for (const t of gatherAttrTargets(base)) {
      stats.scanned++;
      if (!force && unchanged(t.el, t.attr)) { stats.skippedSeen++; continue; }
      const raw = t.el.getAttribute(t.attr);
      const core = clean(raw);
      if (!core || !hasLetters(core) || isAbbreviation(core)) { stats.skippedEmpty++; continue; }
      cands.push({ type: 'attr', node: t.el, attr: t.attr, raw, core, label: null });
    }
    if (!cands.length) return [];

    // 2) Passe 1 : apprendre les valeurs sensibles (noms, téléphones…) pour
    //    pouvoir les masquer même quand elles apparaissent AVANT leur libellé.
    for (const c of cands) {
      c.forced = c.type === 'text' ? kindFromLabel(c.label) : null;
      if (c.forced === 'name' || c.forced === 'phone' || c.forced === 'email') {
        privacy.registerSensitive(c.core, c.forced);
      } else if (c.type === 'text' && privacy.looksLikePersonName(c.core)) {
        if (privacy.registerSensitive(c.core, 'name')) stats.nameGuesses++;
      }
    }

    // 3) Passe 2 : masquage et construction des segments
    const step = getStep();
    const segments = [];
    for (const c of cands) {
      const lead = (c.raw.match(/^\s*/) || [''])[0];
      const trail = (c.raw.match(/\s*$/) || [''])[0];
      let m;
      if (c.forced) { m = privacy.mask(c.core, { forceKind: c.forced }); stats.forcedByLabel++; }
      else m = privacy.mask(c.core);

      const el = c.type === 'text' ? c.node.parentElement : c.node;
      const ctx = { tag: el ? el.localName : null };
      if (c.type === 'attr') ctx.attr = c.attr;
      if (c.label) ctx.label = privacy.mask(c.label).masked;
      const alert = el ? alertLevelOf(el) : null;
      if (alert) ctx.alert = alert;
      if (step) ctx.step = step.index;

      const seg = {
        id: 'sl' + (++seq).toString(36),
        type: c.type,
        node: c.node,
        attr: c.attr,
        original: c.raw,
        core: c.core,
        lead,
        trail,
        masked: m.masked,
        vault: m.vault,
        hasTokens: m.count > 0,
        translatable: privacy.hasTranslatableText(m.masked),
        lang: detectLang(m.masked),
        ctx,
      };
      if (seg.hasTokens) stats.withTokens++;
      stats.extracted++;
      remember(c.node, c.attr, c.raw);
      segments.push(seg);
    }
    return segments;
  }

  /**
   * Charge utile autorisée à quitter le navigateur. Retourne null si le segment
   * n'a rien à traduire, ou { blocked: true } si une donnée sensible a survécu
   * au masquage (l'envoi doit alors être annulé).
   */
  function toPayload(seg) {
    if (!seg.translatable) return null;
    const check = privacy.assertSafe(seg.masked);
    const ctxCheck = seg.ctx.label ? privacy.assertSafe(seg.ctx.label) : { safe: true };
    if (!check.safe || !ctxCheck.safe) {
      return { blocked: true, id: seg.id, leaks: check.leaks };
    }
    return { id: seg.id, text: seg.masked, lang: seg.lang, ctx: seg.ctx };
  }

  // ───────────────────────────── Réécriture ─────────────────────────────────
  /** Écrit la traduction (jetons déjà restaurés) dans le DOM. */
  function apply(seg, text) {
    const n = seg.node;
    if (!n || !n.isConnected) return false;
    if (seg.type === 'text') {
      if (n.nodeValue !== seg.original) return false; // contenu changé entre-temps
      originals.set(n, seg.original);
      const out = seg.lead + text + seg.trail;
      n.nodeValue = out;
      remember(n, null, out);
      return true;
    }
    if (n.getAttribute(seg.attr) !== seg.original) return false;
    let m = attrOriginals.get(n);
    if (!m) attrOriginals.set(n, (m = new Map()));
    m.set(seg.attr, seg.original);
    const out = seg.lead + text + seg.trail;
    n.setAttribute(seg.attr, out);
    remember(n, seg.attr, out);
    return true;
  }

  /** Remet le texte français d'origine sur tous les nœuds traduits sous `rootNode`. */
  function revertAll(rootNode) {
    const base = rootNode || doc().body;
    let n = 0;
    for (const node of gatherTextNodes(base)) {
      const o = originals.get(node);
      if (o != null) {
        node.nodeValue = o;
        remember(node, null, o);
        originals.delete(node);
        n++;
      }
    }
    if (base.nodeType === 1) {
      const sel = config.attributes.map((a) => '[' + a + ']').join(',');
      for (const el of [base, ...base.querySelectorAll(sel)]) {
        const m = attrOriginals.get(el);
        if (!m) continue;
        for (const [a, o] of m) {
          el.setAttribute(a, o);
          remember(el, a, o);
          n++;
        }
        attrOriginals.delete(el);
      }
    }
    return n;
  }

  const getStats = () => Object.assign({}, stats);
  const resetStats = () => { Object.keys(stats).forEach((k) => { stats[k] = 0; }); };
  const configure = (patch) => Object.assign(config, patch || {});

  NS.extractor = {
    config, configure,
    collect, toPayload, apply, revertAll,
    getStep, labelOfControl, kindFromLabel, detectLang,
    stats: getStats, resetStats, isIgnored,
  };
})(typeof globalThis !== 'undefined' ? globalThis : this);
