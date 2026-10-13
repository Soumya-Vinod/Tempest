import { KPI_HEIGHT, useLayout } from '../../lib/layout'
import type { Kpi, KpiTone } from './useKpis'

const TONE: Record<KpiTone, string> = {
  neutral: 'text-ink',
  warn: 'text-ink',
  alert: 'text-sev-cut',
}

/**
 * The headline figures over the top of the map, for the scrubber's timestep and horizon: the
 * landfall countdown first, then at most four figures in neutral ink (severity colour only on
 * "cut off now"), each with its change since the previous timestep in grey when there is one.
 * Scrolls sideways (swipe on phones) when the window is too narrow, a figure at a time.
 */
export default function KpiStrip({ kpis, previousLabel }: { kpis: Kpi[]; previousLabel: string | null }) {
  const { gap, kpiLeft, mapRight } = useLayout()
  return (
    <section
      aria-label="Key figures"
      // Focusable, so the strip can be scrolled from the keyboard when it overflows.
      tabIndex={0}
      className="absolute z-20 flex snap-x snap-mandatory overflow-x-auto overscroll-x-contain rounded-panel border border-line bg-white/95 shadow-sm backdrop-blur"
      style={{ top: gap, left: kpiLeft, right: mapRight, height: KPI_HEIGHT }}
    >
      {kpis.map((k, i) => (
        <div
          key={k.id}
          title={k.value === null && k.failed ? `Data unavailable. ${k.title ?? ''}`.trim() : k.title}
          className={`flex min-w-max snap-start flex-col justify-center px-4 ${
            k.lead ? 'bg-surface' : ''
          } ${i > 0 ? 'border-l border-line' : ''}`}
        >
          <span className="text-caption whitespace-nowrap text-ink-subtle">{k.label}</span>
          <span className="flex items-baseline gap-2 whitespace-nowrap">
            <span
              className={`text-figure tabular-nums ${k.lead ? 'font-semibold' : 'font-medium'} ${TONE[k.tone ?? 'neutral']}`}
            >
              {k.value ?? (k.failed ? '—' : '…')}
            </span>
            {k.delta && previousLabel && (
              <span className="text-caption text-ink-subtle tabular-nums" title={`Change since ${previousLabel}`}>
                {k.delta}
              </span>
            )}
          </span>
        </div>
      ))}
    </section>
  )
}
