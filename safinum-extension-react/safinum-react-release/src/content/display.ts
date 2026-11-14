// Module d'affichage (TypeScript natif) : extrait les textes d'interface, demande la traduction,
// les affiche avec leur statut, et permet de restaurer l'original.
// NOTE : extraction/protection minimales en attendant extractor/privacy/observer du membre 1.
import { requestTranslation } from "../services/translation-api";
import type { Stats, TabState, TranslationResult, TranslationStatus } from "../types/translation";

interface Entry {
  node: Text;
  original: string;
  translated: string | null;
  status: TranslationStatus;
  warning: string | null;
}

const SKIP_TAGS = new Set(["SCRIPT", "STYLE", "NOSCRIPT", "TEXTAREA", "INPUT", "SELECT", "OPTION", "CODE", "PRE", "IFRAME"]);
const IGNORE_SELECTOR = "[contenteditable],[data-safinum-ignore]";
const SOURCE_LANG = "fr";

const clean = (s: string | null | undefined) => (s ?? "").replace(/\s+/g, " ").trim();

// Protection : en cas de doute, on exclut (rien n'est envoyé, rien n'est modifié).
function isProtectedText(text: string): boolean {
  const t = clean(text);
  if (t.length < 2 || t.length > 500) return true;
  if (!/\p{L}/u.test(t)) return true;
  if (/\d/.test(t)) return true; // montants, frais, dates, téléphones, identifiants
  if (/@|https?:\/\//i.test(t)) return true; // e-mails, liens
  if (/^[^:：]{2,40}[:：]\s*\S+(\s+\S+){0,2}$/.test(t)) return true; // « Libellé : Valeur » dans un même nœud
  return false;
}

// Valeur placée après un libellé (« Bénéficiaire : » puis le nom, ou cellule td après th).
function isValueNode(node: Text): boolean {
  let prev = node.previousSibling;
  if (prev && prev.nodeType === Node.TEXT_NODE && !(prev.nodeValue ?? "").trim()) prev = prev.previousSibling;
  if (prev && clean(prev.textContent).endsWith(":")) return true;
  const p = node.parentElement;
  const ps = p?.previousElementSibling;
  return !!(p && ps && /^(DD|TD)$/.test(p.tagName) && /^(DT|TH)$/.test(ps.tagName));
}

// Intégration du module 1 (SafinumLang : privacy/extractor/observer) : c'est lui
// qui extrait, masque, et réinjecte. Ce module ne fournit que le « transport » :
// les payloads masqués → API (module 2) → textes traduits (jetons intacts).
// La langue source (`fr`/`en`) et le contexte (alerte sécurité) viennent du
// module 1 et sont transmis au backend par item.
function integrateModule1(enabledState: boolean, targetLang: string | null) {
  const core = (window as any).SafinumLang;
  if (!core || !core.observer) return false;

  const target = targetLang || "ewondo";
  const transport = async (payloads: Array<{ id: string; text: string; lang?: string | null; ctx?: Record<string, unknown> }>) => {
    if (!payloads.length) return [];
    const res = await chrome.runtime.sendMessage({
      type: "TRANSLATE",
      texts: payloads.map((p) => ({ id: p.id, text: p.text, lang: p.lang ?? null, ctx: p.ctx ?? {} })),
      target
    });
    if (!res || !res.ok) return [];
    return (res.translations ?? []).map((t: { id: string; translated: string }) => ({ id: t.id, text: t.translated }));
  };

  // L'observer complet (module 1) reçoit le transport à la création : start({transport}).
  core.observer.start({ transport });
  core.observer.setEnabled(Boolean(enabledState && targetLang));
  if (!enabledState || !targetLang) core.observer.stop();
  return true;
}

export function createDisplay() {
  const registry = new Map<string, Entry>();
  let nodeIds = new WeakMap<Text, string>();
  let seq = 0;
  let gen = 0;
  let enabled = false;
  let lang: string | null = null;
  let observer: MutationObserver | null = null;
  let timer: number | undefined;

  function isAlreadyHandled(node: Text): boolean {
    const value = node.nodeValue ?? "";
    if (value.includes("[SIM]") || value.includes("⟦") || value.includes("⟧")) return true;
    const parent = node.parentElement;
    if (!parent) return false;
    return !!(parent.dataset.safinumStatus || parent.dataset.safinumTitle);
  }

  function collect(root: Node): Text[] {
    const nodes: Text[] = [];
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    for (let n = walker.nextNode() as Text | null; n; n = walker.nextNode() as Text | null) {
      const el = n.parentElement;
      if (!el || nodeIds.has(n) || SKIP_TAGS.has(el.tagName)) continue;
      if (el.closest(IGNORE_SELECTOR)) continue;
      if (el.checkVisibility && !el.checkVisibility()) continue;
      if (isAlreadyHandled(n) || isProtectedText(n.nodeValue ?? "") || isValueNode(n)) continue;
      nodes.push(n);
    }
    return nodes;
  }

  function apply(id: string, t: Partial<TranslationResult>) {
    const e = registry.get(id);
    if (!e || !e.node.isConnected) return;
    const tr = typeof t.translated === "string" ? t.translated.trim() : "";
    // Contrôle déterministe : sortie vide, statut indisponible, ou chiffres apparus de nulle part.
    // En cas d'échec : AUCUN marquage à l'écran — le texte reste français, visiblement non traduit.
    const bad = !tr || t.status === "unavailable" || t.status === "error" || (/\d/.test(tr) && !/\d/.test(e.original));
    e.warning = t.warning ?? null;
    if (bad) {
      e.status = t.status === "error" ? "error" : "unavailable";
      return;
    }
    e.status = t.status ?? "model_generated";
    const lead = /^\s*/.exec(e.original)![0];
    const trail = /\s*$/.exec(e.original)![0];
    e.translated = lead + tr + trail;
    e.node.nodeValue = e.translated;
    const parent = e.node.parentElement;
    if (!parent) return;
    parent.dataset.safinumStatus = e.status;
    if (!parent.title) {
      parent.title = "Original : " + e.original.trim();
      parent.dataset.safinumTitle = "1";
    }
  }

  async function run() {
    if (!enabled || !lang) return;
    const fresh = collect(document.body).filter((node) => {
      const current = node.nodeValue ?? "";
      if (current.includes("[SIM]")) return false;
      return true;
    });
    if (!fresh.length) return;
    const myGen = gen;
    const batch = fresh.map((node) => {
      const id = "t" + ++seq;
      nodeIds.set(node, id);
      registry.set(id, { node, original: node.nodeValue ?? "", translated: null, status: "pending", warning: null });
      return { id, text: clean(node.nodeValue) };
    });
    let res;
    try {
      res = await requestTranslation(batch, SOURCE_LANG, lang);
    } catch {
      res = { ok: false as const, error: "messagerie" };
    }
    if (myGen !== gen) return; // langue changée ou traduction désactivée entre-temps
    if (!res || !res.ok) {
      batch.forEach((b) => apply(b.id, { status: "error" }));
      return;
    }
    const byId = new Map(res.translations.map((t) => [t.id, t]));
    batch.forEach((b) => apply(b.id, byId.get(b.id) ?? { status: "unavailable" }));
  }

  function restoreAll() {
    gen++;
    for (const e of registry.values()) {
      if (!e.node.isConnected) continue;
      if (e.translated !== null && e.node.nodeValue === e.translated) e.node.nodeValue = e.original;
      const p = e.node.parentElement;
      if (p) {
        delete p.dataset.safinumStatus;
        if (p.dataset.safinumTitle) {
          p.removeAttribute("title");
          delete p.dataset.safinumTitle;
        }
      }
    }
    document.querySelectorAll("[data-safinum-status]").forEach((el) => el.removeAttribute("data-safinum-status"));
    document.querySelectorAll("[data-safinum-title]").forEach((el) => el.removeAttribute("title"));
    registry.clear();
    nodeIds = new WeakMap();
  }

  // Contenus dynamiques
  function onMutations(mutations: MutationRecord[]) {
    for (const m of mutations) {
      if (m.type !== "characterData") continue;
      const target = m.target as Text;
      const id = nodeIds.get(target);
      const e = id ? registry.get(id) : undefined;
      // le site a réécrit un texte déjà traité : on le retraite
      if (id && e && target.nodeValue !== e.translated && target.nodeValue !== e.original) {
        registry.delete(id);
        nodeIds.delete(target);
      }
    }
    clearTimeout(timer);
    timer = window.setTimeout(run, 300);
  }

  function startObserver() {
    if (observer) return;
    observer = new MutationObserver(onMutations);
    observer.observe(document.body, { childList: true, subtree: true, characterData: true });
  }

  function stopObserver() {
    observer?.disconnect();
    observer = null;
    clearTimeout(timer);
  }

  async function setState(next: { enabled: boolean; lang: string | null; force?: boolean }) {
    restoreAll();

    if (integrateModule1(next.enabled, next.lang)) {
      if (!next.enabled) {
        enabled = false;
        lang = null;
        return;
      }
      if (!next.lang) return;
      enabled = true;
      lang = next.lang;
      return;
    }

    if (!next.enabled) {
      enabled = false;
      stopObserver();
      restoreAll();
      return;
    }
    if (!next.lang) return;
    if (enabled && lang === next.lang && !next.force) return;
    restoreAll();
    lang = next.lang;
    enabled = true;
    startObserver();
    await run();
  }

  function stats(): Stats {
    const s: Stats = { human_validated: 0, model_generated: 0, mock: 0, pending: 0, unavailable: 0, error: 0 };
    for (const e of registry.values()) s[e.status]++;
    return s;
  }

  // Exécute fn avec les textes d'origine (et sans badges) : le panneau « Comprendre cette étape »
  // doit lire les libellés français, pas leur traduction. Synchrone : aucun rendu intermédiaire.
  function withOriginals<T>(fn: () => T): T {
    const swapped: Array<[Text, string]> = [];
    for (const e of registry.values()) {
      if (e.translated !== null && e.node.isConnected && e.node.nodeValue === e.translated) {
        e.node.nodeValue = e.original;
        swapped.push([e.node, e.translated]);
      }
    }
    try {
      return fn();
    } finally {
      for (const [n, t] of swapped) n.nodeValue = t;
    }
  }

  const getState = (): TabState => {
    const s = stats();
    // Chemin intégré (module 1) : les textes sont traduits par l'observer du
    // module 1, pas par le registre local → on remonte ses compteurs au popup.
    const m1 = (window as any).SafinumLang?.observer?.stats?.();
    if (m1 && enabled) {
      s.model_generated = Math.max(s.model_generated, m1.translated ?? 0);
      s.unavailable = Math.max(s.unavailable, (m1.fallback ?? 0) + (m1.stale ?? 0));
      s.error = Math.max(s.error, m1.errors ?? 0);
    }
    return { enabled, lang, stats: s };
  };

  return { setState, getState, withOriginals };
}
