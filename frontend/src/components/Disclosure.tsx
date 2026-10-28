import { useState, type ReactNode } from 'react'

type DisclosureProps = {
    summary: ReactNode
    children: ReactNode
    /** Starts open (uncontrolled). */
    defaultOpen?: boolean
    /** Open state owned by the caller, with `onOpenChange`. */
    open?: boolean
    onOpenChange?: (open: boolean) => void
    /** Mount the body only while open, so a closed disclosure costs no request or chart. */
    lazy?: boolean
    /** Modifiers for the host's own layout; the shared look comes from `.disclosure`. */
    className?: string
}

/**
 * Secondary content on demand (SPEC-2026-10-ui-patterns §6.3): native
 * `details/summary`, closed unless told otherwise. It supplements the working
 * view; content that replaces it is a tab.
 */
export function Disclosure({ summary, children, defaultOpen = false, open, onOpenChange, lazy = false, className }: DisclosureProps) {
    const [innerOpen, setInnerOpen] = useState(defaultOpen)
    const isOpen = open ?? innerOpen
    return (
        <details
            className={className ? `disclosure ${className}` : 'disclosure'}
            open={isOpen}
            onToggle={(event) => {
                const next = event.currentTarget.open
                // The attribute set from `open` toggles too; only a change is news.
                if (next === isOpen) return
                setInnerOpen(next)
                onOpenChange?.(next)
            }}
        >
            <summary>{summary}</summary>
            {(!lazy || isOpen) && children}
        </details>
    )
}
