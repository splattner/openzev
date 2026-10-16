import { TextInput } from '@mantine/core'
import { useTranslation } from 'react-i18next'
import { CivilDateInput } from './CivilDateInput'
import { BILLING_INTERVAL_OPTIONS, ZEV_TYPE_OPTIONS } from '../lib/options'
import type { ZevInput } from '../types/api'
import { isValidIban, normalizeIban } from '../lib/iban'
import { GridOperatorField } from '../features/zev/GridOperatorField'
import { GridOperatorSuggestion } from '../features/zev/GridOperatorSuggestion'

type ZevSettingsFieldGroup = 'general' | 'billing' | 'documents'

type ZevGeneralSettingsFieldsProps = {
    form: ZevInput
    onChange: (patch: Partial<ZevInput>) => void
    /** Which hub tab's sections to render (ZEV settings hub, phase 3):
     * general = identity + grid connection, billing = invoicing + payment,
     * documents = contract/tariff notes. */
    group?: ZevSettingsFieldGroup
    /** The ZEV being edited, when there is one — enables the grid-operator
     * suggestion's "test this URL" step, which needs an id to fetch against.
     * Undefined for the create-ZEV form, which has none yet. */
    zevId?: string
    /** Disabled-ZEV owner view: values stay visible but nothing is editable. */
    readOnly?: boolean
    /** Translated inline validation messages by draft field; cleared per field on edit. */
    fieldErrors?: Record<string, string>
}

/**
 * Sections of the ZEV settings form, tagged with the settings-hub tab that
 * renders them (phase 3). Default renders everything (legacy single-form
 * consumers) — the hub passes `group` per tab.
 */
