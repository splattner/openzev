import { FontAwesomeIcon } from '@fortawesome/react-fontawesome'
import { faMoneyBillWave } from '@fortawesome/free-solid-svg-icons'
import { useState, type FormEvent } from 'react'
import { useTranslation } from 'react-i18next'
import { CivilDateInput } from '../../components/CivilDateInput'
import { FormModal } from '../../components/FormModal'
import { FormModalFooter } from '../../components/FormModalFooter'
import { todayBusinessIso } from '../../lib/dates'
import { formatChf } from '../../lib/numbers'

export type RecordPaymentValues = { amount_chf: string; paid_on: string; note: string }

type RecordPaymentModalProps = {
    isOpen: boolean
    isPending: boolean
    /** What is still owed; the amount defaults to it and may not exceed it. */
    outstandingChf: string
    /** Invoice label for list context. */
    invoiceNumber?: string
    onClose: () => void
    onSubmit: (values: RecordPaymentValues) => void
}

/** Books money received against a sent invoice, in full or in part (#388). */
export function RecordPaymentModal({ isOpen, ...rest }: RecordPaymentModalProps) {
    const { t } = useTranslation()
    return (
        <FormModal isOpen={isOpen} title={t('pages.invoiceDetail.payments.recordTitle')} onClose={rest.onClose} size="xs">
            {/* Mounted per opening, so each one starts from the current outstanding amount. */}
            {isOpen ? <RecordPaymentForm {...rest} /> : null}
        </FormModal>
    )
}

function RecordPaymentForm({ isPending, outstandingChf, invoiceNumber, onClose, onSubmit }: Omit<RecordPaymentModalProps, 'isOpen'>) {
    const { t } = useTranslation()
    const today = todayBusinessIso()
    const [amount, setAmount] = useState(outstandingChf)
    const [paidOn, setPaidOn] = useState<string | null>(today)
    const [note, setNote] = useState('')

    const value = Number(amount)
    const amountError = !(value > 0)
        ? t('pages.invoiceDetail.payments.amountPositive')
        : value > Number(outstandingChf)
            ? t('pages.invoiceDetail.payments.amountTooHigh', { amount: formatChf(Number(outstandingChf)) })
            : null

    const handleSubmit = (event: FormEvent) => {
        event.preventDefault()
        if (isPending || amountError || !paidOn) return
        onSubmit({ amount_chf: value.toFixed(2), paid_on: paidOn, note: note.trim() })
    }

    return (
        <form className="inline-form grid" onSubmit={handleSubmit} noValidate>
            {invoiceNumber ? (
                <p className="muted m-0 grid-span-full">
                    {t('pages.invoiceDetail.payments.invoiceContext', { number: invoiceNumber })}
                </p>
            ) : null}
            <p className="muted m-0 grid-span-full">
                {t('pages.invoiceDetail.payments.outstandingHint', { amount: formatChf(Number(outstandingChf)) })}
            </p>
            <label>
                <span>{t('pages.invoiceDetail.payments.amount')}</span>
                <input
                    type="number"
                    inputMode="decimal"
                    step="0.01"
                    min="0.01"
                    max={outstandingChf}
                    value={amount}
                    onChange={(event) => setAmount(event.target.value)}
                    aria-invalid={amountError ? true : undefined}
                    aria-describedby={amountError ? 'record-payment-amount-error' : undefined}
                    required
                />
                {amountError ? <small id="record-payment-amount-error" className="text-error">{amountError}</small> : null}
            </label>
            <label>
                <span>{t('pages.invoiceDetail.payments.paidOn')}</span>
                <CivilDateInput value={paidOn} onChange={setPaidOn} maxDate={today} clearable={false} />
            </label>
            <label className="grid-span-full">
                <span>{t('pages.invoiceDetail.payments.note')}</span>
                <input
                    type="text"
                    maxLength={500}
                    value={note}
                    placeholder={t('pages.invoiceDetail.payments.notePlaceholder')}
                    onChange={(event) => setNote(event.target.value)}
                />
            </label>
            <FormModalFooter
                onCancel={onClose}
                isPending={isPending}
                disabled={!!amountError || !paidOn}
                submitIcon={<FontAwesomeIcon icon={faMoneyBillWave} fixedWidth />}
                submitLabel={t('pages.invoiceDetail.payments.record')}
            />
        </form>
    )
}
