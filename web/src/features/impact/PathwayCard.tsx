import { CARD_BOTTOM, CARD_TOP_CLEARANCE, PANEL_WIDTH, UI_GAP } from '../../lib/layout'
import type { ImpactResultProperties, ImpactStatus, PathwayStep } from '../../types/contracts'
import type { Affected } from './layers'
import { baselineAccess, featureName, type InfraLookup } from './labels'
import { cssColor, HAZARD_LABEL, STATUS_COLOR, STATUS_LABEL } from './style'

export interface PathwayCardProps {
  selectedId: string | null
  selected: Affected | null
  lookup: InfraLookup
  highlightId: string | null
  onHighlight: (id: string) => void
  onClose: () => void
}

// Bottom-left of the map, above the timeline and the attribution control; below the zoom buttons.

function StatusDot({ status }: { status: ImpactStatus }) {
  return (
    <span
      className="size-2.5 shrink-0 rounded-full"
      style={{ background: cssColor(STATUS_COLOR[status]) }}
      aria-hidden
    />
  )
}

function Step({
  step,
  last,
  lookup,
  highlighted,
  onHighlight,
}: {
  step: PathwayStep
  last: boolean
  lookup: InfraLookup
  highlighted: boolean
  onHighlight: (id: string) => void
}) {
  const onMap = step.type !== 'hazard' && lookup.has(step.id)
  const kind = step.type === 'hazard' ? 'Hazard' : onMap ? 'Infrastructure' : 'Not on the map'
  return (
    <li className="relative flex gap-2 pb-2">
      {!last && <span className="absolute top-3 left-[5px] h-full w-px bg-slate-300" aria-hidden />}
      <span
        className={`mt-1 size-2.5 shrink-0 rounded-full ${
          step.type === 'hazard' ? 'bg-slate-700' : 'border-2 border-slate-500 bg-white'
        }`}
        aria-hidden
      />
      {onMap ? (
        <button
          type="button"
          onClick={() => onHighlight(step.id)}
          className={`rounded px-1 text-left hover:bg-cyan-50 ${
            highlighted ? 'bg-cyan-100 ring-1 ring-cyan-500' : ''
          }`}
        >
          <span className="block">{step.label}</span>
          <span className="block text-[11px] text-slate-500">{kind} · show on map</span>
        </button>
      ) : (
        <span className="px-1">
          <span className="block">{step.label}</span>
          <span className="block text-[11px] text-slate-500">{kind}</span>
        </span>
      )}
    </li>
  )
}

function Pathway({
  row,
  lookup,
  highlightId,
  onHighlight,
}: {
  row: ImpactResultProperties
  lookup: InfraLookup
  highlightId: string | null
  onHighlight: (id: string) => void
}) {
  return (
    <div className="mt-2">
      <p className="mb-1 flex items-center gap-1.5 text-xs font-semibold">
        <StatusDot status={row.status} />
        {HAZARD_LABEL[row.hazard_type]}: {STATUS_LABEL[row.status].toLowerCase()}
      </p>
      <ol className="ml-1">
        {row.pathway.map((step, i) => (
          <Step
            key={`${step.id}-${i}`}
            step={step}
            last={i === row.pathway.length - 1}
            lookup={lookup}
            highlighted={step.id === highlightId}
            onHighlight={onHighlight}
          />
        ))}
      </ol>
    </div>
  )
}

/** Floating card with the selected feature's pathway (one chain per affected hazard). */
export default function PathwayCard(props: PathwayCardProps) {
  const { selectedId, selected, lookup } = props
  if (!selectedId) return null
  const access = baselineAccess(selectedId, lookup)
  return (
    <aside
      className="absolute overflow-y-auto rounded-lg bg-white p-3 text-sm text-slate-800 shadow-lg"
      style={{
        left: UI_GAP,
        bottom: CARD_BOTTOM,
        width: PANEL_WIDTH,
        maxHeight: `calc(100% - ${CARD_BOTTOM + CARD_TOP_CLEARANCE}px)`,
      }}
      aria-label="Impact pathway"
    >
      <div className="flex items-start gap-2">
        <p className="font-medium">{featureName(selectedId, lookup)}</p>
        <button
          type="button"
          onClick={props.onClose}
          className="-mt-1 ml-auto px-1 text-lg leading-none text-slate-400 hover:text-slate-700"
          aria-label="Close pathway"
        >
          ×
        </button>
      </div>
      {access && <p className="text-xs text-slate-500">{access}</p>}
      {selected ? (
        selected.rows.map((row) => (
          <Pathway
            key={row.id}
            row={row}
            lookup={lookup}
            highlightId={props.highlightId}
            onHighlight={props.onHighlight}
          />
        ))
      ) : (
        <p className="mt-1 text-xs text-slate-500">Not affected at this timestep.</p>
      )}
    </aside>
  )
}
