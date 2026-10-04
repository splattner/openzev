import { todayBusinessIso } from './dates'
import { isValidIban } from './iban'
import type { Zev, ZevInput } from '../types/api'

export type ZevSettingsTab = 'general' | 'people' | 'buildings' | 'billing' | 'documents' | 'audit' | 'export'

export function getDefaultZevForm(): ZevInput {
    return {
        name: '',
        start_date: todayBusinessIso(),
        zev_type: 'vzev',
        postal_code: '',
        grid_operator: '',
        grid_operator_elcom_id: null,
        tariff_source_url: '',
        grid_connection_point: '',
        billing_interval: 'monthly',
        invoice_prefix: '',
        invoice_language: 'de',
        payment_term_days: 30,
        bank_iban: '',
        bank_name: '',
        vat_mode: 'not_registered',
        vat_number: '',
        itemize_tariff_bands: false,
        participant_invoice_access: false,
        notes: '',
        email_subject_template: '',
        email_body_template: '',
        local_tariff_notes: '',
        additional_contract_notes: '',
    }
}

export function mapZevToForm(zev: Zev): ZevInput {
    return {
        name: zev.name,
        start_date: zev.start_date,
        zev_type: zev.zev_type,
        postal_code: zev.postal_code || '',
        grid_operator: zev.grid_operator || '',
        grid_operator_elcom_id: zev.grid_operator_elcom_id ?? null,
        tariff_source_url: zev.tariff_source_url || '',
        grid_connection_point: zev.grid_connection_point || '',
        billing_interval: zev.billing_interval as ZevInput['billing_interval'],
        invoice_prefix: zev.invoice_prefix || '',
        invoice_language: zev.invoice_language ?? 'de',
        payment_term_days: zev.payment_term_days ?? 30,
        bank_iban: zev.bank_iban || '',
        bank_name: zev.bank_name || '',
        vat_mode: zev.vat_mode ?? 'not_registered',
        vat_number: zev.vat_number || '',
        itemize_tariff_bands: zev.itemize_tariff_bands ?? false,
        participant_invoice_access: zev.participant_invoice_access ?? false,
        notes: zev.notes || '',
        email_subject_template: zev.email_subject_template ?? '',
        email_body_template: zev.email_body_template ?? '',
        local_tariff_notes: zev.local_tariff_notes ?? '',
        additional_contract_notes: zev.additional_contract_notes ?? '',
    }
}

/**
 * Field-wise dirty check between draft and saved baseline. All `ZevInput`
 * fields are scalars, so shallow per-key comparison suffices — typing a value
 * back to its saved contents reads as clean again.
 */
export function isZevFormDirty(draft: ZevInput, baseline: ZevInput): boolean {
    for (const key of Object.keys(draft) as (keyof ZevInput)[]) {
        if (draft[key] !== baseline[key]) {
            return true
        }
    }
    return false
}

/** Editable draft fields that can fail validation, in tab order. */
export type ZevFormField = keyof ZevInput

/**
 * Which settings-hub tab renders each draft field. Used to route the user to
 * the first invalid field on save — a Billing save can otherwise fail on a
 * General field with no hint where to look.
 */
export const ZEV_FIELD_TABS: Record<ZevFormField, ZevSettingsTab> = {
    name: 'general',
    start_date: 'general',
    zev_type: 'general',
    postal_code: 'general',
    grid_operator: 'general',
    grid_operator_elcom_id: 'general',
    tariff_source_url: 'general',
    grid_connection_point: 'general',
    billing_interval: 'billing',
    invoice_language: 'billing',
    payment_term_days: 'billing',
    invoice_prefix: 'billing',
    bank_name: 'billing',
    bank_iban: 'billing',
    vat_mode: 'billing',
    vat_number: 'billing',
    itemize_tariff_bands: 'billing',
    participant_invoice_access: 'billing',
    notes: 'documents',
    email_subject_template: 'documents',
    email_body_template: 'documents',
    local_tariff_notes: 'documents',
    additional_contract_notes: 'documents',
}

export interface ZevFormViolation {
    field: ZevFormField
    /** i18n key for the inline message (under `pages.zevSettings.validation`). */
    messageKey: string
}

/**
 * Client-side mirror of the backend write rules (`ZevSerializer` + model
 * validation): required name, IBAN checksum, payment-term range, and VAT
 * number required when registered. Select-bound fields (type, interval,
 * language) cannot hold invalid values, so they are not checked.
 */
export function validateZevForm(form: ZevInput): ZevFormViolation[] {
    const violations: ZevFormViolation[] = []
    if (!form.name.trim()) {
        violations.push({ field: 'name', messageKey: 'requiredName' })
    }
    if (!form.start_date.trim()) {
        violations.push({ field: 'start_date', messageKey: 'requiredStartDate' })
    }
    const term = form.payment_term_days
    if (term === undefined || !Number.isInteger(term) || term < 1 || term > 365) {
        violations.push({ field: 'payment_term_days', messageKey: 'paymentTermRange' })
    }
    if ((form.bank_iban ?? '').trim() !== '' && !isValidIban(form.bank_iban ?? '')) {
        violations.push({ field: 'bank_iban', messageKey: 'invalidIban' })
    }
    if (form.vat_mode === 'registered' && !(form.vat_number ?? '').trim()) {
        violations.push({ field: 'vat_number', messageKey: 'vatNumberRequired' })
    }
    return violations
}

/**
 * Focus a draft field by its `data-zev-field` wrapper — the wrapper may be
 * the control itself (native inputs) or a container (Mantine fields), so
 * prefer an enabled editor over actions such as resetting an email field.
 * Date triggers and Customize buttons are fallbacks when no editor exists.
 */
export function focusZevField(field: string): boolean {
    const wrapper = document.querySelector(`[data-zev-field="${field}"]`)
    if (!(wrapper instanceof HTMLElement)) {
        return false
    }
    const editorSelector = 'input:not([type="hidden"]):not(:disabled), select:not(:disabled), textarea:not(:disabled)'
    const target = wrapper.matches(`${editorSelector}, button:not(:disabled)`)
        ? wrapper
        : wrapper.querySelector<HTMLElement>(editorSelector)
            ?? wrapper.querySelector<HTMLElement>('button:not(:disabled)')
    if (!target) {
        return false
    }
    target.focus()
    // jsdom (unit tests) has no layout; scrolling is a no-op there.
    if (typeof target.scrollIntoView === 'function') {
        target.scrollIntoView({ block: 'center' })
    }
    return true
}

/** First human-readable message of a DRF field-error value. */
function firstErrorMessage(value: unknown): string | null {
    if (typeof value === 'string' && value.trim()) {
        return value
    }
    if (Array.isArray(value)) {
        for (const entry of value) {
            const message = firstErrorMessage(entry)
            if (message) {
                return message
            }
        }
    }
    return null
}

/**
 * Pull known draft-field errors out of a DRF 400 payload
 * (`{field: [messages]}`), in tab order. Unknown keys are ignored — the
 * caller still shows the flattened generic banner.
 */
export function parseZevFieldErrors(payload: Record<string, unknown> | null): { field: ZevFormField; message: string }[] {
    if (!payload) {
        return []
    }
    const found: { field: ZevFormField; message: string }[] = []
    for (const key of Object.keys(ZEV_FIELD_TABS)) {
        const message = firstErrorMessage(payload[key])
        if (message) {
            found.push({ field: key as ZevFormField, message })
        }
    }
    return found
}
