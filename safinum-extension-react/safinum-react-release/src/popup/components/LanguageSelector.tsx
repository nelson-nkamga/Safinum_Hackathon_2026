import type { Language } from "../../types/translation";

interface Props {
  languages: Language[];
  value: string;
  disabled?: boolean;
  onChange: (code: string) => void;
}

// Seules les directions réellement prises en charge (available) sont sélectionnables.
export default function LanguageSelector({ languages, value, disabled, onChange }: Props) {
  const empty = languages.length === 0;
  return (
    <>
      <label className="field" htmlFor="lang">Langue</label>
      <select id="lang" value={value} disabled={disabled || empty} onChange={(e) => onChange(e.target.value)}>
        <option value="">{empty ? "Aucune langue disponible" : "Choisir une langue…"}</option>
        {languages.map((l) => (
          <option key={l.code} value={l.code} disabled={!l.available}>
            {l.available ? l.name : `${l.name} (non vérifiée)`}
          </option>
        ))}
      </select>
    </>
  );
}
