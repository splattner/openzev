import { FontAwesomeIcon } from '@fortawesome/react-fontawesome'
import type { IconDefinition } from '@fortawesome/free-solid-svg-icons'
import { useId } from 'react'
import { Link } from 'react-router-dom'
import { useTranslation } from 'react-i18next'

export type EmptyStateAction = {
    labelKey: string
    variant?: 'primary' | 'secondary'
    icon?: IconDefinition
} & (
    | { to: string; onClick?: never }
    | { onClick: () => void; to?: never }
)

export type EmptyStateProps = {
    titleKey: string
    descriptionKey: string
    actions?: EmptyStateAction[]
}

export function EmptyState({ titleKey, descriptionKey, actions }: EmptyStateProps) {
    const { t } = useTranslation()
    const titleId = useId()
    const descId = useId()

    return (
        <section className="card empty-state" aria-labelledby={titleId} aria-describedby={descId}>
            <h3 id={titleId}>{t(titleKey)}</h3>
            <p id={descId} className="muted">{t(descriptionKey)}</p>
            {actions?.length ? (
                <div className="actions-row actions-row-wrap">
                    {actions.map((action, index) => (
                        <ActionButton
                            key={`${action.labelKey}:${typeof action.to === 'string' ? action.to : action.variant ?? 'action'}-${index}`}
                            action={action}
                            label={t(action.labelKey)}
                        />
                    ))}
                </div>
            ) : null}
        </section>
    )
}

function ActionButton({ action, label }: { action: EmptyStateAction; label: string }) {
    const variantClass =
        action.variant === 'secondary' ? 'button button-secondary' : 'button button-primary'
    const content = (
        <>
            {action.icon && <FontAwesomeIcon icon={action.icon} fixedWidth aria-hidden="true" />}
            {label}
        </>
    )

    if (typeof action.to === 'string' && action.to.length > 0) {
        return (
            <Link className={variantClass} to={action.to}>
                {content}
            </Link>
        )
    }

    if (typeof action.onClick === 'function') {
        return (
            <button type="button" className={variantClass} onClick={action.onClick}>
                {content}
            </button>
        )
    }

    return null
}
