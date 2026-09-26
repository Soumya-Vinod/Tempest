import { ApiError } from '../../lib/api'

/** The API's error detail as text: a message, plus the check's problems when there are any. */
export function errorText(err: unknown): string {
  if (err instanceof ApiError && typeof err.detail === 'object' && err.detail !== null) {
    const d = err.detail as { message?: string; problems?: string[] }
    return [d.message, ...(d.problems ?? [])].filter(Boolean).join(' · ')
  }
  return err instanceof Error ? err.message : String(err)
}
