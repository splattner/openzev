import { useId } from 'react'
import { Chip } from '@mantine/core'
import { recurrenceValue, selectedRecurrence } from './recurrence'

type RecurrenceChipsProps = {
  label: string
  hint: string
  /** The stored mask: comma-separated numbers, blank meaning every option. */
  value: string
  onChange: (next: string) => void
  options: Array<{ value: number; label: string }>
  /** Columns to lay the chips out in — 7 for weekdays, 6 for months. */
  columns: number
}

/**
 * Toggle group for the two axes a price band recurs on — its weekdays and its
 * months.
 *
 * Both were free-text lists of numbers, which asked the user to know that
 * Monday is 0 while January is 1, and gave no feedback until the server
 * rejected the string. The chips carry the whole answer: which options exist,
 * which apply, and — because blank is rendered as everything lit — that a band
 * with no restriction applies to all of them.
 *
 * Laid out on a fixed grid rather than wrapped: a selected chip is wider than
 * an unselected one, so under flex-wrap every click reflowed the rows below
 * it, and twelve months of uneven width wrapped raggedly. Fixed columns keep
 * the block still while it is being used, and give months a 6x2 block that
 * reads as two half-years.
 *
 * A group is `role="group"` rather than a `<fieldset>`: a legend does not lay
 * out predictably inside a grid, and a `<label>` wrapping seven checkboxes
 * would target only the first.
 */
export function RecurrenceChips({ label, hint, value, onChange, options, columns }: RecurrenceChipsProps) {
  const labelId = useId()
  const selected = selectedRecurrence(value, options.map((option) => option.value))

  function handleChange(next: string[]) {
    const stored = recurrenceValue(next, options.length)
    // null means the change would leave nothing selected, which is not a state
    // the field can hold — the click is a no-op rather than a silent surprise.
    if (stored !== null) onChange(stored)
  }

  return (
    <div className="recurrence-field grid-span-full" role="group" aria-labelledby={labelId}>
      <span id={labelId}>{label}</span>
      <Chip.Group multiple value={selected} onChange={handleChange}>
        <div
          className="recurrence-chips"
          style={{ gridTemplateColumns: `repeat(${columns}, minmax(0, 1fr))` }}
        >
          {options.map((option) => (
            <Chip
              key={option.value}
              value={String(option.value)}
              size="sm"
              radius="sm"
              classNames={{ label: 'recurrence-chip', input: 'recurrence-chip-input' }}
            >
              {option.label}
            </Chip>
          ))}
        </div>
      </Chip.Group>
      <small className="muted">{hint}</small>
    </div>
  )
}
