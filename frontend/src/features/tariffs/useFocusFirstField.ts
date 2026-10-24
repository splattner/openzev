import { useEffect, type RefObject } from 'react'

/** Entering a form puts the cursor in its first editable field. */
export function useFocusFirstField(ref: RefObject<HTMLElement | null>) {
  useEffect(() => {
    ref.current
      ?.querySelector<HTMLElement>('input:not([type="hidden"]):not(:disabled), select:not(:disabled), textarea:not(:disabled)')
      ?.focus()
  }, [ref])
}
