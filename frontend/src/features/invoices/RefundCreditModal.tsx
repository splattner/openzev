import { FontAwesomeIcon } from '@fortawesome/react-fontawesome'
import { faHandHoldingDollar } from '@fortawesome/free-solid-svg-icons'
import { useState, type FormEvent } from 'react'
import { useTranslation } from 'react-i18next'
import { CivilDateInput } from '../../components/CivilDateInput'
import { FormModal } from '../../components/FormModal'
import { FormModalFooter } from '../../components/FormModalFooter'
import { todayBusinessIso } from '../../lib/dates'
import { formatChf } from '../../lib/numbers'

export type RefundCreditValues = { refunded_on: string; note: string }

type RefundCreditModalProps = {
    isOpen: boolean
    isPending: boolean
    creditNumber: string
    /** What remains of the credit; all of it is booked as paid out. */
    remainingChf: string
    onClose: () => void
    onSubmit: (values: RefundCreditValues) => void
}

/** Books what remains of a credit note as paid out to the participant (#388). */
export function RefundCreditModal({ isOpen, ...rest }: RefundCreditModalProps) {
    const { t } = useTranslation()
    return (
        <FormModal isOpen={isOpen} title={t('pages.invoiceDetail.credits.refundTitle')} onClose={rest.onClose} maxWidth="480px">
            {/* Mounted per opening, so each one starts from today and the current remainder. */}
            {isOpen ? <RefundCreditForm {...rest} /> : null}
        </FormModal>
    )
}

function RefundCreditForm({ isPending, creditNumber, remainingChf, onClose, onSubmit }: Omit<RefundCreditModalProps, 'isOpen'>) {
    const { t } = useTranslation()
    const today = todayBusinessIso()
    const [refundedOn, setRefundedOn] = useState<string | null>(today)
    const [note, setNote] = useState('')

    const handleSubmit = (event: FormEvent) => {
        event.preventDefault()
        if (!refundedOn) return
        onSubmit({ refunded_on: refundedOn, note: note.trim() })
    }

    return (
        <form className="inline-form grid" onSubmit={handleSubmit} noValidate>
            <p className="muted m-0 grid-span-full">
                {t('pages.invoiceDetail.credits.refundHint', { number: creditNumber, amount: formatChf(Number(remainingChf)) })}
            </p>
            <label className="grid-span-full">
                <span>{t('pages.invoiceDetail.credits.refundDate')}</span>
                <CivilDateInput value={refundedOn} onChange={setRefundedOn} maxDate={today} clearable={false} />
            </label>
            <label className="grid-span-full">
                <span>{t('pages.invoiceDetail.credits.refundNote')}</span>
                <input
                    type="text"
                    maxLength={500}
                    value={note}
                    placeholder={t('pages.invoiceDetail.credits.refundNotePlaceholder')}
                    onChange={(event) => setNote(event.target.value)}
                />
            </label>
            <FormModalFooter
                onCancel={onClose}
                isPending={isPending || !refundedOn}
                submitIcon={<FontAwesomeIcon icon={faHandHoldingDollar} fixedWidth />}
                submitLabel={t('pages.invoiceDetail.credits.refundSubmit')}
            />
        </form>
    )
}
