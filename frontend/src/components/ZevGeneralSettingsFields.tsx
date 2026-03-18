import type { ZevInput } from '../types/api'

type ZevGeneralSettingsFieldsProps = {
    form: ZevInput
    onChange: (patch: Partial<ZevInput>) => void
}

export function ZevGeneralSettingsFields({ form, onChange }: ZevGeneralSettingsFieldsProps) {
    return (
        <div className="inline-form grid grid-3">
            <label>
                <span>Name</span>
                <input
                    value={form.name}
                    onChange={(event) => onChange({ name: event.target.value })}
                    required
                />
            </label>
            <label>
                <span>Start date</span>
                <input
                    type="date"
                    value={form.start_date}
                    onChange={(event) => onChange({ start_date: event.target.value })}
                    required
                />
            </label>
            <label>
                <span>ZEV type</span>
                <select
                    value={form.zev_type}
                    onChange={(event) => onChange({ zev_type: event.target.value as ZevInput['zev_type'] })}
                >
                    <option value="zev">ZEV</option>
                    <option value="vzev">vZEV</option>
                </select>
            </label>

            <label>
                <span>Grid operator</span>
                <input
                    value={form.grid_operator ?? ''}
                    onChange={(event) => onChange({ grid_operator: event.target.value })}
                />
            </label>
            <label>
                <span>Grid connection point</span>
                <input
                    value={form.grid_connection_point ?? ''}
                    onChange={(event) => onChange({ grid_connection_point: event.target.value })}
                />
            </label>
            <label>
                <span>Billing interval</span>
                <select
                    value={form.billing_interval}
                    onChange={(event) =>
                        onChange({ billing_interval: event.target.value as ZevInput['billing_interval'] })
                    }
                >
                    <option value="monthly">Monthly</option>
                    <option value="quarterly">Quarterly</option>
                    <option value="semi_annual">Semi-annual</option>
                    <option value="annual">Annual</option>
                </select>
            </label>

            <label>
                <span>Address line 1</span>
                <input
                    value={form.address_line1 ?? ''}
                    onChange={(event) => onChange({ address_line1: event.target.value })}
                />
            </label>
            <label>
                <span>Address line 2</span>
                <input
                    value={form.address_line2 ?? ''}
                    onChange={(event) => onChange({ address_line2: event.target.value })}
                />
            </label>
            <label>
                <span>Postal code</span>
                <input
                    value={form.postal_code ?? ''}
                    onChange={(event) => onChange({ postal_code: event.target.value })}
                />
            </label>

            <label>
                <span>Invoice prefix</span>
                <input
                    value={form.invoice_prefix ?? ''}
                    onChange={(event) => onChange({ invoice_prefix: event.target.value })}
                />
            </label>
            <label>
                <span>Bank IBAN</span>
                <input
                    value={form.bank_iban ?? ''}
                    onChange={(event) => onChange({ bank_iban: event.target.value })}
                />
            </label>
            <label>
                <span>Bank name</span>
                <input
                    value={form.bank_name ?? ''}
                    onChange={(event) => onChange({ bank_name: event.target.value })}
                />
            </label>

            <label>
                <span>VAT number</span>
                <input
                    value={form.vat_number ?? ''}
                    onChange={(event) => onChange({ vat_number: event.target.value })}
                />
            </label>
            <label style={{ gridColumn: '1 / -1' }}>
                <span>Notes</span>
                <textarea
                    value={form.notes ?? ''}
                    onChange={(event) => onChange({ notes: event.target.value })}
                    rows={4}
                />
            </label>
        </div>
    )
}
