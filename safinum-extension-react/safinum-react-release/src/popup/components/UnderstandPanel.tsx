import { templates } from "../../data/templates";
import type { StepInfo } from "../../types/translation";

interface Props {
  info: StepInfo | null;
  onRefresh: () => void;
  onClose: () => void;
}

// Lecture seule : n'exécute aucune opération et n'invente aucune donnée.
export default function UnderstandPanel({ info, onRefresh, onClose }: Props) {
  const step = info && templates.steps.find((s) => s.id === info.stepId);
  return (
    <section className="understand" aria-label="Comprendre cette étape">
      <h2>Comprendre cette étape</h2>
      {!info || !step ? (
        <p className="muted">Impossible de lire la page. Rechargez-la, puis actualisez.</p>
      ) : (
        <>
          <p className="muted">{step.title}</p>
          <p>{step.intro}</p>
          {step.fields.length > 0 && (
            <dl>
              {step.fields.map((f) => {
                const v = info.values[f.key];
                return (
                  <div key={f.key} className="pair">
                    <dt>{f.label}</dt>
                    <dd className={v ? "" : "missing"}>{v || templates.notIndicated}</dd>
                  </div>
                );
              })}
            </dl>
          )}
          <p className="notice">{templates.notice}</p>
        </>
      )}
      <div className="actions row">
        <button type="button" onClick={onRefresh}>Actualiser</button>
        <button type="button" className="primary" onClick={onClose}>Retour</button>
      </div>
    </section>
  );
}
