import type { Charge, ChargeInput, Participant } from '../../types/api'

/** The form's own state: strings, as typed, converted to a `ChargeInput` only when valid. */
export type ChargeFormValues = {
    description: string
    amount: string
    chargeDate: string | null
    allocation: Charge['allocation']
    participants: string[]
    splitKey: Charge['split_key']
    vatTreatment: Charge['vat_treatment']
}

export function emptyChargeValues(today: string): ChargeFormValues {
    return {
        description: '',
        amount: '',
        chargeDate: today,
        allocation: 'all_participants',
        participants: [],
        splitKey: 'equal',
        vatTreatment: 'taxable',
    }
}

export function chargeToValues(charge: Charge): ChargeFormValues {
    return {
        description: charge.description,
        amount: charge.amount_chf,
        chargeDate: charge.charge_date,
        allocation: charge.allocation,
        participants: charge.participants,
        splitKey: charge.split_key,
        vatTreatment: charge.vat_treatment,
    }
}

export type ChargeFieldErrors = { description?: true; amount?: true; chargeDate?: true; participants?: true }

export function chargeFieldErrors(values: ChargeFormValues): ChargeFieldErrors {
    const errors: ChargeFieldErrors = {}
    if (!values.description.trim()) errors.description = true
    if (!(Number(values.amount) > 0)) errors.amount = true
    if (!values.chargeDate) errors.chargeDate = true
    if (values.allocation === 'selected_participants' && values.participants.length === 0) errors.participants = true
    return errors
}

/** The payload for the API, or null while the form is incomplete. */
export function chargeInputFrom(values: ChargeFormValues, zevId: string): ChargeInput | null {
    if (Object.keys(chargeFieldErrors(values)).length > 0 || !values.chargeDate) return null
    return {
        zev: zevId,
        description: values.description.trim(),
        amount_chf: Number(values.amount).toFixed(2),
        charge_date: values.chargeDate,
        allocation: values.allocation,
        // Ignored by the backend for a single bearer, but kept stable so the preview key does not churn.
        split_key: values.splitKey,
        vat_treatment: values.vatTreatment,
        participants: values.allocation === 'selected_participants' ? values.participants : [],
    }
}

/** A short label for who bears a charge, for the list. */
export function bearersLabel(
    charge: Pick<Charge, 'allocation' | 'participants'>,
    names: Map<string, string>,
    t: (key: string, options?: Record<string, unknown>) => string,
): string {
    if (charge.allocation === 'all_participants') return t('pages.charges.bearers.all')
    if (charge.participants.length === 1) return names.get(charge.participants[0]) ?? t('pages.charges.bearers.one')
    return t('pages.charges.bearers.selected', { count: charge.participants.length })
}

/** ``day`` pulled into [min, max]; ISO dates compare as strings. */
export function clampDate(day: string, min: string, max: string): string {
    return day < min ? min : day > max ? max : day
}

type Translate = (key: string, options?: Record<string, unknown>) => string

/**
 * How each participation is named where one is picked or listed. A party can
 * hold several participations (a flat and a parking space) under one name, so
 * those carry their meters' locations, as the invoice rows do, and their
 * validity where the locations still do not tell them apart.
 */
export function participantLabels(
    participants: Participant[],
    formatDate: (day: string) => string,
    t: Translate,
): Map<string, string> {
    const nameOf = (participant: Participant) => participant.display_name || participant.full_name || ''
    const partyOf = (participant: Participant) => participant.party ?? participant.id
    const partySize = new Map<string, number>()
    for (const participant of participants) {
        partySize.set(partyOf(participant), (partySize.get(partyOf(participant)) ?? 0) + 1)
    }
    const labelWith = (participant: Participant, withValidity: boolean) => {
        if ((partySize.get(partyOf(participant)) ?? 0) < 2) return nameOf(participant)
        const details = [
            ...new Set((participant.metering_points ?? []).map((point) => point.location_description?.trim() || point.meter_id)),
        ].sort()
        if (withValidity) {
            details.push(
                participant.valid_to
                    ? t('pages.charges.fields.participantValidity', { from: formatDate(participant.valid_from), to: formatDate(participant.valid_to) })
                    : t('pages.charges.fields.participantValiditySince', { from: formatDate(participant.valid_from) }),
            )
        }
        return details.length > 0 ? `${nameOf(participant)} (${details.join(', ')})` : nameOf(participant)
    }
    const plain = new Map(participants.map((participant) => [participant.id, labelWith(participant, false)]))
    const counts = new Map<string, number>()
    for (const label of plain.values()) counts.set(label, (counts.get(label) ?? 0) + 1)
    return new Map(
        participants.map((participant) => [
            participant.id,
            (counts.get(plain.get(participant.id)!) ?? 0) > 1 ? labelWith(participant, true) : plain.get(participant.id)!,
        ]),
    )
}
