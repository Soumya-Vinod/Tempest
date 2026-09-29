import { ABOUT_THE_DATA } from './sources'

/** "About the data": collapsed by default, at the bottom of the side panel. */
export default function AboutPanel() {
  return (
    <details className="mt-5 border-t border-slate-200 pt-3">
      <summary className="cursor-pointer text-xs font-semibold tracking-wide text-slate-500 uppercase">
        About the data
      </summary>
      <div className="mt-2 space-y-3">
        {ABOUT_THE_DATA.map((group) => (
          <section key={group.title}>
            <h3 className="text-xs font-semibold text-slate-700">{group.title}</h3>
            <dl className="mt-1 space-y-1.5 text-[11px] text-slate-600">
              {group.items.map((item) => (
                <div key={item.name}>
                  <dt className="font-medium text-slate-700">{item.name}</dt>
                  <dd>{item.detail}</dd>
                </div>
              ))}
            </dl>
          </section>
        ))}
      </div>
    </details>
  )
}
