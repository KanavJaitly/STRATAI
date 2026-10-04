// An editable table of rows: used for scoring actions, ranking-point rules, field elements, codebook functions,
// the action map and rubric archetypes.

export interface Column<R> {
  key: keyof R & string
  label: string
  type?: 'text' | 'number' | 'select'
  options?: readonly string[]
  width?: string
  placeholder?: string
  list?: string // a <datalist> id offering suggestions
}

interface Props<R> {
  label: string
  rows: R[]
  columns: Column<R>[]
  onChange: (rows: R[]) => void
  newRow: () => R
  disabled?: boolean
}

export function RowsEditor<R extends { [K in keyof R]: string }>({ label, rows, columns, onChange, newRow, disabled }: Props<R>) {
  const update = (index: number, key: keyof R, value: string) =>
    onChange(rows.map((row, i) => (i === index ? { ...row, [key]: value } : row)))
  return (
    <fieldset className="rows-editor" disabled={disabled}>
      <legend>{label}</legend>
      {rows.length === 0 && <p className="muted small">None yet.</p>}
      {rows.length > 0 && (
        <div className="table-scroll">
          <table className="grid compact">
            <thead>
              <tr>
                {columns.map((c) => <th key={c.key} style={{ width: c.width }}>{c.label}</th>)}
                <th aria-label="actions" />
              </tr>
            </thead>
            <tbody>
              {rows.map((row, index) => (
                <tr key={index}>
                  {columns.map((c) => (
                    <td key={c.key}>
                      {c.type === 'select' ? (
                        <select aria-label={`${label} ${index + 1} ${c.label}`} value={row[c.key]}
                          onChange={(e) => update(index, c.key, e.target.value)}>
                          <option value="">—</option>
                          {(c.options ?? []).map((o) => <option key={o} value={o}>{o}</option>)}
                        </select>
                      ) : (
                        <input aria-label={`${label} ${index + 1} ${c.label}`} value={row[c.key]}
                          inputMode={c.type === 'number' ? 'decimal' : undefined} placeholder={c.placeholder}
                          list={c.list} onChange={(e) => update(index, c.key, e.target.value)} />
                      )}
                    </td>
                  ))}
                  <td>
                    <button type="button" className="link danger" onClick={() => onChange(rows.filter((_, i) => i !== index))}
                      aria-label={`Remove ${label} ${index + 1}`}>
                      remove
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <button type="button" className="secondary" onClick={() => onChange([...rows, newRow()])}>
        Add {label.toLowerCase().replace(/s$/, '')}
      </button>
    </fieldset>
  )
}
