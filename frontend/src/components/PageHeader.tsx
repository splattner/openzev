import { useId, type ReactNode } from 'react'
import { useDocumentTitle } from '../lib/useDocumentTitle'
import { CommunitySwitcher } from './CommunitySwitcher'

export type PageHeaderProps = {
    /** Community name above the title. */
    eyebrow?: ReactNode
    /** The eyebrow names the selected community: it opens the community list
     * when the account has more than one. */
    communitySwitch?: boolean
    /** Access label beside the community (a viewer's read-only access); excluded from the browser title. */
    scopeNote?: string
    /** Plain text: it also names the browser tab. */
    title: string
    description?: ReactNode
    /** Page-level actions. One primary action per page (SPEC-2026-04 §7.3). */
    actions?: ReactNode
}

export function PageHeader({ eyebrow, communitySwitch, scopeNote, title, description, actions }: PageHeaderProps) {
    useDocumentTitle(title, typeof eyebrow === 'string' ? eyebrow : undefined)
    // Focus lands on the h1 after navigation; it describes itself by the scope line.
    const eyebrowId = useId()

    return (
        <header className="page-header">
            {eyebrow ? (
                <p className="eyebrow" id={eyebrowId}>
                    {communitySwitch ? <CommunitySwitcher name={eyebrow} /> : eyebrow}
                    {scopeNote ? <span className="eyebrow-note"> · {scopeNote}</span> : null}
                </p>
            ) : null}
            <div className="page-header-main">
                <div className="page-header-text">
                    {/* Focus target after navigation (useRouteFocus); not a tab stop. */}
                    <h1 tabIndex={-1} aria-describedby={eyebrow ? eyebrowId : undefined}>{title}</h1>
                    {description ? <p className="muted">{description}</p> : null}
                </div>
                {actions ? <div className="actions-row page-header-actions">{actions}</div> : null}
            </div>
        </header>
    )
}
