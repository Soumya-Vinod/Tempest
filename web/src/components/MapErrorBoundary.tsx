import { Component, type ErrorInfo, Fragment, type ReactNode } from 'react'

import { PANEL_WIDTH, UI_GAP } from '../lib/layout'

interface State {
  error: Error | null
  /** Bumped by "Reload map": a new key remounts the map without reloading the page. */
  attempt: number
}

/**
 * Around the map only: if the map fails (WebGL unavailable, a lost context it can't recover
 * from...), the panels and the timeline stay up and the map area offers a reload of the map.
 */
export default class MapErrorBoundary extends Component<{ children: ReactNode }, State> {
  state: State = { error: null, attempt: 0 }

  static getDerivedStateFromError(error: Error): Partial<State> {
    return { error }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error('Map failed; the panels stay up.', error, info.componentStack)
  }

  private reload = () => this.setState((s) => ({ error: null, attempt: s.attempt + 1 }))

  render() {
    if (!this.state.error) return <Fragment key={this.state.attempt}>{this.props.children}</Fragment>
    return (
      <div
        className="absolute inset-0 flex items-center justify-center bg-slate-100"
        style={{ paddingRight: PANEL_WIDTH + 2 * UI_GAP }}
        role="alert"
      >
        <div className="max-w-sm rounded-lg bg-white p-4 text-center text-sm text-slate-700 shadow">
          <p className="font-semibold text-slate-800">Map paused — reload map</p>
          <p className="mt-1 text-xs text-slate-500">
            The map stopped (graphics error). The panels and timeline still work.
          </p>
          <button
            type="button"
            onClick={this.reload}
            className="mt-3 rounded bg-violet-700 px-3 py-1 text-xs font-medium text-white hover:bg-violet-800"
          >
            Reload map
          </button>
        </div>
      </div>
    )
  }
}
