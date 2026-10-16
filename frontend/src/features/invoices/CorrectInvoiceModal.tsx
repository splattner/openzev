import { FontAwesomeIcon } from '@fortawesome/react-fontawesome'
import { faReceipt } from '@fortawesome/free-solid-svg-icons'
import { useState, type FormEvent } from 'react'
import { useTranslation } from 'react-i18next'
import { FormModal } from '../../components/FormModal'
import { FormModalFooter } from '../../components/FormModalFooter'
import { formatChf } from '../../lib/numbers'
import type { CreditKind } from '../../types/api'

export type CorrectInvoiceValues = { kind: CreditKind; reason: string; amount_chf?: string }

type CorrectInvoiceModalProps = {
    isOpen: boolean
    isPending: boolean
    /** What was received in cash for the invoice and not yet credited; a partial credit may not exceed it. */
    creditableChf: string
    /** Credit applied to the invoice that a reversal releases again (CHF); `0.00` when none. */
    creditAppliedChf: string
    /** A partial credit needs cash to credit; an invoice settled by credit alone can only be reversed. */
    canAdjust: boolean
    onClose: () => void
    onSubmit: (values: CorrectInvoiceValues) => void
}

/** Corrects a paid invoice with a credit note: a full reversal or a partial credit (#388). */
export function CorrectInvoiceModal({ isOpen, ...rest }: CorrectInvoiceModalProps) {
    const { t } = useTranslation()
    return (
        <FormModal isOpen={isOpen} title={t('pages.invoiceDetail.credits.correctTitle')} onClose={rest.onClose} maxWidth="520px">
            {/* Mounted per opening, so each one starts from the current creditable amount. */}
            {isOpen ? <CorrectInvoiceForm {...rest} /> : null}
        </FormModal>
    )
}

function CorrectInvoiceForm({ isPending, creditableChf, creditAppliedChf, canAdjust, onClose, onSubmit }: Omit<CorrectInvoiceModalProps, 'isOpen'>) {
    const { t } = useTranslation()
    const [kind, setKind] = useState<CreditKind>('reversal')
    const [reason, setReason] = useState('')
    const [amount, setAmount] = useState('')

    const cashCreditable = Number(creditableChf) > 0
    const creditApplied = Number(creditAppliedChf) > 0
    const value = Number(amount)
    const amountError = kind !== 'adjustment'
        ? null
        : !(value > 0)
            ? t('pages.invoiceDetail.credits.amountPositive')
            : value > Number(creditableChf)
                ? t('pages.invoiceDetail.credits.amountTooHigh', { amount: formatChf(Number(creditableChf)) })
                : null
    const reasonMissing = reason.trim() === ''

    const handleSubmit = (event: FormEvent) => {
        event.preventDefault()
        if (amountError || reasonMissing) return
        onSubmit({
            kind,
            reason: reason.trim(),
            ...(kind === 'adjustment' ? { amount_chf: value.toFixed(2) } : {}),
        })
    }

    return (
        <form className="inline-form grid" onSubmit={handleSubmit} noValidate>
            <fieldset className="grid-span-full">
                <legend>{t('pages.invoiceDetail.credits.kindLabel')}</legend>
                {(['reversal', 'adjustment'] as const).map((option) => (
                    <label key={option} style={{ display: 'flex', gap: '0.6rem', alignItems: 'flex-start' }}>
                        <input
                            type="radio"
                            name="correction-kind"
                            value={option}
                            checked={kind === option}
                            disabled={option === 'adjustment' && !canAdjust}
                            onChange={() => setKind(option)}
                        />
                        <span>
                            <strong>{t(`pages.invoiceDetail.credits.${option}`)}</strong>
                            <small className="muted" style={{ display: 'block' }}>
                                {option === 'reversal'
                                    ? cashCreditable
                                        ? t('pages.invoiceDetail.credits.reversalHint', { amount: formatChf(Number(creditableChf)) })
                                        : t('pages.invoiceDetail.credits.reversalNoCashHint')
                                    : canAdjust
                                        ? t('pages.invoiceDetail.credits.adjustmentHint')
                                        : t('pages.invoiceDetail.credits.adjustmentNoCashHint')}
                            </small>
                        </span>
                    </label>
                ))}
                {creditApplied ? (
                    <p className="muted m-0">
                        {t('pages.invoiceDetail.credits.releasesCredit', { amount: formatChf(Number(creditAppliedChf)) })}
                    </p>
                ) : null}
            </fieldset>
            {kind === 'adjustment' ? (
                <label className="grid-span-full">
                    <span>{t('pages.invoiceDetail.credits.amount')}</span>
                    <input
                        type="number"
                        inputMode="decimal"
                        step="0.01"
                        min="0.01"
                        max={creditableChf}
                        value={amount}
                        onChange={(event) => setAmount(event.target.value)}
                        aria-invalid={amountError ? true : undefined}
                        aria-describedby="correct-invoice-amount-hint"
                        required
                    />
                    <small id="correct-invoice-amount-hint" className={amountError && amount !== '' ? 'text-error' : 'muted'}>
                        {amountError && amount !== ''
                            ? amountError
                            : t('pages.invoiceDetail.credits.creditableHint', { amount: formatChf(Number(creditableChf)) })}
                    </small>
                </label>
            ) : null}
            <label className="grid-span-full">
                <span>{t('pages.invoiceDetail.credits.reason')}</span>
                <textarea
                    rows={3}
                    maxLength={2000}
                    value={reason}
                    placeholder={t('pages.invoiceDetail.credits.reasonPlaceholder')}
                    onChange={(event) => setReason(event.target.value)}
                    aria-invalid={reasonMissing && reason !== '' ? true : undefined}
                    required
                />
            </label>
            <FormModalFooter
                onCancel={onClose}
                isPending={isPending || !!amountError || reasonMissing}
                submitIcon={<FontAwesomeIcon icon={faReceipt} fixedWidth />}
                submitLabel={t('pages.invoiceDetail.credits.submit')}
            />
        </form>
    )
}
