# Module 1 — Extraction HTML, protection des données, surveillance du site

Responsable : NKAMGA Nelson (« le TGV »)

## Contenu

| Fichier | Livrable | Rôle |
|---|---|---|
| `extractor.js` | 1 — Extracteur de textes | Parcourt le DOM, récupère textes + `placeholder` / `aria-label` / `title` / `alt`, produit des *segments* masqués |
| `privacy.js` | 2 — Module de protection | Masque montants, téléphones, comptes, références, dates, noms, e-mails ; restaure ; valide ; bloque les fuites |
| `observer.js` | 3 — Observateur dynamique | `MutationObserver` : détecte les nouveaux écrans sans rechargement, évite les retraitements, orchestre le pipeline |
| `demo.js` | banc d'essai | Faux moteur (préfixe `[ew]`) pour tester sans le vrai moteur |
| `manifest.json` | banc d'essai | Charge les 4 fichiers sur `https://safinum.cm/hackathon-test*` |
| `tests/` | tests | 29 tests automatiques (`npm install && npm test`) |

Ordre de chargement obligatoire : `privacy.js` → `extractor.js` → `observer.js`.

## Charger l'extension dans Chrome

1. `chrome://extensions` → activer « Mode développeur ».
2. « Charger l'extension non empaquetée » → choisir ce dossier.
3. Ouvrir `https://safinum.cm/hackathon-test` : les textes passent en `[ew] …`.
4. DevTools → Console → menu déroulant « top » → choisir l'extension, puis :
   `SafinumLang.debug.report()`, `SafinumLang.debug.stats()`,
   `SafinumLang.debug.leakScan(['25 000','Mbarga','699123456'])` (doit renvoyer `[]`).

## Interface pour les modules 2 et 3

```js
// Module 2 / 3 : brancher le vrai moteur (remplace le faux moteur de demo.js)
SafinumLang.observer.setTransport(async (payloads) => {
  // payloads = [{ id, text, lang, ctx }]  — text est DÉJÀ MASQUÉ, ex. "Frais : ⟦M1⟧"
  //   lang : 'fr' | 'en' | null     ctx : { tag, attr?, label?, alert?: 'warning'|'error', step?: 1..5 }
  // → renvoyer [{ id, text }] : traduction qui CONSERVE les jetons ⟦M1⟧ ⟦T1⟧ …
});
```

* Les jetons ⟦X1⟧ doivent revenir **tels quels, une seule fois chacun** dans la traduction.
  Sinon le texte reste en français (repli automatique) : jamais de montant faux à l'écran.
* Codes : `M` montant · `P` pourcentage · `T` téléphone · `A` compte · `R` référence · `D` date/heure · `E` e-mail · `N` nom · `X` autre numéro.
* Le format des jetons se change dans `privacy.js` (`config.open` / `config.close`) si le moteur les abîme.
* `ctx.alert === 'warning'` marque l'avertissement de sécurité du bénéficiaire : à prioriser dans la mémoire de traduction.
* `SafinumLang.extractor.getStep()` donne l'étape courante (1 à 5) sans dépendre de l'URL.
* Réécriture dans le DOM : `extractor.apply(segment, texte)` ; retour au français : `observer.setEnabled(false)`.

## Correspondance avec le cahier des tâches

| N° | Tâche | Où |
|---|---|---|
| 1 | Analyser la structure HTML | `README` + fixtures de `tests/dom.test.js` (copie fidèle des 5 écrans) |
| 2 | Extraire titres, paragraphes, boutons, textes | `extractor.collect()` |
| 3 | placeholders, aria-label, title, options | `extractor.collect()` (`config.attributes`), `<option>` = nœuds texte |
| 4 | Ne pas modifier valeurs saisies / logique | on n'écrit que dans des nœuds texte et 4 attributs ; `.value` jamais lu ni écrit pour l'extraction |
| 5 | Détecter montants, téléphones, dates… | `PATTERNS` dans `privacy.js` |
| 6 | Remplacer par des jetons | `privacy.mask()` |
| 7 | Conserver la correspondance localement | `vault` (`Map`) dans chaque segment, jamais envoyé |
| 8 | Réinjecter après traduction | `privacy.restore()` après `privacy.validate()` |
| 9 | Détecter les nouveaux contenus | `MutationObserver` + événements Inertia/historique/clic |
| 10 | Ne pas retraiter | `WeakSet` + signature de contenu (`unchanged()`), voir ci-dessous |

## Choix techniques à connaître

* **WeakSet + signature.** Un `WeakSet` seul ne suffit pas : Vue modifie parfois un nœud *en place*
  (ex. « Transfert instantané et gratuit » → « Frais de 1,5 % … » quand on change le type d'opération).
  On mémorise donc aussi le dernier contenu traité du nœud : il est ré-extrait seulement si son contenu a changé.
* **Anti-boucle.** L'observateur est déconnecté pendant nos écritures, et le texte écrit devient la signature du nœud.
* **Nœuds sans lettres jamais envoyés** (`250 000 FCFA`, `05 nov. 2026`, `+237 6 99 12 34 56`, références) :
  rien à traduire, rien à faire sortir. Les montants dans une phrase (`Frais : 375 FCFA`) sont masqués.
* **Libellé → valeur.** Dans le récapitulatif, la valeur d'un `<dd>` est entièrement masquée selon son `<dt>`
  (Bénéficiaire, Téléphone, Référence, Compte, E-mail), même si son format est inattendu.
* **Noms propres.** Détectés par : libellé du `<dt>`, formule « Bonjour, X », texte isolé « Prénom Nom »
  (heuristique), valeurs saisies dans les champs « Nom » / téléphone (lecture seule, mémoire locale uniquement).
  Un nom inconnu, écrit en pleine phrase et sans l'un de ces indices, ne peut pas être deviné.

## Limites connues

* Le texte est traité nœud par nœud : une phrase coupée par une balise interne
  (`Frais <span>Gratuit</span>`) est envoyée en deux morceaux. Aucun cas gênant sur les 5 écrans connus.
* Les messages d'erreur de validation (montant invalide, solde insuffisant…) ne figurent pas dans les pages reçues.
  Ils seront capturés automatiquement par l'observateur ; à vérifier en les provoquant sur le site.
* Les textes dans des images ou un `<canvas>` ne sont pas lus.
* Le `<title>` de l'onglet n'est pas traité (hors `<body>`).
* Si le jury passe le site en anglais (bouton EN), `lang` vaut `'en'` : le module 2 doit prévoir ce cas.
