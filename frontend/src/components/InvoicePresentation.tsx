import type { ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome'
import { faEllipsis, faFilePdf, faSpinner } from '@fortawesome/free-solid-svg-icons'
import { ActionMenu, type ActionMenuItem } from './ActionMenu'
import { openInvoicePdf } from '../lib/api/invoices'
import { formatChf, formatChfAmount } from '../lib/numbers'
import type { Invoice } from '../types/api'
import { amountDueChf, hasCreditApplied } from '../features/invoices/invoiceCredits'
import { invoiceStatusBadgeClass, isPartlyPaid } from '../features/invoices/invoiceStatus'

export function InvoiceLink({ invoice, from, period, children, className }: {
    invoice: Pick<Invoice, 'id' | 'invoice_number'>
    from: string
    period?: { period_start: string; period_end: string }
    children?: ReactNode
    className?: string
}) {
    return (
        <Link
            to={`/billing/invoices/${invoice.id}`}
            state={{ from, ...period }}
            className={className}
        >
            {children ?? invoice.invoice_number}
        </Link>
    )
}

/** Pass `paidChf` where it is known, so a partly paid invoice says so. */
export function InvoiceStatusBadge({ status, paidChf }: { status: Invoice['status']; paidChf?: Invoice['paid_chf'] }) {
    const { t } = useTranslation()
    const label = isPartlyPaid({ status, paid_chf: paidChf }) ? t('invoice.status.partlyPaid')
        : status ? t(`invoice.status.${status}`) : ''
    return <span className={invoiceStatusBadgeClass(status)}>{label}</span>
}

/** `currency={false}` drops "CHF" where the column header already names it. */
export function InvoiceAmount({ value, currency = true }: { value: Invoice['total_chf'] | null; currency?: boolean }) {
    if (value === null) return <span className="muted">-</span>
    return <>{currency ? formatChf(Number(value)) : formatChfAmount(Number(value))}</>
}

/**
 * The invoice total and, where credit notes were set against it, the amount
 * due beneath it (#388).
 */
export function InvoiceTotal({ invoice, currency = true }: {
    invoice: Pick<Invoice, 'status' | 'total_chf' | 'credit_applied_chf' | 'amount_due_chf'>
    currency?: boolean
}) {
    const { t } = useTranslation()
    const due = amountDueChf(invoice)
    return (
        <>
            <InvoiceAmount value={invoice.total_chf} currency={currency} />
            {hasCreditApplied(invoice) && (
                <small className="muted invoice-amount-due" style={{ display: 'block' }}>
                    {t('invoice.amountDue')}: {currency ? formatChf(due) : formatChfAmount(due)}
                </small>
            )}
        </>
    )
}

/** Presentation only: callers decide whether PDF access is allowed and pass local pending state. */
export function InvoicePdfCell({ invoice, pending = false, showReadyStatus = true, keepExistingDuringPending = false, buttonClassName = 'table-inline-link', ariaLabel }: {
    invoice: Invoice | null
    pending?: boolean
    showReadyStatus?: boolean
    keepExistingDuringPending?: boolean
    buttonClassName?: string
    ariaLabel?: string
}) {
    const { t } = useTranslation()
    if (!invoice) return <span className="muted">-</span>
    const regenerating = pending || invoice.pdf_status === 'pending'
    if (regenerating && (!keepExistingDuringPending || !invoice.pdf_url)) {
        return (
            <span className="badge badge-info" role="status">
                <FontAwesomeIcon icon={faSpinner} spin fixedWidth aria-hidden="true" />
                {t('pages.invoices.pdfGenerating')}
            </span>
        )
    }
    if (invoice.pdf_status === 'failed' && !invoice.pdf_url) {
        return (
            <span className="badge badge-danger" title={t('pages.invoices.pdfFailedHint')}>
                {t('pages.invoices.pdfFailed')}
            </span>
        )
    }
    if (!invoice.pdf_url) return <span className="badge badge-neutral">{t('pages.invoices.pdfMissing')}</span>
    return (
        <div className="invoice-cell-stack">
            <button type="button" onClick={() => void openInvoicePdf(invoice.id)} className={buttonClassName} aria-label={ariaLabel}>
                <FontAwesomeIcon icon={faFilePdf} fixedWidth aria-hidden="true" />
                {t('common.openPdf')}
            </button>
            {showReadyStatus && <span className="badge badge-success">{t('pages.invoices.pdfReady')}</span>}
        </div>
    )
}

/** Minimal action a standalone button renders: no menu key or section. */
export type InvoiceButtonAction = Pick<ActionMenuItem, 'label' | 'icon' | 'onClick' | 'disabled' | 'danger'>

/** `secondary` outlines the button where a page-level primary action leads. */
export type InvoiceButtonVariant = 'primary' | 'secondary'

export function InvoiceActionButton({ action, compact = true, variant = 'primary' }: {
    action: InvoiceButtonAction
    compact?: boolean
    variant?: InvoiceButtonVariant
}) {
    return (
        <button
            className={`button button-${action.danger ? 'danger' : variant}${compact ? ' button-compact' : ''}`}
            type="button"
            disabled={action.disabled}
            onClick={action.onClick}
        >
            {action.icon}
            {action.label}
        </button>
    )
}

/** Eligibility and read-only restrictions remain with the caller. */
export function InvoiceRowActions({ primary, menuItems = [], children, variant, iconOnlyMenu = false }: {
    primary?: InvoiceButtonAction | null
    menuItems?: ActionMenuItem[]
    children?: ReactNode
    variant?: InvoiceButtonVariant
    iconOnlyMenu?: boolean
}) {
    const { t } = useTranslation()
    return (
        <div className="invoice-row-actions">
            {primary && <InvoiceActionButton action={primary} variant={variant} />}
            {children}
            {menuItems.length > 0 && (
                <ActionMenu
                    label={t('pages.invoices.moreActions')}
                    iconOnly={iconOnlyMenu}
                    icon={<FontAwesomeIcon icon={faEllipsis} fixedWidth />}
                    items={menuItems}
                />
            )}
        </div>
    )
}
