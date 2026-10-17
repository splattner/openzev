import { faPlus, faFloppyDisk } from '@fortawesome/free-solid-svg-icons'
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome'
import { useQuery } from '@tanstack/react-query'
import { useEffect, useMemo, useState, type FormEvent } from 'react'
import { useTranslation } from 'react-i18next'
import { CivilDateInput } from '../../components/CivilDateInput'
import { FormModal } from '../../components/FormModal'
import { FormModalFooter } from '../../components/FormModalFooter'
import { Notice } from '../../components/Notice'
import { previewCharge } from '../../lib/api/charges'
import { formatApiError } from '../../lib/api/errors'
import { queryKeys } from '../../lib/api/queryKeys'
import { formatShortDate, useAppSettings } from '../../lib/appSettings'
import { todayBusinessIso } from '../../lib/dates'
import { formatChf } from '../../lib/numbers'
import type { Charge, Participant } from '../../types/api'
import {
    chargeFieldErrors,
    chargeInputFrom,
    chargeToValues,
    clampDate,
    emptyChargeValues,
    participantLabels,
    type ChargeFormValues,
} from './chargeForm'

type ChargeFormModalProps = {
    isOpen: boolean
    isPending: boolean
    zevId: string
    /** The charge being edited; none creates one. */
    charge: Charge | null
    participants: Participant[]
    /** The period being edited: a charge is dated within it. */
    minDate: string
    maxDate: string
    onClose: () => void
    onSubmit: (values: NonNullable<ReturnType<typeof chargeInputFrom>>) => void
}

/** Records a one-off cost and who bears it (#924), with the split the invoices will show. */
export function ChargeFormModal({ isOpen, ...rest }: ChargeFormModalProps) {
    const { t } = useTranslation()
    return (
        <FormModal
            isOpen={isOpen}
            title={rest.charge ? t('pages.charges.editTitle') : t('pages.charges.createTitle')}
            onClose={rest.onClose}
            maxWidth="640px"
        >
            {/* Mounted per opening, so each one starts from the charge being edited (or a blank one). */}
            {isOpen ? <ChargeForm {...rest} /> : null}
        </FormModal>
    )
}

/** Holds a value back until typing pauses, so the preview is not asked for every keystroke. */
function useSettled<T>(value: T, delayMs = 350): T {
    const [settled, setSettled] = useState(value)
    useEffect(() => {
        const timer = window.setTimeout(() => setSettled(value), delayMs)
        return () => window.clearTimeout(timer)
    }, [value, delayMs])
    return settled
}

