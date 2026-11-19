import type { ReactElement } from 'react'
import { Tooltip } from '@mantine/core'

export function ActionTooltip({ label, disabled, children }: {
    label?: string
    disabled?: boolean
    children: ReactElement
}) {
    return (
        <Tooltip label={label} disabled={disabled || !label} events={{ hover: true, focus: true, touch: false }}>
            {children}
        </Tooltip>
    )
}
