import type { ReactNode } from 'react'

export type PageHeaderProps = {
    /** Community name above the title. */
    eyebrow?: ReactNode
    title: ReactNode
    description?: ReactNode
    /** Page-level actions. One primary action per page (SPEC-2026-04 §7.3). */
    actions?: ReactNode
}

export function PageHeader({ eyebrow, title, description, actions }: PageHeaderProps) {
    return (
        <header className="page-header">
            {eyebrow ? <p className="eyebrow">{eyebrow}</p> : null}
            <div className="page-header-main">
                <div className="page-header-text">
                    <h1>{title}</h1>
                    {description ? <p className="muted">{description}</p> : null}
                </div>
                {actions ? <div className="actions-row page-header-actions">{actions}</div> : null}
            </div>
        </header>
    )
}
