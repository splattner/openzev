import { useLayoutEffect, useState } from 'react'

/**
 * Whether an element is at least `minRem` wide, kept current as it resizes.
 * Measures the element, not the viewport: a sidebar or a narrower shell
 * changes how much room a layout really has. Returns the ref to put on the
 * element (a callback, so an element that mounts late is still measured) and
 * the answer. Assumed wide until measured, and where `ResizeObserver` is
 * missing.
 */
export function useMinWidth<T extends HTMLElement>(minRem: number): [(element: T | null) => void, boolean] {
    const [element, setElement] = useState<T | null>(null)
    const [fits, setFits] = useState(true)

    useLayoutEffect(() => {
        if (!element || typeof ResizeObserver === 'undefined') return
        const rootFontSize = parseFloat(getComputedStyle(document.documentElement).fontSize) || 16
        const measure = () => setFits(element.getBoundingClientRect().width >= minRem * rootFontSize)
        measure()
        const observer = new ResizeObserver(measure)
        observer.observe(element)
        return () => observer.disconnect()
    }, [element, minRem])

    return [setElement, fits]
}
