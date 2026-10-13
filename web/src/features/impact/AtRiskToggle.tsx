import StatusSwatch from './StatusSwatch'

/** Layers: the watch tier's at-risk roads and lines (off by default, to keep the map quiet). */
export default function AtRiskToggle({ on, onToggle }: { on: boolean; onToggle: () => void }) {
  return (
    <section>
      <label className="flex cursor-pointer items-center gap-2 text-xs text-slate-700">
        <input type="checkbox" checked={on} onChange={onToggle} className="accent-accent" />
        <StatusSwatch status="at_risk" />
        Show at-risk roads, lines and facilities
      </label>
      <p className="mt-0.5 ml-5 text-[11px] text-slate-500">
        Cut and cut-off features always show. At-risk facilities also show in the Risk view.
      </p>
    </section>
  )
}
