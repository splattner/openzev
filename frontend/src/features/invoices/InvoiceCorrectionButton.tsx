import { useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome'
import { faReceipt } from '@fortawesome/free-solid-svg-icons'
import { correctInvoice } from '../../lib/api/invoices'
import { formatApiError } from '../../lib/api/errors'
import { useToast } from '../../lib/toast'
import type { Invoice } from '../../types/api'
import { CorrectInvoiceModal, type CorrectInvoiceValues } from './CorrectInvoiceModal'
import { appliedCreditChf, canAdjustInvoice, canCorrectInvoice, creditableChf } from './invoiceCredits'

export function InvoiceCorrectionButton({ invoice, canManage, onChanged }: {
    invoice: Invoice
    canManage: boolean
    onChanged: (invoice: Invoice) => void
}) {
    const { t } = useTranslation()
    const { pushToast } = useToast()
    const [open, setOpen] = useState(false)
    const mutation = useMutation({
        mutationFn: (values: CorrectInvoiceValues) => correctInvoice(invoice.id, values),
        onSuccess: ({ invoice: updated }) => {
            setOpen(false)
            pushToast(t('pages.invoiceDetail.credits.corrected'), 'success')
            onChanged(updated)
        },
        onError: (error) => pushToast(formatApiError(error, t('pages.invoiceDetail.credits.correctFailed')), 'error'),
    })
    if (!canCorrectInvoice(invoice, canManage)) return null
    return (
        <>
            <button type="button" className={invoice.needs_data_review ? 'button button-primary' : 'button button-secondary'} onClick={() => setOpen(true)}>
                <FontAwesomeIcon icon={faReceipt} fixedWidth aria-hidden="true" />
                {t('pages.invoiceDetail.credits.correct')}
            </button>
            <CorrectInvoiceModal
                isOpen={open}
                isPending={mutation.isPending}
                creditableChf={creditableChf(invoice).toFixed(2)}
                creditAppliedChf={appliedCreditChf(invoice).toFixed(2)}
                canAdjust={canAdjustInvoice(invoice, canManage)}
                onClose={() => setOpen(false)}
                onSubmit={(values) => mutation.mutate(values)}
            />
        </>
    )
}
