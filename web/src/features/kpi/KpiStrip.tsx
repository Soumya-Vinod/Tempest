import { KPI_HEIGHT, KPI_LEFT, PANEL_WIDTH, UI_GAP } from '../../lib/layout'
import type { Kpi, KpiTone } from './useKpis'

const TONE: Record<KpiTone, string> = {
  neutral: 'text-slate-900',
  warn: 'text-amber-800',
  alert: 'text-red-800',
}

/**
 * The headline figures over the top of the map, for the scrubber's timestep and horizon, each
 * with its change since the previous timestep. Scrolls sideways when the window is narrow.
 */
export default function KpiStrip({ kpis, previousLabel }: { kpis: Kpi[]; previousLabel: string | null }) {
  return (
    <section
      aria-label="Key figures"
      className="absolute z-20 flex overflow-x-auto rounded-lg bg-white/95 shadow-lg backdrop-blur"
      style={{ top: UI_GAP, left: KPI_LEFT, right: PANEL_WIDTH + 2 * UI_GAP, height: KPI_HEIGHT }}
    >
      {kpis.map((k, i) => (
        <div
          key={k.id}
          title={k.title}
          className={`flex min-w-max flex-col justify-center px-3 ${i > 0 ? 'border-l border-slate-100' : ''}`}
        >
          <span className="text-[11px] leading-tight whitespace-nowrap text-slate-500">{k.label}</span>
          <span className="flex items-baseline gap-1.5 whitespace-nowrap">
            <span className={`text-base leading-6 font-semibold tabular-nums ${TONE[k.tone ?? 'neutral']}`}>
              {k.value ?? '…'}
            </span>
            {k.delta && previousLabel && (
              <span
                className={`text-[11px] tabular-nums ${
                  k.upIsWorse && (k.change ?? 0) > 0 ? 'text-red-700' : 'text-slate-500'
                }`}
                title={`Change since ${previousLabel}`}
              >
                {k.delta}
              </span>
            )}
          </span>
        </div>
      ))}
    </section>
  )
}
