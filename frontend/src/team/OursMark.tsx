/** The gold diamond after our team's number, with a text equivalent. Renders nothing for any other team. */
export function OursMark({ team, ours }: { team: number; ours: number | null }) {
  if (ours === null || team !== ours) return null
  return <><span className="ours-mark" aria-hidden="true" /><span className="visually-hidden"> (our team)</span></>
}
