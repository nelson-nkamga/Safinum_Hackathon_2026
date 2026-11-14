/*!
 * SAFINUM Langues — Module 1 / Livrable 2 : privacy.js
 * ---------------------------------------------------------------------------
 * Rôle : masquer les données sensibles AVANT tout envoi au moteur de
 * traduction, puis les réinjecter APRÈS traduction.
 *
 *   texte du site  ──mask()──►  texte à jetons  ──(moteur)──►  traduction à jetons
 *   "Frais : 25 000 FCFA"        "Frais : ⟦M1⟧"                 "<ewondo> ⟦M1⟧"
 *                                                   ◄──restore()── "<ewondo> 25 000 FCFA"
 *
 * Garanties :
 *  - la table jeton → valeur d'origine (« vault ») reste dans la mémoire du
 *    navigateur : elle n'est ni envoyée, ni stockée, ni journalisée ;
 *  - assertSafe() re-scanne le texte masqué : s'il reste une donnée sensible,
 *    l'envoi doit être bloqué ;
 *  - validate() vérifie que la traduction a gardé tous les jetons (donc tous
 *    les montants, numéros, bénéficiaires) exactement une fois.
 *
 * Aucune dépendance. Fonctionne dans le navigateur (content script) et dans
 * Node (tests).
 */