function ChargeForm({ isPending, zevId, charge, participants, minDate, maxDate, onClose, onSubmit }: Omit<ChargeFormModalProps, 'isOpen'>) {
    const { t } = useTranslation()
    const { settings } = useAppSettings()
    const [values, setValues] = useState<ChargeFormValues>(
        () => (charge ? chargeToValues(charge) : emptyChargeValues(clampDate(todayBusinessIso(), minDate, maxDate))),
    )
    const [submitted, setSubmitted] = useState(false)
    const patch = (next: Partial<ChargeFormValues>) => setValues((previous) => ({ ...previous, ...next }))

    const errors = chargeFieldErrors(values)
    const dateOutside = !!values.chargeDate && (values.chargeDate < minDate || values.chargeDate > maxDate)
    const input = dateOutside ? null : chargeInputFrom(values, zevId)
    const settledInput = useSettled(input)
    const preview = useQuery({
        queryKey: queryKeys.charges.preview(settledInput),
        queryFn: () => previewCharge(settledInput!),
        enabled: settledInput !== null,
        retry: false,
    })
    const showErrors = submitted
    const labels = useMemo(
        () => participantLabels(participants, (day) => formatShortDate(day, settings), t),
        [participants, settings, t],
    )

    const handleSubmit = (event: FormEvent) => {
        event.preventDefault()
        setSubmitted(true)
        if (input) onSubmit(input)
    }

    const toggleParticipant = (id: string) =>
        patch({
            participants: values.participants.includes(id)
                ? values.participants.filter((existing) => existing !== id)
                : [...values.participants, id],
        })

    const bearerCount = preview.data?.bearers.length ?? 0
    const unrecovered = Number(preview.data?.unrecovered_chf ?? 0)

    return (
        <form className="inline-form grid" onSubmit={handleSubmit} noValidate>
            <label className="grid-span-full">
                <span>{t('pages.charges.fields.description')}</span>
                <input
                    type="text"
                    maxLength={200}
                    value={values.description}
                    placeholder={t('pages.charges.fields.descriptionPlaceholder')}
                    onChange={(event) => patch({ description: event.target.value })}
                    aria-invalid={showErrors && errors.description ? true : undefined}
                    required
                />
                {showErrors && errors.description ? <small className="text-error">{t('pages.charges.errors.description')}</small> : null}
            </label>
            <label>
                <span>{t('pages.charges.fields.amount')}</span>
                <input
                    type="number"
                    inputMode="decimal"
                    step="0.01"
                    min="0.01"
                    value={values.amount}
                    onChange={(event) => patch({ amount: event.target.value })}
                    aria-invalid={showErrors && errors.amount ? true : undefined}
                    required
                />
                {showErrors && errors.amount ? <small className="text-error">{t('pages.charges.errors.amount')}</small> : null}
            </label>
            <label>
                <span>{t('pages.charges.fields.chargeDate')}</span>
                <CivilDateInput
                    value={values.chargeDate}
                    onChange={(chargeDate) => patch({ chargeDate })}
                    minDate={minDate}
                    maxDate={maxDate}
                    clearable={false}
                />
                {showErrors && dateOutside ? (
                    <small className="text-error">{t('pages.charges.errors.dateOutside')}</small>
                ) : null}
                <small className="muted">
                    {t('pages.charges.fields.chargeDateHint', {
                        from: formatShortDate(minDate, settings),
                        to: formatShortDate(maxDate, settings),
                    })}
                </small>
            </label>

            <label className="grid-span-full">
                <span>{t('pages.charges.fields.allocation')}</span>
                <select
                    value={values.allocation}
                    onChange={(event) => patch({ allocation: event.target.value as ChargeFormValues['allocation'] })}
                >
                    <option value="all_participants">{t('pages.charges.allocation.all_participants')}</option>
                    <option value="selected_participants">{t('pages.charges.allocation.selected_participants')}</option>
                </select>
            </label>

            {values.allocation === 'selected_participants' ? (
                <fieldset className="grid-span-full">
                    <legend>{t('pages.charges.fields.participants')}</legend>
                    {participants.map((participant) => (
                        <label key={participant.id} className="checkbox-row">
                            <input
                                type="checkbox"
                                checked={values.participants.includes(participant.id)}
                                onChange={() => toggleParticipant(participant.id)}
                            />
                            <span>{labels.get(participant.id)}</span>
                        </label>
                    ))}
                    {showErrors && errors.participants ? <small className="text-error">{t('pages.charges.errors.participants')}</small> : null}
                </fieldset>
            ) : null}

            {/* One bearer pays the whole amount whichever key is set, so there is nothing to choose. */}
            {values.allocation === 'all_participants' || values.participants.length !== 1 ? (
                <label>
                    <span>{t('pages.charges.fields.splitKey')}</span>
                    <select
                        value={values.splitKey}
                        onChange={(event) => patch({ splitKey: event.target.value as ChargeFormValues['splitKey'] })}
                    >
                        <option value="equal">{t('pages.charges.splitKey.equal')}</option>
                        <option value="weight">{t('pages.charges.splitKey.weight')}</option>
                    </select>
                </label>
            ) : null}
            <label>
                <span>{t('pages.charges.fields.vatTreatment')}</span>
                <select
                    value={values.vatTreatment}
                    onChange={(event) => patch({ vatTreatment: event.target.value as ChargeFormValues['vatTreatment'] })}
                >
                    <option value="taxable">{t('pages.charges.vatTreatment.taxable')}</option>
                    <option value="pass_through">{t('pages.charges.vatTreatment.pass_through')}</option>
                </select>
            </label>
            <p className="muted m-0 grid-span-full">{t(`pages.charges.vatHint.${values.vatTreatment}`)}</p>

            <section className="grid-span-full" aria-live="polite" aria-label={t('pages.charges.preview.title')}>
                <h3 className="m-0">{t('pages.charges.preview.title')}</h3>
                {!settledInput ? (
                    <p className="muted">{t('pages.charges.preview.incomplete')}</p>
                ) : preview.isError ? (
                    <Notice tone="error">{formatApiError(preview.error, t('pages.charges.preview.failed'))}</Notice>
                ) : preview.data ? (
                    bearerCount === 0 ? (
                        <Notice tone="warning">{t('pages.charges.preview.nobody')}</Notice>
                    ) : (
                        <>
                            <div className="table-scroll">
                                <table className="data-table">
                                    <thead>
                                        <tr>
                                            <th>{t('pages.charges.preview.participant')}</th>
                                            <th className="numeric">{t('pages.charges.preview.share')}</th>
                                        </tr>
                                    </thead>
                                    <tbody>
                                        {preview.data.bearers.map((bearer) => (
                                            <tr key={bearer.participant}>
                                                <td>{labels.get(bearer.participant) ?? bearer.name}</td>
                                                <td className="numeric">{formatChf(Number(bearer.share_chf))}</td>
                                            </tr>
                                        ))}
                                    </tbody>
                                </table>
                            </div>
                            {unrecovered !== 0 ? (
                                <p className="muted">
                                    {unrecovered > 0
                                        ? t('pages.charges.preview.unrecovered', { amount: formatChf(unrecovered) })
                                        : t('pages.charges.preview.overbilled', { amount: formatChf(-unrecovered) })}
                                </p>
                            ) : null}
                        </>
                    )
                ) : (
                    <p className="muted">{t('common.loading')}</p>
                )}
            </section>

            <FormModalFooter
                onCancel={onClose}
                isPending={isPending}
                submitIcon={<FontAwesomeIcon icon={charge ? faFloppyDisk : faPlus} fixedWidth />}
                submitLabel={charge ? t('common.save') : t('pages.charges.create')}
            />
        </form>
    )
}
