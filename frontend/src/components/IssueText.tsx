import type { ReactNode } from 'react'
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome'
import { faTriangleExclamation } from '@fortawesome/free-solid-svg-icons'
import { Link } from 'react-router-dom'
import './IssueText.css'

export type IssueTextProps = {
    children: ReactNode
    /** `error` is a problem to fix, `warning` one to look at. */
    tone?: 'error' | 'warning'
    /** Where the fix is, for a user who may use it. Omitted for a read-only user: the text stays, the click affordance goes. */
    to?: string
    onClick?: () => void
    title?: string
    'aria-label'?: string
}

/**
 * A concrete problem as short coloured text with its fix a click away, the
 * reference being "Kein Messpunkt" on a participant (UI patterns §10.1). No
 * capsule: a filled pill is for a state, not for something to do.
 */
export function IssueText({ children, tone = 'error', to, onClick, title, 'aria-label': ariaLabel }: IssueTextProps) {
    const className = `issue-text issue-text--${tone}`
    const content = (
        <>
            <FontAwesomeIcon icon={faTriangleExclamation} fixedWidth aria-hidden="true" />
            <span>{children}</span>
        </>
    )
    if (to) return <Link className={className} to={to} title={title} aria-label={ariaLabel}>{content}</Link>
    if (onClick) return <button type="button" className={className} onClick={onClick} title={title} aria-label={ariaLabel}>{content}</button>
    return <span className={className} title={title}>{content}</span>
}
