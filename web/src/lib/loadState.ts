/** A data request that has failed for good (an error, or the data isn't available): not loading. */
export const failed = (s: { status: string }) => s.status === 'error' || s.status === 'unavailable'
