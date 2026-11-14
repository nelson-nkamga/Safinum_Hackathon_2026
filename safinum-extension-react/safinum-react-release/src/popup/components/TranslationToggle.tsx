interface Props {
  checked: boolean;
  disabled?: boolean;
  onChange: (checked: boolean) => void;
}

export default function TranslationToggle({ checked, disabled, onChange }: Props) {
  return (
    <label className="switch">
      <input
        type="checkbox"
        role="switch"
        checked={checked}
        disabled={disabled}
        onChange={(e) => onChange(e.target.checked)}
      />
      <span>Traduire cette page</span>
    </label>
  );
}