(function (root, factory) {
  'use strict';
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  if (root) {
    root.SafinumLang = root.SafinumLang || {};
    root.SafinumLang.privacy = api;
  }
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';

  // ─────────────────────────── Configuration ────────────────────────────────
  const config = {
    // Format du jeton. À valider avec le moteur (Marian) : si les crochets
    // ⟦ ⟧ sont abîmés à la traduction, changer ici (ex. '[[' et ']]').
    open: '⟦',
    close: '⟧',
    // Termes à ne JAMAIS considérer comme des noms de personnes.
    keepTerms: [
      'Safinum Pay', 'Safinum', 'SAFINUM', 'Mobile Money', 'Orange Money',
      'MTN MoMo', 'MoMo', 'FCFA', 'CFA', 'XAF', 'XOF', 'CNEF', 'Wave',
      'Afriland First Bank', 'Huawei',
    ],
    // Mots capitalisés fréquents dans les interfaces (pas des noms propres).
    commonWords: [
      'Bonjour', 'Bonsoir', 'Salut', 'Bienvenue', 'Hello', 'Welcome', 'Merci',
      'Compte', 'Transfert', 'Solde', 'Frais', 'Montant', 'Total', 'Nouveau',
      'Nouvelle', 'Votre', 'Mon', 'Ma', 'Mes', 'Succès', 'Erreur', 'Confirmer',
      'Continuer', 'Retour', 'Modifier', 'Sécurité', 'Banque', 'Paiement',
      'Opération', 'Référence', 'Statut', 'Bénéficiaire', 'Téléphone',
    ],
    nameHeuristic: true, // détecte les textes isolés qui ressemblent à « Prénom Nom »
    maxEntities: 300,    // nombre max de valeurs sensibles mémorisées (noms saisis…)
  };

  // Codes de jetons par type de donnée.
  const KIND_CODE = {
    amount: 'M', percent: 'P', phone: 'T', account: 'A', reference: 'R',
    date: 'D', email: 'E', name: 'N', number: 'X',
  };
  const CODE_KIND = Object.fromEntries(Object.entries(KIND_CODE).map(([k, v]) => [v, k]));

  // ─────────────────────────── Motifs de détection ──────────────────────────
  // Espaces : normal, insécable, fine insécable (le site peut en utiliser).
  const S = String.raw`[ \u00A0\u202F\u2009]`;
  const NUM = String.raw`(?:\d{1,3}(?:[ \u00A0\u202F\u2009.,]\d{3})+|\d+)(?:[.,]\d{1,2})?`;
  const CUR = String.raw`(?:FCFA|F\s?CFA|XAF|XOF|CFA|EUR|USD|€|\$|francs?\s+CFA)`;
  const MONTH = String.raw`(?:janv(?:ier)?|f[ée]vr(?:ier)?|mars|avr(?:il)?|mai|juin|juil(?:let)?|ao[uû]t|sept(?:embre)?|oct(?:obre)?|nov(?:embre)?|d[ée]c(?:embre)?|jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)`;
  const GREET = String.raw`(?:[Bb]onjour|[Bb]onsoir|[Ss]alut|[Cc]her|[Cc]hère|[Bb]ienvenue|[Hh]ello|[Hh]i|[Dd]ear|[Ww]elcome)`;

  // pr = priorité en cas d'égalité (le plus grand gagne).
  const PATTERNS = [
    { kind: 'email', pr: 9, re: /[\p{L}\d._%+-]+@[\p{L}\d-]+(?:\.[\p{L}\d-]+)+/gu },
    // Référence de transaction : SAF-2026-0RGVFI (au moins un chiffre)
    { kind: 'reference', pr: 8, re: /(?<![\w-])(?=[A-Z0-9-]*\d)[A-Z]{2,6}(?:-[A-Z0-9]{2,12}){1,4}(?![\w-])/g },
    { kind: 'reference', pr: 8, re: /(?<!\w)(?:REF|TRX|TXN)[ .:#-]*[A-Z0-9]{5,}(?!\w)/g },
    // IBAN
    { kind: 'account', pr: 8, re: /(?<!\w)[A-Z]{2}\d{2}(?:[ \u00A0]?[A-Z0-9]{4}){3,7}(?:[ \u00A0]?[A-Z0-9]{1,4})?(?!\w)/g },
    // Numéro de compte : CM 001 2345 6789 01
    { kind: 'account', pr: 8, re: /(?<!\w)[A-Z]{2}(?:[ \u00A0\u202F]?\d{2,6}){3,}(?!\w)/g },
    // Téléphone international : +237 6 99 12 34 56
    { kind: 'phone', pr: 7, re: /(?<!\w)\+\d{1,3}(?:[ \u00A0\u202F.\-]?\d){6,12}(?!\d)/g },
    // Mobile camerounais local : 6 99 12 34 56 / 699123456
    { kind: 'phone', pr: 7, re: /(?<![\w+])6(?=[ \u00A0\u202F.\-]?[2-9])(?:[ \u00A0\u202F.\-]?\d){8}(?!\d)/g },
    // Dates : 05 nov. 2026 / 5 novembre 2026 / Nov 5, 2026 / 05/11/2026 / 2026-11-05 / 14h30
    { kind: 'date', pr: 6, re: new RegExp(String.raw`(?<!\d)\d{1,2}${S}+${MONTH}\.?${S}+\d{4}(?!\d)`, 'giu') },
    { kind: 'date', pr: 6, re: new RegExp(String.raw`\b${MONTH}\.?${S}+\d{1,2}(?:st|nd|rd|th)?,?${S}+\d{4}(?!\d)`, 'giu') },
    { kind: 'date', pr: 6, re: /(?<!\d)\d{1,2}[\/.\-]\d{1,2}[\/.\-]\d{2,4}(?!\d)/g },
    { kind: 'date', pr: 6, re: /(?<!\d)\d{4}-\d{2}-\d{2}(?:T\d{2}:\d{2}(?::\d{2})?Z?)?(?!\d)/g },
    { kind: 'date', pr: 6, re: /(?<!\d)(?:[01]?\d|2[0-3])(?:h|:)[0-5]\d(?!\d)/g },
    // Montants avec devise : 25 000 FCFA, -12 500 FCFA, +180 000 FCFA, 0 FCFA
    { kind: 'amount', pr: 6, re: new RegExp(String.raw`(?<!\w)[+\-−–]?${NUM}${S}*${CUR}(?![\p{L}\d])`, 'gu') },
    // Montants sans devise (milliers groupés) : 225 000
    { kind: 'amount', pr: 5, re: /(?<![\w.,])\d{1,3}(?:[ \u00A0\u202F\u2009.,]\d{3})+(?:[.,]\d{1,2})?(?!\w)/g },
    // Taux / pourcentages (frais en %) : 1,5 %
    { kind: 'percent', pr: 5, re: new RegExp(String.raw`(?<!\w)\d+(?:[.,]\d+)?${S}?%`, 'g') },
    // Code OTP / PIN : « code 123456 »
    { kind: 'number', pr: 4, re: /(?<=\b(?:code|otp|pin|mot de passe)[ :]+)\d{4,8}(?!\d)/giu },
    // Longue suite de chiffres (≥ 8) : numéro de carte, de compte, de téléphone inconnu
    { kind: 'number', pr: 3, re: /(?<!\w)\d(?:[ \u00A0\u202F.\-]?\d){7,}(?!\w)/g },
    // Nom après une formule de salutation : « Bonjour, Amina »
    { kind: 'name', pr: 5, re: new RegExp(String.raw`(?<=\b${GREET}[,!]?[ \u00A0]+)\p{Lu}[\p{L}'’\-]*(?:[ \u00A0]+\p{Lu}[\p{L}'’\-]*){0,3}`, 'gu') },
  ];

  // ─────────────────────── Valeurs sensibles mémorisées ─────────────────────
  // Noms / téléphones appris pendant la navigation (valeurs saisies, noms vus
  // à l'écran). Mémoire locale uniquement.
  const entities = new Map(); // clé normalisée → { value, kind }
  let entityRe = null;

  const norm = (s) => String(s).replace(/[\u00A0\u202F\u2009]/g, ' ').replace(/\s+/g, ' ').trim().toLowerCase();
  const escapeRe = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');

  function isKept(text) {
    const t = norm(text);
    return config.keepTerms.some((k) => t === norm(k) || t.includes(norm(k)));
  }

  function registerSensitive(value, kind) {
    kind = kind || 'name';
    if (typeof value !== 'string') return false;
    const v = value.replace(/\s+/g, ' ').trim();
    if (v.length < 3 || isKept(v)) return false;
    if (entities.size >= config.maxEntities && !entities.has(norm(v))) return false;
    entities.set(norm(v), { value: v, kind });
    if (kind === 'name') {
      // chaque élément du nom (« Amina », « Ngo », « Bell ») est aussi sensible
      v.split(' ').forEach((part) => {
        if (part.length >= 3 && !isKept(part) && !config.commonWords.includes(part)) {
          entities.set(norm(part), { value: part, kind: 'name' });
        }
      });
    }
    entityRe = null;
    return true;
  }

  function clearSensitive() { entities.clear(); entityRe = null; }

  function getEntityRe() {
    if (entityRe !== null) return entityRe || null;
    if (!entities.size) { entityRe = false; return null; }
    const parts = [...entities.values()]
      .map((e) => e.value)
      .sort((a, b) => b.length - a.length)
      .map((v) => escapeRe(v).replace(/ +/g, '[ \\u00A0\\u202F]+'));
    entityRe = new RegExp(String.raw`(?<![\p{L}\p{N}])(?:${parts.join('|')})(?![\p{L}\p{N}])`, 'giu');
    return entityRe;
  }

  // Un texte isolé ressemble-t-il à « Prénom Nom » ? (2 à 4 mots capitalisés)
  const WORD_RE = /^\p{Lu}\p{Ll}+(?:['’-]\p{Lu}?\p{Ll}+)*$/u;
  function looksLikePersonName(text) {
    if (!config.nameHeuristic || typeof text !== 'string') return false;
    const t = text.replace(/[\u00A0\u202F\u2009]/g, ' ').replace(/\s+/g, ' ').trim();
    if (t.length < 5 || t.length > 60 || /[\d@:,;!?()]/.test(t)) return false;
    const words = t.split(' ');
    if (words.length < 2 || words.length > 4) return false;
    if (isKept(t)) return false;
    return words.every((w) => WORD_RE.test(w) && !config.commonWords.includes(w) && !isKept(w));
  }

  // ───────────────────────────── Détection ──────────────────────────────────
  function findSpans(text) {
    const spans = [];
    for (const p of PATTERNS) {
      p.re.lastIndex = 0;
      let m;
      while ((m = p.re.exec(text)) !== null) {
        if (m[0].length === 0) { p.re.lastIndex++; continue; }
        if (p.kind === 'name' && isKept(m[0])) continue;
        spans.push({ start: m.index, end: m.index + m[0].length, kind: p.kind, pr: p.pr, text: m[0] });
      }
    }
    const er = getEntityRe();
    if (er) {
      er.lastIndex = 0;
      let m;
      while ((m = er.exec(text)) !== null) {
        const e = entities.get(norm(m[0]));
        spans.push({ start: m.index, end: m.index + m[0].length, kind: e ? e.kind : 'name', pr: 6, text: m[0] });
      }
    }
    // Résolution des chevauchements : début le plus tôt, puis le plus long, puis priorité.
    spans.sort((a, b) => a.start - b.start || (b.end - b.start) - (a.end - a.start) || b.pr - a.pr);
    const out = [];
    let cursor = 0;
    for (const s of spans) {
      if (s.start >= cursor) { out.push(s); cursor = s.end; }
    }
    return out;
  }

  // ───────────────────────────── Jetons ─────────────────────────────────────
  const makeToken = (kind, n) => config.open + (KIND_CODE[kind] || 'X') + n + config.close;

  function strictRe() {
    return new RegExp(escapeRe(config.open) + String.raw`([A-Z])(\d{1,3})` + escapeRe(config.close), 'g');
  }
  // Tolère ⟦ M1 ⟧, [M1], [[M1]], (M1) : le moteur peut abîmer légèrement les délimiteurs.
  function tolerantRe() {
    const o = `(?:${escapeRe(config.open)}|⟦|\\[\\[|\\[|\\()`;
    const c = `(?:${escapeRe(config.close)}|⟧|\\]\\]|\\]|\\))`;
    return new RegExp(o + String.raw`\s*([A-Z])\s*(\d{1,3})\s*` + c, 'g');
  }

  /**
   * Masque les données sensibles.
   * @param {string} text
   * @param {{forceKind?: string}} [opts] forceKind : masque TOUT le texte (ex. valeur d'un champ « Bénéficiaire »)
   * @returns {{masked: string, vault: Map<string,{kind:string, original:string}>, count: number}}
   */
  function mask(text, opts) {
    opts = opts || {};
    const vault = new Map();
    const byValue = new Map();
    const counters = {};
    const tokenFor = (kind, original) => {
      const key = kind + '|' + norm(original);
      if (byValue.has(key)) return byValue.get(key);
      counters[kind] = (counters[kind] || 0) + 1;
      const token = makeToken(kind, counters[kind]);
      vault.set(token, { kind, original });
      byValue.set(key, token);
      return token;
    };
    if (opts.forceKind) {
      return { masked: tokenFor(opts.forceKind, text), vault, count: 1 };
    }
    const spans = findSpans(text);
    let out = '';
    let last = 0;
    for (const s of spans) {
      out += text.slice(last, s.start) + tokenFor(s.kind, s.text);
      last = s.end;
    }
    out += text.slice(last);
    return { masked: out, vault, count: spans.length };
  }

  /** Réinjecte les valeurs d'origine à la place des jetons. */
  function restore(text, vault) {
    return String(text).replace(tolerantRe(), (m, code, num) => {
      const entry = vault.get(config.open + code + num + config.close);
      return entry ? entry.original : m;
    });
  }

  function countTokens(text, re) {
    const counts = new Map();
    let m;
    while ((m = re.exec(text)) !== null) {
      const key = config.open + m[1] + m[2] + config.close;
      counts.set(key, (counts.get(key) || 0) + 1);
    }
    return counts;
  }

  /**
   * Contrôle d'intégrité d'une traduction : tous les jetons du texte source
   * doivent être présents, une seule fois chacun, sans jeton inconnu.
   */
  function validate(maskedSource, translated, vault) {
    const expected = countTokens(maskedSource, strictRe());
    const found = countTokens(translated, tolerantRe());
    const strictFound = countTokens(translated, strictRe());
    const missing = [];
    const duplicated = [];
    const extra = [];
    for (const [k, n] of expected) {
      const f = found.get(k) || 0;
      if (f < n) missing.push(k);
      if (f > n) duplicated.push(k);
    }
    for (const k of strictFound.keys()) {
      if (!expected.has(k) && !(vault && vault.has(k))) extra.push(k);
    }
    return { ok: !missing.length && !duplicated.length && !extra.length, missing, duplicated, extra };
  }

  /**
   * Dernier garde-fou avant envoi : aucune donnée sensible ne doit rester
   * dans le texte masqué. Les « leaks » ne contiennent qu'un extrait tronqué.
   */
  function assertSafe(maskedText) {
    const leaks = findSpans(String(maskedText)).map((s) => ({
      kind: s.kind,
      sample: s.text.slice(0, 2) + '…',
    }));
    return { safe: leaks.length === 0, leaks };
  }

  /** Reste-t-il du texte à traduire une fois les jetons retirés ? */
  function hasTranslatableText(masked) {
    return /\p{L}{2,}/u.test(String(masked).replace(tolerantRe(), ' '));
  }

  function configure(patch) { Object.assign(config, patch || {}); return config; }

  return {
    config, configure, KIND_CODE, CODE_KIND,
    mask, restore, validate, assertSafe, hasTranslatableText,
    registerSensitive, clearSensitive, looksLikePersonName,
    findSpans,
  };
});
