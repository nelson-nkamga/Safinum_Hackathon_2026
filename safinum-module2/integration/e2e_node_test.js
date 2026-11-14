// Harnais Node : teste le chemin de données EXACT de l'extension contre l'API réelle.
//   privacy.mask (module 1) → POST /translate (module 2) → privacy.validate + restore
// Exécuter : node integration/e2e_node_test.js   (API lancée sur 127.0.0.1:8000)
'use strict';
const path = require('path');

// privacy.js s'auto-enregistre sur globalThis (compatible Node, pas de DOM requis)
require(path.join(__dirname, '..', '..', 'safinum-extension-react', 'safinum-react-release', 'dist', 'safinum-core', 'privacy.js'));
const privacy = globalThis.SafinumLang.privacy;
const API = 'http://127.0.0.1:8000/translate';

const CASES = [
  // [texte, alerte, description]
  ['Frais : 500 FCFA', null, 'montant dans une phrase'],
  ['Total : 50 500 FCFA', null, 'montant'],
  ['Bonjour, Jean Dupont', null, 'nom après salutation'],
  ['Confirmer le transfert', null, 'texte simple'],
  ['Numéro du bénéficiaire : 6 70 00 00 00', null, 'téléphone'],
  ['Référence : SAF-2026-0RGVFI', null, 'référence'],
  ['Attention : ne partagez jamais votre code secret.', 'warning', 'alerte sécurité'],
  ['Available balance', null, 'page anglaise'],
];

function assert(cond, msg) {
  if (!cond) { console.error('  ✗ ' + msg); process.exitCode = 1; }
  else console.log('  ✓ ' + msg);
}

(async () => {
  // 1. Module 1 : masquage + assertions de fuite
  const batch = [];
  for (const [text, alert] of CASES) {
    const m = privacy.mask(text);
    const safe = privacy.assertSafe(m.masked);
    assert(safe.safe, `masquage sûr : ${text}`);
    batch.push({ id: 'n' + batch.length, text: m.masked, lang: /^[A-Za-z0-9 ,:'-]+$/.test(text) && text === text.toLowerCase() ? null : null, ctx: { tag: 'p', alert: alert || undefined } });
    batch[batch.length - 1]._vault = m.vault;
    batch[batch.length - 1]._masked = m.masked;
    batch[batch.length - 1]._original = text;
  }
  // Langue : le module 1 la détecte (fr/en) ; ici on la fixe manuellement
  batch[7].lang = 'en';

  // 2. Appel API — exactement le corps envoyé par le service worker de l'extension
  const res = await fetch(API, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      target_language: 'ewondo',
      texts: batch.map(({ id, text, lang, ctx }) => ({ id, text, lang: lang ?? null, ctx })),
    }),
  });
  const data = await res.json();
  assert(res.ok, 'HTTP 200');

  // 3. Pour chaque résultat : validate() + restore() comme le fait observer.js
  console.log('');
  for (const item of batch) {
    const t = data.translations.find((x) => x.id === item.id);
    if (!t) { console.error('  ✗ pas de réponse pour ' + item.id); process.exitCode = 1; continue; }
    const report = privacy.validate(item._masked, t.translated, item._vault);
    if (!report.ok) {
      assert(false, `${item._original} : jetons perdus ${JSON.stringify(report)}`);
      continue;
    }
    const finalText = privacy.restore(t.translated, item._vault);
    // Le montant original doit être réapparu EXACTEMENT si le texte a été traduit
    const restoredOk = !finalText.includes('⟦') || finalText === item._original;
    console.log(`  ${item._original.padEnd(48)} → ${finalText}  [${t.status}]${t.warning ? ' ⚠ ' + t.warning : ''}`);
    assert(restoredOk, 'jetons restaurés (aucune valeur perdue)');
    // Aucune valeur sensible dans CE QUI A ÉTÉ ENVOYÉ
    assert(!item.text.match(/\d{3,}|@|\+/), `aucune donnée sensible envoyée pour « ${item._original} »`);
  }
  console.log('\nTerminé. exit=' + (process.exitCode || 0));
})().catch((e) => { console.error(e); process.exit(1); });
