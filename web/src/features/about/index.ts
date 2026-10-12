// About the data: sources, models and limits (sources.ts is the one place to update them).
import { lazy } from 'react'

// Code-split: loaded the first time it is shown (see components/Deferred).
export const AboutPanel = lazy(() => import('./AboutPanel'))
export { ABOUT_THE_DATA, FORECAST_FRAMING } from './sources'
