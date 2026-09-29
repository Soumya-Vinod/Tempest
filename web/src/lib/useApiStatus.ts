import { useSyncExternalStore } from 'react'

import { type ApiStatus, getApiStatus, subscribeApiStatus } from './api'

/** The API request queue's status (lib/api.ts): busy, and waking (a slow first response). */
export function useApiStatus(): ApiStatus {
  return useSyncExternalStore(subscribeApiStatus, getApiStatus)
}
