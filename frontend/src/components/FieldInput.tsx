import type { CustomValue, Field } from "../types";

export function FieldInput({ field, value, onChange }: { field: Field; value: CustomValue | undefined; onChange: (v: CustomValue | undefined) => void }) {
  const id = `f-${field.key}`;
  const label = (
    <label htmlFor={id} className={field.type === "multiselect" ? "visually-hidden" : undefined}>
      {field.label}
    </label>
  );
  switch (field.type) {
    case "boolean":
      return (
        <div className="field">
          <span className="field-label">{field.label}</span>
          <label className="check">
            <input id={id} type="checkbox" checked={!!value} onChange={(e) => onChange(e.target.checked || undefined)} />
            Yes
          </label>
        </div>
      );
    case "select": {
      const opts = typeof value === "string" && value && !field.options.includes(value) ? [...field.options, value] : field.options;
      return (
        <div className="field">
          {label}
          <select id={id} className="input" value={typeof value === "string" ? value : ""} onChange={(e) => onChange(e.target.value || undefined)}>
            <option value="">—</option>
            {opts.map((o) => (
              <option key={o} value={o}>
                {o}
              </option>
            ))}
          </select>
        </div>
      );
    }
    case "multiselect": {
      const current = Array.isArray(value) ? value : [];
      const opts = [...field.options, ...current.filter((v) => !field.options.includes(v))];
      return (
        <div className="field">
          <span className="field-label">{field.label}</span>
          <div className="chips" role="group" aria-label={field.label}>
            {opts.map((o) => {
              const on = current.includes(o);
              return (
                <button
                  key={o}
                  type="button"
                  className="chip"
                  aria-pressed={on}
                  onClick={() => {
                    const next = on ? current.filter((x) => x !== o) : [...current, o];
                    onChange(next.length ? next : undefined);
                  }}
                >
                  {o}
                </button>
              );
            })}
          </div>
        </div>
      );
    }
    case "longtext":
      return (
        <div className="field" style={{ gridColumn: "1 / -1" }}>
          {label}
          <textarea id={id} className="input" value={typeof value === "string" ? value : ""} onChange={(e) => onChange(e.target.value || undefined)} />
        </div>
      );
    case "number":
      return (
        <div className="field">
          {label}
          <input
            id={id}
            className="input"
            type="number"
            inputMode="decimal"
            step="any"
            value={value === undefined ? "" : String(value)}
            onChange={(e) => onChange(e.target.value === "" ? undefined : Number(e.target.value))}
          />
        </div>
      );
    case "date":
      return (
        <div className="field">
          {label}
          <input id={id} className="input" type="date" value={typeof value === "string" ? value : ""} onChange={(e) => onChange(e.target.value || undefined)} />
        </div>
      );
    default:
      return (
        <div className="field">
          {label}
          <input id={id} className="input" value={typeof value === "string" ? value : value === undefined ? "" : String(value)} onChange={(e) => onChange(e.target.value || undefined)} />
        </div>
      );
  }
}
