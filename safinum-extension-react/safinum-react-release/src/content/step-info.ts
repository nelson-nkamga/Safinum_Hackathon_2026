// Lecture seule des informations réellement présentes dans la page, pour le panneau « Comprendre cette étape ».
// Rien n'est envoyé à l'API ; aucun mot de passe n'est lu ; aucune opération n'est exécutée.
import { templates } from "../data/templates";
import type { StepInfo, TemplateStep } from "../types/translation";

const clean = (s: string | null | undefined) => (s ?? "").replace(/\s+/g, " ").trim();
const norm = (s: string | null | undefined) =>
  clean(s).toLowerCase().normalize("NFD").replace(/[\u0300-\u036f]/g, "");

function detectStep(): TemplateStep {
  const text = norm(document.body.innerText);
  let best: TemplateStep | null = null;
  let bestScore = 0;
  for (const step of templates.steps) {
    const score = step.keywords.filter((k) => text.includes(norm(k))).length;
    if (score > bestScore) {
      best = step;
      bestScore = score;
    }
  }
  return best ?? templates.steps.find((s) => s.id === "generic")!;
}

interface Pair { label: string; value: string }

// Champs de formulaire, « Libellé : valeur », tableaux et listes de définitions.
function collectPairs(): Pair[] {
  const pairs: Pair[] = [];
  const push = (label: string | null | undefined, value: string | null | undefined) => {
    const l = norm(label).replace(/[:：]$/, "").trim();
    const v = clean(value);
    if (l && v && v.length < 120) pairs.push({ label: l, value: v });
  };

  document
    .querySelectorAll<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>(
      "input:not([type=password]):not([type=hidden]):not([type=checkbox]):not([type=radio]), select, textarea"
    )
    .forEach((f) => {
      const lab = (f.id && document.querySelector(`label[for="${CSS.escape(f.id)}"]`)) || f.closest("label");
      const placeholder = "placeholder" in f ? f.placeholder : "";
      const label = lab?.textContent || f.getAttribute("aria-label") || placeholder || f.getAttribute("name") || f.id;
      const value = f instanceof HTMLSelectElement ? f.selectedOptions[0]?.textContent : f.value;
      push(label, value);
    });

  document.body.innerText.split("\n").forEach((line) => {
    const m = /^([^:：]{2,40})\s*[:：]\s*(.+)$/.exec(line);
    if (m) push(m[1], m[2]);
  });

  document.querySelectorAll("tr").forEach((tr) => {
    const cells = tr.querySelectorAll("th,td");
    if (cells.length === 2) push(cells[0].textContent, cells[1].textContent);
  });
  document.querySelectorAll("dt").forEach((dt) => {
    const dd = dt.nextElementSibling;
    if (dd?.tagName === "DD") push(dt.textContent, dd.textContent);
  });
  return pairs;
}

export function readStepInfo(): StepInfo {
  const step = detectStep();
  const pairs = collectPairs();
  const values: Record<string, string | null> = {};
  for (const f of step.fields) {
    if (f.key === "titre") {
      values.titre = clean(document.querySelector("h1,h2")?.textContent) || clean(document.title) || null;
      continue;
    }
    const keys = f.labels.map(norm);
    const hit = pairs.find((p) => keys.some((k) => p.label === k || p.label.startsWith(k)));
    values[f.key] = hit?.value ?? null;
  }
  return { stepId: step.id, values };
}
