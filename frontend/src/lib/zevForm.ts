import type { Zev, ZevInput } from '../types/api'

export function getDefaultZevForm(): ZevInput {
    return {
        name: '',
        start_date: new Date().toISOString().slice(0, 10),
        zev_type: 'vzev',
        city: '',
        grid_operator: '',
        grid_connection_point: '',
        billing_interval: 'monthly',
        address_line1: '',
        address_line2: '',
        postal_code: '',
        invoice_prefix: '',
        bank_iban: '',
        bank_name: '',
        vat_number: '',
        notes: '',
        email_subject_template: '',
        email_body_template: '',
    }
}

export function mapZevToForm(zev: Zev): ZevInput {
    return {
        name: zev.name,
        start_date: zev.start_date,
        owner: zev.owner,
        zev_type: zev.zev_type,
        city: zev.city || '',
        grid_operator: zev.grid_operator || '',
        grid_connection_point: zev.grid_connection_point || '',
        billing_interval: zev.billing_interval as ZevInput['billing_interval'],
        address_line1: zev.address_line1 || '',
        address_line2: zev.address_line2 || '',
        postal_code: zev.postal_code || '',
        invoice_prefix: zev.invoice_prefix || '',
        bank_iban: zev.bank_iban || '',
        bank_name: zev.bank_name || '',
        vat_number: zev.vat_number || '',
        notes: zev.notes || '',
        email_subject_template: zev.email_subject_template ?? '',
        email_body_template: zev.email_body_template ?? '',
    }
}
