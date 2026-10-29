import { useId, type KeyboardEvent, type ReactNode, type Ref } from 'react'
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome'
import { faXmark } from '@fortawesome/free-solid-svg-icons'
import { useTranslation } from 'react-i18next'

type DetailPaneProps = {
    title: string
    /** One quiet line under the title. */
    subtitle?: ReactNode
    /** Something under the line that needs a look (a failed price fetch). */
    notice?: ReactNode
    /** X, and Escape while the pane has focus: leave the pane. */
    onClose: () => void
    /** `brand`: the header in the brand's dark green, as the list's group bands. */
    tone?: 'brand'
    /** The title is where focus lands when the pane is opened on purpose. */
    titleRef?: Ref<HTMLHeadingElement>
    children: ReactNode
}

/**
 * The chrome of a detail pane beside its list (SPEC-2026-10-ui-patterns §6.2,
 * §7.2): a region named by its title, a close button, and the body. Not modal:
 * no `aria-modal`, no focus trap, nothing around it made inert. Lay it out in a
 * `.detail-split` next to a `.detail-split-list`.
 */
export function DetailPane({ title, subtitle, notice, onClose, tone, titleRef, children }: DetailPaneProps) {
    const { t } = useTranslation()
    const titleId = useId()

    function onKeyDown(event: KeyboardEvent<HTMLElement>) {
        // A menu or picker inside the pane takes the Escape that dismisses it.
        if (event.key === 'Escape' && !event.defaultPrevented) {
            event.preventDefault()
            onClose()
        }
    }

    return (
        <section className="detail-pane" aria-labelledby={titleId} onKeyDown={onKeyDown}>
            <header className={`detail-pane-header${tone === 'brand' ? ' detail-pane-header--brand' : ''}`}>
                <div className="detail-pane-heading">
                    <h2 id={titleId} ref={titleRef} tabIndex={-1}>{title}</h2>
                    {subtitle && <p className="detail-pane-meta">{subtitle}</p>}
                    {notice}
                </div>
                <button
                    type="button"
                    className="button button-secondary"
                    onClick={onClose}
                    aria-label={t('common.close')}
                >
                    <FontAwesomeIcon icon={faXmark} fixedWidth />
                </button>
            </header>
            {children}
        </section>
    )
}
