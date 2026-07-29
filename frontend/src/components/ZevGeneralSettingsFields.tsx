import dayjs from 'dayjs'
import { DatePicker } from '@mui/x-date-pickers/DatePicker'
import { useTranslation } from 'react-i18next'
import { toDayJsDateFormat, useAppSettings } from '../lib/appSettings'
import type { ZevInput } from '../types/api'

type ZevGeneralSettingsFieldsProps = {
    form: ZevInput
    onChange: (patch: Partial<ZevInput>) => void
}

export function ZevGeneralSettingsFields({ form, onChange }: ZevGeneralSettingsFieldsProps) {
    const { settings } = useAppSettings()
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
                        <DatePicker
                            format={toDayJsDateFormat(settings.date_format_short)}
                            value={form.start_date ? dayjs(form.start_date) : null}
                            onChange={(newValue) =>
                                onChange({ start_date: newValue ? newValue.format('YYYY-MM-DD') : '' })
                            }
                            slotProps={{ textField: { required: true, size: 'small' } }}
                        />
                    </label>
                    <label>
                        <span>{t('pages.zevSettings.fields.zevType')}</span>
                        <select
                            value={form.zev_type}
                            onChange={(event) => onChange({ zev_type: event.target.value as ZevInput['zev_type'] })}
                        >
                            <option value="zev">{t('pages.zevSettings.fields.zevTypeZev')}</option>
                            <option value="vzev">{t('pages.zevSettings.fields.zevTypeVzev')}</option>
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
                            <option value="monthly">{t('pages.zevSettings.fields.billingMonthly')}</option>
                            <option value="quarterly">{t('pages.zevSettings.fields.billingQuarterly')}</option>
                            <option value="semi_annual">{t('pages.zevSettings.fields.billingSemiAnnual')}</option>
                            <option value="annual">{t('pages.zevSettings.fields.billingAnnual')}</option>
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
                </div>
            </div>

            {/* Grid Connection */}
            <div className="form-section">
                <p className="form-section-header">{t('pages.zevSettings.sections.gridConnection')}</p>
                <div className="inline-form grid grid-2">
                    <label>
                        <span>{t('pages.zevSettings.fields.gridOperator')}</span>
                        <input
                            value={form.grid_operator ?? ''}
                            onChange={(event) => onChange({ grid_operator: event.target.value })}
                        />
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
