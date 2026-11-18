import type { ComponentPropsWithRef } from 'react'
import { ActionTooltip } from './ActionTooltip'

type Props = Omit<ComponentPropsWithRef<'button'>, 'aria-label'> & {
    label: string
    danger?: boolean
}

export function IconActionButton({ label, danger, disabled, className, children, ...props }: Props) {
    return (
        <ActionTooltip label={label} disabled={disabled}>
            <button
                type="button"
                {...props}
                className={`button ${danger ? 'button-danger' : 'button-secondary'} button-compact button-icon${className ? ` ${className}` : ''}`}
                aria-label={label}
                disabled={disabled}
            >
                {children}
            </button>
        </ActionTooltip>
    )
}