export function ZevGeneralSettingsFields({ form, onChange, group, zevId, readOnly = false, fieldErrors = {} }: ZevGeneralSettingsFieldsProps) {
    const { t } = useTranslation()
    const liveIbanInvalid = (form.bank_iban ?? '').trim() !== '' && !isValidIban(form.bank_iban ?? '')

    function describeInvalid(field: string): { 'aria-invalid': true; 'aria-describedby': string } | Record<string, never> {
        if (!fieldErrors[field]) {
            return {}
        }
        return { 'aria-invalid': true, 'aria-describedby': `zev-settings-field-${field}-error` }
    }

    function inlineError(field: string) {
        if (!fieldErrors[field]) {
            return null
        }
        return (
            <small className="field-error" id={`zev-settings-field-${field}-error`} role="alert">
                {fieldErrors[field]}
            </small>
        )
    }

    return (
        <div className="page-stack zev-general-settings-fields">
            {/* General ZEV Settings (identity) */}
            {(!group || group === 'general') && (
            <div className="form-section">
                <p className="form-section-header">{t('pages.zevSettings.sections.general')}</p>
                <div className="inline-form grid grid-2">
                    <label data-zev-field="name">
                        <span>{t('pages.zevSettings.fields.name')}</span>
                        <input
                            name="name"
                            value={form.name}
                            disabled={readOnly}
                            onChange={(event) => onChange({ name: event.target.value })}
                            required
                            {...describeInvalid('name')}
                        />
                        {inlineError('name')}
                    </label>
                    <label data-zev-field="start_date">
                        <span>{t('pages.zevSettings.fields.startDate')}</span>
                        <CivilDateInput
                            value={form.start_date || null}
                            disabled={readOnly}
                            onChange={(iso) => onChange({ start_date: iso ?? '' })}
                            error={fieldErrors.start_date}
                            errorId="zev-settings-field-start_date-error"
                        />
                    </label>
                    <label data-zev-field="zev_type">
                        <span>{t('pages.zevSettings.fields.zevType')}</span>
                        <select
                            value={form.zev_type}
                            disabled={readOnly}
                            {...describeInvalid('zev_type')}
                            onChange={(event) => onChange({ zev_type: event.target.value as ZevInput['zev_type'] })}
                        >
                            {ZEV_TYPE_OPTIONS.map((option) => (
                                <option key={option.value} value={option.value}>
                                    {t(option.labelKey)}
                                </option>
                            ))}
                        </select>
                        {inlineError('zev_type')}
                    </label>
                </div>
            </div>
            )}
            {/* Billing & payment */}
            {(!group || group === 'billing') && (
            <div className="form-section">
                <p className="form-section-header">{t('pages.zevSettings.sections.billingPayment')}</p>
                <div className="inline-form grid grid-2">
                    <label data-zev-field="billing_interval">
                        <span>{t('pages.zevSettings.fields.billingInterval')}</span>
                        <select
                            value={form.billing_interval}
                            disabled={readOnly}
                            {...describeInvalid('billing_interval')}
                            onChange={(event) =>
                                onChange({ billing_interval: event.target.value as ZevInput['billing_interval'] })
                            }
                        >
                            {BILLING_INTERVAL_OPTIONS.map((option) => (
                                <option key={option.value} value={option.value}>
                                    {t(option.labelKey)}
                                </option>
                            ))}
                        </select>
                        {inlineError('billing_interval')}
                    </label>
                    <label data-zev-field="invoice_language">
                        <span>{t('pages.zevSettings.fields.invoiceLanguage')}</span>
                        <select
                            value={form.invoice_language ?? 'de'}
                            disabled={readOnly}
                            {...describeInvalid('invoice_language')}
                            onChange={(event) =>
                                onChange({ invoice_language: event.target.value as ZevInput['invoice_language'] })
                            }
                        >
                            <option value="de">Deutsch</option>
                            <option value="fr">Français</option>
                            <option value="it">Italiano</option>
                            <option value="en">English</option>
                        </select>
                        {inlineError('invoice_language')}
                    </label>
                    <label data-zev-field="payment_term_days">
                        <span>{t('pages.zevSettings.fields.paymentTermDays')}</span>
                        <input
                            type="number"
                            min={1}
                            max={365}
                            step={1}
                            value={form.payment_term_days ?? ''}
                            disabled={readOnly}
                            onChange={(event) => {
                                const raw = event.target.value
                                onChange({ payment_term_days: raw === '' ? undefined : Number(raw) })
                            }}
                            {...describeInvalid('payment_term_days')}
                        />
                        {inlineError('payment_term_days')}
                    </label>
                    <label data-zev-field="itemize_tariff_bands" className="checkbox-row align-start grid-span-full">
                        <input
                            type="checkbox"
                            checked={form.itemize_tariff_bands ?? false}
                            disabled={readOnly}
                            {...describeInvalid('itemize_tariff_bands')}
                            onChange={(event) => onChange({ itemize_tariff_bands: event.target.checked })}
                        />
                        <span className="checkbox-row-text">
                            <span>{t('pages.zevSettings.fields.itemizeTariffBands')}</span>
                            <small className="muted">{t('pages.zevSettings.fields.itemizeTariffBandsHint')}</small>
                            {inlineError('itemize_tariff_bands')}
                        </span>
                    </label>
                    <label data-zev-field="participant_invoice_access" className="checkbox-row align-start grid-span-full">
                        <input
                            type="checkbox"
                            checked={form.participant_invoice_access ?? false}
                            disabled={readOnly}
                            {...describeInvalid('participant_invoice_access')}
                            onChange={(event) =>
                                onChange({ participant_invoice_access: event.target.checked })
                            }
                        />
                        <span className="checkbox-row-text">
                            <span>{t('pages.zevSettings.fields.participantInvoiceAccess')}</span>
                            <small className="muted">
                                {t('pages.zevSettings.fields.participantInvoiceAccessHint')}
                            </small>
                            {inlineError('participant_invoice_access')}
                        </span>
                    </label>
                </div>
            </div>
            )}

            {/* Grid Connection */}
            {(!group || group === 'general') && (
            <div className="form-section">
                <p className="form-section-header">{t('pages.zevSettings.sections.gridConnection')}</p>
                <div className="inline-form grid grid-2 align-start">
                    <div data-zev-field="postal_code">
                    <TextInput
                        label={t('pages.zevSettings.fields.postalCode')}
                        description={t('pages.zevSettings.fields.postalCodeHint')}
                        value={form.postal_code ?? ''}
                        disabled={readOnly}
                        error={fieldErrors.postal_code}
                        errorProps={{ id: 'zev-settings-field-postal_code-error', className: 'field-error', role: 'alert' }}
                        onChange={(event) => onChange({ postal_code: event.target.value })}
                    />
                    </div>
                    <div data-zev-field="grid_operator">
                    <GridOperatorField
                        label={t('pages.zevSettings.fields.gridOperator')}
                        value={form.grid_operator ?? ''}
                        elcomId={form.grid_operator_elcom_id ?? null}
                        disabled={readOnly}
                        error={[fieldErrors.grid_operator, fieldErrors.grid_operator_elcom_id].filter(Boolean).join(' ') || undefined}
                        errorId="zev-settings-field-grid_operator-error"
                        onChange={onChange}
                    />
                    </div>
                    {(form.postal_code ?? '').trim() && !readOnly && (
                        <div className="grid-span-full">
                            <GridOperatorSuggestion
                                postalCode={form.postal_code ?? ''}
                                currentElcomId={form.grid_operator_elcom_id}
                                currentTariffUrl={form.tariff_source_url}
                                zevId={zevId}
                                onApplyOperator={(operator) =>
                                    onChange({ grid_operator: operator.name, grid_operator_elcom_id: operator.id })
                                }
                                onApplyTariffUrl={(url) => onChange({ tariff_source_url: url })}
                            />
                        </div>
                    )}
                    <div data-zev-field="tariff_source_url" className="grid-span-full">
                    <TextInput
                        className="grid-span-full"
                        label={t('pages.zevSettings.fields.tariffSourceUrl')}
                        description={t('pages.zevSettings.fields.tariffSourceUrlHint')}
                        type="url"
                        value={form.tariff_source_url ?? ''}
                        disabled={readOnly}
                        error={fieldErrors.tariff_source_url}
                        errorProps={{ id: 'zev-settings-field-tariff_source_url-error', className: 'field-error', role: 'alert' }}
                        placeholder={t('pages.zevSettings.fields.tariffSourceUrlPlaceholder')}
                        onChange={(event) => onChange({ tariff_source_url: event.target.value })}
                    />
                    </div>
                    <div data-zev-field="grid_connection_point">
                    <TextInput
                        label={t('pages.zevSettings.fields.gridConnectionPoint')}
                        value={form.grid_connection_point ?? ''}
                        disabled={readOnly}
                        error={fieldErrors.grid_connection_point}
                        errorProps={{ id: 'zev-settings-field-grid_connection_point-error', className: 'field-error', role: 'alert' }}
                        onChange={(event) => onChange({ grid_connection_point: event.target.value })}
                    />
                    </div>
                </div>
            </div>
            )}

            {/* Payment details (billing & payment tab) */}
            {(!group || group === 'billing') && (
            <div className="form-section">
                <p className="form-section-header">{t('pages.zevSettings.sections.paymentDetails')}</p>
                <div className="inline-form grid grid-3">
                    <label data-zev-field="invoice_prefix">
                        <span>{t('pages.zevSettings.fields.invoicePrefix')}</span>
                        <input
                            value={form.invoice_prefix ?? ''}
                            disabled={readOnly}
                            {...describeInvalid('invoice_prefix')}
                            onChange={(event) => onChange({ invoice_prefix: event.target.value })}
                        />
                        {inlineError('invoice_prefix')}
                    </label>
                    <label data-zev-field="credit_note_prefix">
                        <span>{t('pages.zevSettings.fields.creditNotePrefix')}</span>
                        <input
                            value={form.credit_note_prefix ?? ''}
                            disabled={readOnly}
                            {...describeInvalid('credit_note_prefix')}
                            onChange={(event) => onChange({ credit_note_prefix: event.target.value })}
                        />
                        {inlineError('credit_note_prefix')}
                    </label>
                    <div className="grid-span-full payment-recipient-section">
                        <strong>{t('pages.zevSettings.fields.paymentRecipientHeader')}</strong>
                        <p className="muted">{t('pages.zevSettings.fields.paymentRecipientHint')}</p>
                        <div className="payment-fields-grid">
                            <label data-zev-field="bank_name">
                                <span>{t('pages.zevSettings.fields.bankName')}</span>
                                <input
                                    name="bank_name"
                                    value={form.bank_name ?? ''}
                                    disabled={readOnly}
                                    {...describeInvalid('bank_name')}
                                    maxLength={200}
                                    onChange={(event) => onChange({ bank_name: event.target.value })}
                                />
                                {inlineError('bank_name')}
                            </label>
                            <label data-zev-field="bank_iban">
                                <span>{t('pages.zevSettings.fields.bankIban')}</span>
                                <input
                                    name="bank_iban"
                                    value={form.bank_iban ?? ''}
                                    disabled={readOnly}
                                    maxLength={34}
                                    onChange={(event) => onChange({ bank_iban: event.target.value })}
                                    onBlur={(event) => onChange({ bank_iban: normalizeIban(event.target.value) })}
                                    {...describeInvalid('bank_iban')}
                                    aria-invalid={fieldErrors.bank_iban || liveIbanInvalid ? true : undefined}
                                    aria-describedby={fieldErrors.bank_iban || liveIbanInvalid ? 'zev-settings-field-bank_iban-error' : undefined}
                                />
                                {fieldErrors['bank_iban'] ? (
                                    inlineError('bank_iban')
                                ) : liveIbanInvalid && (
                                    <small className="field-error" id="zev-settings-field-bank_iban-error" role="alert">
                                        {t('pages.zevSettings.validation.invalidIban')}
                                    </small>
                                )}
                            </label>
                        </div>
                        <small className="muted">{t('pages.zevSettings.fields.bankIbanHint')}</small>
                    </div>
                    <label data-zev-field="vat_mode" className="grid-span-full">
                        <span>{t('pages.zevSettings.fields.vatMode')}</span>
                        <select
                            value={form.vat_mode ?? 'not_registered'}
                            disabled={readOnly}
                            aria-invalid={fieldErrors.vat_mode || (form.vat_mode !== 'registered' && fieldErrors.vat_number) ? true : undefined}
                            aria-describedby={[
                                fieldErrors.vat_mode && 'zev-settings-field-vat_mode-error',
                                form.vat_mode !== 'registered' && fieldErrors.vat_number && 'zev-settings-field-vat_number-error',
                            ].filter(Boolean).join(' ') || undefined}
                            onChange={(event) => {
                                const vat_mode = event.target.value as ZevInput['vat_mode']
                                onChange(
                                    vat_mode === 'registered'
                                        ? { vat_mode }
                                        : { vat_mode, vat_number: '' },
                                )
                            }}
                        >
                            <option value="not_registered">{t('pages.zevSettings.fields.vatModeNotRegistered')}</option>
                            <option value="registered">{t('pages.zevSettings.fields.vatModeRegistered')}</option>
                            <option value="inclusive">{t('pages.zevSettings.fields.vatModeInclusive')}</option>
                        </select>
                        <small className="muted">{t('pages.zevSettings.fields.vatModeHint')}</small>
                        {inlineError('vat_mode')}
                        {/* A vat_number violation with a hidden number field
                            (mode other than registered) surfaces here so it
                            is always visible next to its fix. */}
                        {form.vat_mode !== 'registered' && inlineError('vat_number')}
                    </label>
                    {form.vat_mode === 'registered' && (
                        <label data-zev-field="vat_number" className="grid-span-full">
                            <span>{t('pages.zevSettings.fields.vatNumber')}</span>
                            <input
                                value={form.vat_number ?? ''}
                                disabled={readOnly}
                                onChange={(event) => onChange({ vat_number: event.target.value })}
                                {...describeInvalid('vat_number')}
                            />
                            {inlineError('vat_number')}
                        </label>
                    )}
                </div>
            </div>

            )}

            {/* Notes (documents tab) */}
            {(!group || group === 'documents') && (
            <>
            <div className="form-section">
                <p className="form-section-header">{t('pages.zevSettings.sections.notes')}</p>
                <label data-zev-field="notes">
                    <textarea
                        value={form.notes ?? ''}
                        disabled={readOnly}
                        {...describeInvalid('notes')}
                        onChange={(event) => onChange({ notes: event.target.value })}
                        rows={4}
                    />
                    {inlineError('notes')}
                </label>
            </div>

            {/* Local tariff notes (contract PDF) */}
            <div className="form-section">
                <p className="form-section-header">{t('pages.zevSettings.sections.localTariffNotes')}</p>
                <label data-zev-field="local_tariff_notes">
                    <textarea
                        value={form.local_tariff_notes ?? ''}
                        disabled={readOnly}
                        {...describeInvalid('local_tariff_notes')}
                        onChange={(event) => onChange({ local_tariff_notes: event.target.value })}
                        rows={4}
                        placeholder={t('pages.zevSettings.fields.localTariffNotesPlaceholder')}
                    />
                    {inlineError('local_tariff_notes')}
                </label>
            </div>

            {/* Additional contract notes (contract PDF) */}
            <div className="form-section">
                <p className="form-section-header">{t('pages.zevSettings.sections.additionalContractNotes')}</p>
                <label data-zev-field="additional_contract_notes">
                    <textarea
                        value={form.additional_contract_notes ?? ''}
                        disabled={readOnly}
                        {...describeInvalid('additional_contract_notes')}
                        onChange={(event) => onChange({ additional_contract_notes: event.target.value })}
                        rows={4}
                        placeholder={t('pages.zevSettings.fields.additionalContractNotesPlaceholder')}
                    />
                    {inlineError('additional_contract_notes')}
                </label>
            </div>
            </>
            )}
        </div>
    )
}
