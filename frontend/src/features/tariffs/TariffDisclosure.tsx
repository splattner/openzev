import { useState, type ReactNode } from 'react'

type TariffDisclosureProps = {
    summary: ReactNode
    /** Opens when the group holds what the pane is showing. */
    defaultOpen?: boolean
    children: ReactNode
}

/**
 * Secondary pane content on demand: native details/summary, closed unless
 * told otherwise. Its body mounts only while open, so a closed disclosure
 * costs no request or chart. The shared `Disclosure` (UI patterns phase 2)
 * replaces it.
 */
export function TariffDisclosure({ summary, defaultOpen = false, children }: TariffDisclosureProps) {
    const [open, setOpen] = useState(defaultOpen)
    return (
        <details className="tariff-disclosure" open={open} onToggle={(event) => setOpen(event.currentTarget.open)}>
            <summary>{summary}</summary>
            {open && children}
        </details>
    )
}
