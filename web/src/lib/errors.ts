// What the UI says when a request fails. The API's details are written for developers ("roads.graphml
// not found; run api/scripts/ingest_osm.py"): they go to the console only, never on screen.
import { ApiError } from './api'

/** "Impact data is unavailable right now." for a failed load of `subject`; logs the raw error. */
export function unavailableText(subject: string, err: unknown): string {
  console.warn(`${subject}: request failed.`, err)
  return err instanceof ApiError
    ? `${subject} is unavailable right now.`
    : `${subject} is unavailable: the server can't be reached.`
}

/**
 * For a failed action (generate, approve, dispatch...): the API's own explanation when it is
 * meant for the user (a 4xx with a message, or the check's problems), else plain words. The raw
 * error is logged.
 */
export function actionErrorText(err: unknown): string {
  console.warn('Action failed.', err)
  if (!(err instanceof ApiError)) return "Can't reach the server. Please try again."
  if (err.status < 500) {
    const d = err.detail
    if (typeof d === 'string' && d) return d
    if (typeof d === 'object' && d !== null && !Array.isArray(d)) {
      const { message, problems } = d as { message?: string; problems?: string[] }
      const text = [message, ...(problems ?? [])].filter(Boolean).join(' · ')
      if (text) return text
    }
    return 'That request was not accepted. Please check it and try again.'
  }
  return "The server couldn't do this right now. Please try again later."
}
