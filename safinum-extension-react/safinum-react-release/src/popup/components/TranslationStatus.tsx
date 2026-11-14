import type { TabState } from "../../types/translation";

export default function TranslationStatus({ state }: { state: TabState | null }) {
  if (!state?.enabled) return <p className="stats muted" aria-live="polite" />;
  const s = state.stats;
  const parts: Array<[number, string]> = [
    [s.human_validated, "validées"],
    [s.model_generated, "générées par IA"],
    [s.mock, "simulées"],
    [s.pending, "en cours"],
    [s.unavailable + s.error, "non traduites"]
  ];
  const text = parts.filter(([n]) => n > 0).map(([n, label]) => `${n} ${label}`).join(" · ");
  return (
    <p className="stats muted" aria-live="polite">
      {text || "Aucun texte à traduire"}
    </p>
  );
}
