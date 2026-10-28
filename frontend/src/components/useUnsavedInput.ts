import { useCallback, useEffect, useRef, type RefObject } from 'react'

const INERT_INPUT_TYPES = new Set(['button', 'submit', 'reset', 'image'])

/** What the user could have changed in `root`, in document order, as one comparable string. */
export function snapshotControls(root: HTMLElement): string {
    const values = Array.from(root.querySelectorAll<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>('input, select, textarea'), (control) => {
        if (control instanceof HTMLInputElement) {
            if (INERT_INPUT_TYPES.has(control.type)) return null
            if (control.type === 'checkbox' || control.type === 'radio') return control.checked
            if (control.type === 'file') return Array.from(control.files ?? [], (file) => `${file.name}:${file.size}`)
        }
        return control.value
    })
    return JSON.stringify(values)
}

/**
 * Whether the user has changed anything inside `ref` (SPEC-2026-10-ui-patterns §6.1).
 * No form has to report it: the controls are read at the first keystroke or
 * pointer press inside the element, and again when asked, so a prefilled or
 * late-loaded form counts as clean until the user touches it. Mantine's hidden
 * inputs carry the chosen value, so pickers count too.
 */
export function useUnsavedInput(ref: RefObject<HTMLElement | null>) {
    const baseline = useRef<string | null>(null)

    useEffect(() => {
        const node = ref.current
        if (!node) return
        const capture = () => { baseline.current ??= snapshotControls(node) }
        const events = ['pointerdown', 'keydown', 'beforeinput'] as const
        events.forEach((name) => node.addEventListener(name, capture, true))
        return () => events.forEach((name) => node.removeEventListener(name, capture, true))
    }, [ref])

    return useCallback(() => {
        const node = ref.current
        return node !== null && baseline.current !== null && snapshotControls(node) !== baseline.current
    }, [ref])
}
