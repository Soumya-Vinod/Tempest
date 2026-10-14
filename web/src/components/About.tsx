import type { ReactNode } from 'react'

/**
 * "About this view": the long explanatory text of a section, folded away (closed by default) so
 * the section leads with what to do. The text itself is unchanged.
 */
export default function About({ children }: { children: ReactNode }) {
  return (
    <details className="group mt-1">
      <summary className="cursor-pointer list-none text-[11px] text-accent hover:underline [&::-webkit-details-marker]:hidden">
        <span aria-hidden className="mr-1 inline-block transition-transform group-open:rotate-90 motion-reduce:transition-none">
          ›
        </span>
        About this view
      </summary>
      <div className="mt-1 space-y-1 text-[11px] text-ink-subtle">{children}</div>
    </details>
  )
}
