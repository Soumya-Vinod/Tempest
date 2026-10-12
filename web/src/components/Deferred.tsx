import { type ReactNode, Suspense, useState } from 'react'

/**
 * Renders `children` (lazy components, in Suspense) only once `when` has first been true, then
 * keeps them mounted so they keep their state. Their code isn't fetched until then.
 */
export default function Deferred({
  when,
  fallback = null,
  children,
}: {
  when: boolean
  fallback?: ReactNode
  children: ReactNode
}) {
  const [seen, setSeen] = useState(when)
  if (when && !seen) setSeen(true)
  if (!when && !seen) return null
  return <Suspense fallback={fallback}>{children}</Suspense>
}
