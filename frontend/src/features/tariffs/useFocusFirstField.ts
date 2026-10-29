import { useEffect, type RefObject } from 'react'

/** Entering a form puts the cursor in its first editable field. A date picker is
 * a button (Mantine's `data-dates-input`), so it is named too: without it a
 * version's first field would be taken for its notes. */
export function useFocusFirstField(ref: RefObject<HTMLElement | null>) {
  useEffect(() => {
    ref.current
      ?.querySelector<HTMLElement>('input:not([type="hidden"]):not(:disabled), select:not(:disabled), textarea:not(:disabled), button[data-dates-input]:not(:disabled)')
      ?.focus()
  }, [ref])
}
