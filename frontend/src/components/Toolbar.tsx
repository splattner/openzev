import type { ReactNode } from 'react'

export type ToolbarProps = {
    children?: ReactNode
    actions?: ReactNode
}

export function Toolbar({ children, actions }: ToolbarProps) {
    return (
        <div className="toolbar">
            {children ? <div className="toolbar-main">{children}</div> : null}
            {actions ? <div className="toolbar-actions">{actions}</div> : null}
        </div>
    )
}
