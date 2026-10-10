export type FilterTab<T> = {
  value: T
  label: string
  count: number
  /** Marks the count in the danger tone while it is above zero. */
  attention?: boolean
}

type FilterTabsProps<T> = {
  /** Accessible name of the group. */
  label: string
  /** The first tab is the default view: it always shows, and pressing an
   * active tab again returns to it. */
  tabs: Array<FilterTab<T>>
  value: T
  onChange: (value: T) => void
}

/** Counted, mutually exclusive views of one list. A tab with nothing to show,
 * or with as many entries as the default (the same list), is left out unless
 * it is the active one, so it can still be cleared; a default tab left on its
 * own offers no choice, so the group is too. */
export function FilterTabs<T>({ label, tabs, value, onChange }: FilterTabsProps<T>) {
  const defaultValue = tabs[0]?.value
  const defaultCount = tabs[0]?.count
  const shown = tabs.filter((tab, index) => index === 0
    || tab.value === value
    || (tab.count > 0 && tab.count !== defaultCount))
  if (shown.length < 2) return null
  return (
    <div className="filter-tabs" role="group" aria-label={label}>
      {shown.map((tab) => {
        const pressed = tab.value === value
        return (
          <button
            key={String(tab.value)}
            type="button"
            className={`filter-tab${tab.attention && tab.count > 0 ? ' filter-tab--attention' : ''}`}
            aria-pressed={pressed}
            onClick={() => onChange(pressed ? (defaultValue as T) : tab.value)}
          >
            {/* The space keeps the accessible name "Drafts 2"; flex layout drops it visually. */}
            {tab.label}{' '}
            <span className="filter-tab-count">{tab.count}</span>
          </button>
        )
      })}
    </div>
  )
}
