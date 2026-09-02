import { CivilDateInput } from './CivilDateInput'
import { useTranslation } from 'react-i18next'
import { BILLING_INTERVAL_OPTIONS, ZEV_TYPE_OPTIONS } from '../lib/options'
import type { ZevInput } from '../types/api'
import { GridOperatorField } from '../features/zev/GridOperatorField'

type ZevGeneralSettingsFieldsProps = {
    form: ZevInput
    onChange: (patch: Partial<ZevInput>) => void
}

export function ZevGeneralSettingsFields({ form, onChange }: ZevGeneralSettingsFieldsProps) {
    const { t } = useTranslation()

    return (
        <div className="page-stack">
            {/* General ZEV Settings */}
            <div className="form-section">
                <p className="form-section-header">{t('pages.zevSettings.sections.general')}</p>
                <div className="inline-form grid grid-2">
                    <label>
                        <span>{t('pages.zevSettings.fields.name')}</span>
                        <input
                            name="name"
                            value={form.name}
                            onChange={(event) => onChange({ name: event.target.value })}
                            required
                        />
                    </label>
                    <label>
                        <span>{t('pages.zevSettings.fields.startDate')}</span>
                        <CivilDateInput
                            value={form.start_date || null}
                            onChange={(iso) => onChange({ start_date: iso ?? '' })}
                        />
                    </label>
                    <label>
                        <span>{t('pages.zevSettings.fields.zevType')}</span>
                        <select
                            value={form.zev_type}
                            onChange={(event) => onChange({ zev_type: event.target.value as ZevInput['zev_type'] })}
                        >
                            {ZEV_TYPE_OPTIONS.map((option) => (
                                <option key={option.value} value={option.value}>
                                    {t(option.labelKey)}
                                </option>
                            ))}
                        </select>
                    </label>
                    <label>
                        <span>{t('pages.zevSettings.fields.billingInterval')}</span>
                        <select
                            value={form.billing_interval}
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
                    </label>
                    <label>
                        <span>{t('pages.zevSettings.fields.invoiceLanguage')}</span>
                        <select
                            value={form.invoice_language ?? 'de'}
                            onChange={(event) =>
                                onChange({ invoice_language: event.target.value as ZevInput['invoice_language'] })
                            }
                        >
                            <option value="de">Deutsch</option>
                            <option value="fr">Français</option>
                            <option value="it">Italiano</option>
                            <option value="en">English</option>
                        </select>
                    </label>
                    <label>
                        <span>{t('pages.zevSettings.fields.paymentTermDays')}</span>
                        <input
                            type="number"
                            min={1}
                            max={365}
                            step={1}
                            value={form.payment_term_days ?? 30}
                            onChange={(event) => {
                                const raw = event.target.value
                                onChange({ payment_term_days: raw === '' ? undefined : Number(raw) })
                            }}
                        />
                    </label>
                </div>
            </div>

            {/* Grid Connection */}
            <div className="form-section">
                <p className="form-section-header">{t('pages.zevSettings.sections.gridConnection')}</p>
                <div className="inline-form grid grid-2">
                    <GridOperatorField
                        label={t('pages.zevSettings.fields.gridOperator')}
                        value={form.grid_operator ?? ''}
                        elcomId={form.grid_operator_elcom_id ?? null}
                        onChange={onChange}
                    />
                    <label className="grid-span-full">
                        <span>{t('pages.zevSettings.fields.tariffSourceUrl')}</span>
                        <input
                            type="url"
                            value={form.tariff_source_url ?? ''}
                            placeholder="https://…/tarife.json"
                            onChange={(event) => onChange({ tariff_source_url: event.target.value })}
                        />
                        <small className="muted">{t('pages.zevSettings.fields.tariffSourceUrlHint')}</small>
                    </label>
                    <label>
                        <span>{t('pages.zevSettings.fields.gridConnectionPoint')}</span>
                        <input
                            value={form.grid_connection_point ?? ''}
                            onChange={(event) => onChange({ grid_connection_point: event.target.value })}
                        />
                    </label>
                </div>
            </div>

            {/* Payment Details */}
            <div className="form-section">
                <p className="form-section-header">{t('pages.zevSettings.sections.paymentDetails')}</p>
                <div className="inline-form grid grid-3">
                    <label>
                        <span>{t('pages.zevSettings.fields.invoicePrefix')}</span>
                        <input
                            value={form.invoice_prefix ?? ''}
                            onChange={(event) => onChange({ invoice_prefix: event.target.value })}
                        />
                    </label>
                    <label>
                        <span>{t('pages.zevSettings.fields.vatNumber')}</span>
                        <input
                            value={form.vat_number ?? ''}
                            onChange={(event) => onChange({ vat_number: event.target.value })}
                        />
                    </label>
                    <label>
                        <span>{t('pages.zevSettings.fields.bankName')}</span>
                        <input
                            name="bank_name"
                            value={form.bank_name ?? ''}
                            onChange={(event) => onChange({ bank_name: event.target.value })}
                        />
                    </label>
                    <label className="grid-span-full">
                        <span>{t('pages.zevSettings.fields.bankIban')}</span>
                        <input
                            name="bank_iban"
                            value={form.bank_iban ?? ''}
                            onChange={(event) => onChange({ bank_iban: event.target.value })}
                        />
                    </label>
                </div>
            </div>

            {/* Notes */}
            <div className="form-section">
                <p className="form-section-header">{t('pages.zevSettings.sections.notes')}</p>
                <label>
                    <textarea
                        value={form.notes ?? ''}
                        onChange={(event) => onChange({ notes: event.target.value })}
                        rows={4}
                    />
                </label>
            </div>

            {/* Local tariff notes (contract PDF) */}
            <div className="form-section">
                <p className="form-section-header">{t('pages.zevSettings.sections.localTariffNotes')}</p>
                <label>
                    <textarea
                        value={form.local_tariff_notes ?? ''}
                        onChange={(event) => onChange({ local_tariff_notes: event.target.value })}
                        rows={4}
                        placeholder={t('pages.zevSettings.fields.localTariffNotesPlaceholder')}
                    />
                </label>
            </div>

            {/* Additional contract notes (contract PDF) */}
            <div className="form-section">
                <p className="form-section-header">{t('pages.zevSettings.sections.additionalContractNotes')}</p>
                <label>
                    <textarea
                        value={form.additional_contract_notes ?? ''}
                        onChange={(event) => onChange({ additional_contract_notes: event.target.value })}
                        rows={4}
                        placeholder={t('pages.zevSettings.fields.additionalContractNotesPlaceholder')}
                    />
                </label>
            </div>
        </div>
    )
}
