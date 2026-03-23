export type UserRole = 'admin' | 'zev_owner' | 'participant' | 'guest'

export interface AuthTokens {
    access: string
    refresh: string
}

export interface ImpersonationTokens extends AuthTokens {
    impersonated_user: User
    impersonator: User
}

export interface User {
    id: number
    username: string
    email: string
    first_name: string
    last_name: string
    role: UserRole
    must_change_password: boolean
}

export interface UserInput {
    username: string
    email: string
    first_name: string
    last_name: string
    role: UserRole
    must_change_password?: boolean
}

export type ShortDateFormat = 'dd.MM.yyyy' | 'dd/MM/yyyy' | 'MM/dd/yyyy' | 'yyyy-MM-dd'
export type LongDateFormat = 'd MMMM yyyy' | 'd. MMMM yyyy' | 'MMMM d, yyyy' | 'yyyy-MM-dd'
export type DateTimeFormat = 'dd.MM.yyyy HH:mm' | 'dd/MM/yyyy HH:mm' | 'MM/dd/yyyy HH:mm' | 'yyyy-MM-dd HH:mm'

export interface AppSettings {
    date_format_short: ShortDateFormat
    date_format_long: LongDateFormat
    date_time_format: DateTimeFormat
    updated_at: string
}

export interface AppSettingsInput {
    date_format_short?: ShortDateFormat
    date_format_long?: LongDateFormat
    date_time_format?: DateTimeFormat
}

export interface VatRate {
    id: number
    rate: string
    valid_from: string
    valid_to?: string | null
    created_at: string
    updated_at: string
}

export interface VatRateInput {
    rate: string
    valid_from: string
    valid_to?: string | null
}

export interface Zev {
    id: string
    name: string
    start_date: string
    owner: number
    zev_type: 'zev' | 'vzev'
    grid_operator: string
    grid_connection_point?: string
    billing_interval: string
    invoice_prefix?: string
    invoice_language?: 'de' | 'fr' | 'it' | 'en'
    bank_iban?: string
    bank_name?: string
    vat_number?: string
    notes?: string
    email_subject_template?: string
    email_body_template?: string
    local_tariff_notes?: string
    additional_contract_notes?: string
}

export interface ZevInput {
    name: string
    start_date: string
    owner?: number
    zev_type: 'zev' | 'vzev'
    grid_operator?: string
    grid_connection_point?: string
    billing_interval: 'monthly' | 'quarterly' | 'semi_annual' | 'annual'
    invoice_prefix?: string
    invoice_language?: 'de' | 'fr' | 'it' | 'en'
    bank_iban?: string
    bank_name?: string
    vat_number?: string
    notes?: string
    email_subject_template?: string
    email_body_template?: string
    local_tariff_notes?: string
    additional_contract_notes?: string
}

export interface ZevOwnerInput {
    username?: string
    title?: 'mr' | 'mrs' | 'ms' | 'dr' | 'prof' | ''
    first_name: string
    last_name: string
    email: string
    phone?: string
    address_line1?: string
    address_line2?: string
    postal_code?: string
    city?: string
}

export interface OwnerMeteringPointInput {
    meter_id: string
    meter_type: 'consumption' | 'production' | 'bidirectional'
    is_active?: boolean
    valid_from?: string
    valid_to?: string | null
    location_description?: string
}

export interface ZevWizardInput extends Omit<ZevInput, 'owner'> {
    owner: ZevOwnerInput
    metering_points: OwnerMeteringPointInput[]
}

export interface RegisterInput {
    username: string
    email: string
}

export interface SelfSetupZevInput {
    name: string
    start_date: string
    zev_type: 'zev' | 'vzev'
    billing_interval: 'monthly' | 'quarterly' | 'semi_annual' | 'annual'
    grid_operator?: string
}

export interface ZevWizardResult {
    zev: {
        id: string
        name: string
    }
    owner: {
        id: number
        username: string
        temporary_password: string
    }
    owner_participant_id: string
    metering_points: Array<{
        id: string
        meter_id: string
    }>
}

export interface Participant {
    id: string
    zev: string
    user: number | null
    account_username?: string | null
    initial_password?: string | null
    title?: 'mr' | 'mrs' | 'ms' | 'dr' | 'prof' | ''
    first_name: string
    last_name: string
    email: string
    phone?: string
    address_line1?: string
    address_line2?: string
    postal_code?: string
    city?: string
    notes?: string
    valid_from: string
    valid_to?: string | null
    metering_points?: MeteringPoint[]
    has_metering_point_assignment?: boolean
}

export interface ParticipantAccountCreateResult {
    participant: Participant
    account: User
    temporary_password: string
}

export interface ParticipantInput {
    zev: string
    title?: 'mr' | 'mrs' | 'ms' | 'dr' | 'prof' | ''
    first_name: string
    last_name: string
    email: string
    valid_from: string
    valid_to?: string | null
    phone?: string
    city?: string
    postal_code?: string
    address_line1?: string
    address_line2?: string
    notes?: string
}

export interface MeteringPoint {
    id: string
    zev: string
    participant?: string | null
    meter_id: string
    meter_type: 'consumption' | 'production' | 'bidirectional'
    is_active: boolean
    valid_from: string
    valid_to?: string | null
    location_description?: string
}

export interface MeteringPointInput {
    zev: string
    participant?: string | null
    meter_id: string
    meter_type: 'consumption' | 'production' | 'bidirectional'
    is_active: boolean
    valid_from: string
    valid_to?: string | null
    location_description?: string
}

export interface MeteringPointAssignment {
    id: string
    metering_point: string
    participant: string
    valid_from: string
    valid_to?: string | null
    created_at: string
    updated_at: string
}

export interface MeteringPointAssignmentInput {
    metering_point: string
    participant: string
    valid_from: string
    valid_to?: string | null
}

export type TariffBillingMode = 'energy' | 'percentage_of_energy' | 'monthly_fee' | 'yearly_fee' | 'per_metering_point_monthly_fee' | 'per_metering_point_yearly_fee'

export interface Tariff {
    id: string
    zev: string
    name: string
    category: 'energy' | 'grid_fees' | 'levies'
    billing_mode: TariffBillingMode
    energy_type?: 'local' | 'grid' | 'feed_in' | null
    fixed_price_chf?: string | null
    percentage?: string | null
    valid_from: string
    valid_to?: string | null
    notes?: string
}

export interface TariffInput {
    zev: string
    name: string
    category: 'energy' | 'grid_fees' | 'levies'
    billing_mode: TariffBillingMode
    energy_type?: 'local' | 'grid' | 'feed_in' | null
    fixed_price_chf?: string | null
    percentage?: string | null
    valid_from: string
    valid_to?: string | null
    notes?: string
}

export interface TariffPeriod {
    id: string
    tariff: string
    period_type: 'flat' | 'high' | 'low'
    price_chf_per_kwh: string
    time_from?: string | null
    time_to?: string | null
    weekdays?: string
}

export interface TariffPeriodInput {
    tariff: string
    period_type: 'flat' | 'high' | 'low'
    price_chf_per_kwh: string
    time_from?: string | null
    time_to?: string | null
    weekdays?: string
}

export interface TariffPresetPeriod {
    period_type: 'flat' | 'high' | 'low'
    price_chf_per_kwh: string
    time_from?: string | null
    time_to?: string | null
    weekdays?: string
}

export interface TariffPreset {
    name: string
    category: 'energy' | 'grid_fees' | 'levies'
    billing_mode: TariffBillingMode
    energy_type?: 'local' | 'grid' | 'feed_in' | null
    fixed_price_chf?: string | null
    percentage?: string | null
    valid_from: string
    valid_to?: string | null
    notes?: string
    periods: TariffPresetPeriod[]
}

export interface Invoice {
    id: string
    invoice_number: string
    zev: string
    participant: string
    participant_name: string
    period_start: string
    period_end: string
    subtotal_chf?: string
    vat_rate?: string
    vat_chf?: string
    total_chf: string
    total_local_kwh?: string
    total_grid_kwh?: string
    total_feed_in_kwh?: string
    status: string
    pdf_url?: string | null
    items?: InvoiceItem[]
    email_logs?: EmailLog[]
}

export interface InvoicePeriodParticipantRow {
    participant_id: string
    participant_name: string
    participant_email?: string
    invoice: Invoice | null
    metering_data_complete: boolean
    metering_points_total: number
    metering_points_with_data: number
    missing_meter_ids: string[]
    missing_meter_details?: Array<{
        meter_id: string
        missing_days: number
    }>
}

export interface InvoicePeriodOverview {
    zev_id: string
    zev_name: string
    billing_interval: 'monthly' | 'quarterly' | 'semi_annual' | 'annual'
    period_start: string
    period_end: string
    rows: InvoicePeriodParticipantRow[]
}

export interface InvoiceItem {
    id: string
    item_type: string
    tariff_category: 'energy' | 'grid_fees' | 'levies'
    description: string
    quantity_kwh: string
    unit: string
    unit_price_chf: string
    total_chf: string
    sort_order: number
}

export interface EmailLog {
    id: string
    invoice: string
    recipient: string
    subject: string
    status: 'pending' | 'sent' | 'failed'
    error_message?: string
    sent_at?: string | null
    created_at: string
}

export interface PaginatedResponse<T> {
    count: number
    next: string | null
    previous: string | null
    results: T[]
}

export interface ImportLog {
    id: string
    batch_id?: string
    zev?: string
    imported_by?: number | null
    filename: string
    rows_total?: number
    rows_imported: number
    rows_skipped: number
    source: string
    errors?: Array<{ row: number | null; error: string }>
    created_at: string
}

export interface ImportPreviewRow {
    row: number
    meter_id: string | null
    metering_point_exists: boolean
    meter_type?: string | null
    timestamp?: string | null
    energy?: string | null
    existing_data?: boolean
    interval_minutes?: number
    values_count?: number
}

export interface ImportPreviewResult {
    rows_total: number
    preview_rows: ImportPreviewRow[]
    summary: {
        existing_metering_points: number
        missing_metering_points: number
        rows_previewed: number
    }
    errors: Array<{ row: number | null; error: string }>
}

export interface ChartDataPoint {
    bucket: string
    in_kwh: number
    out_kwh: number
}

export interface RawMeteringReading {
    timestamp: string
    direction: 'in' | 'out'
    energy_kwh: number
    resolution: string
    import_source: string
}

export interface RawMeteringDailyRow {
    date: string
    in_kwh: number
    out_kwh: number
    readings_count: number
    readings: RawMeteringReading[]
}

export interface DashboardStats {
    zevs: {
        total: number
    }
    participants: {
        total: number
    }
    invoices: {
        draft: number
        approved: number
        sent: number
        paid: number
        cancelled: number
        total_revenue: number
    }
    emails: {
        total: number
        sent: number
        failed: number
        pending: number
    }
    recent_invoices: Array<{
        invoice_number: string
        participant_name: string
        zev_name: string
        total_chf: number
        status: string
        created_at: string
    }>
}

export interface PdfTemplateResponse {
    template_name: string
    content: string
    detail?: string
}

export interface ZevOwnerDashboardSummary {
    role: 'zev_owner'
    bucket: 'day' | 'hour' | 'month'
    selected_participant_id?: string | null
    selected_participant_name?: string | null
    totals: {
        produced_kwh: number
        consumed_kwh: number
        imported_kwh: number
        exported_kwh: number
    }
    timeline: Array<{
        bucket: string
        produced_kwh: number
        consumed_kwh: number
        imported_kwh: number
        exported_kwh: number
    }>
    participant_stats: Array<{
        participant_id: string
        participant_name: string
        total_consumed_kwh: number
        total_produced_kwh: number
        from_zev_kwh: number
        from_grid_kwh: number
    }>
}

export interface ParticipantDashboardSummary {
    role: 'participant'
    bucket: 'day' | 'hour' | 'month'
    totals: {
        consumed_from_zev_kwh: number
        imported_from_grid_kwh: number
        total_consumed_kwh: number
    }
    timeline: Array<{
        bucket: string
        consumed_from_zev_kwh: number
        imported_from_grid_kwh: number
        total_consumed_kwh: number
    }>
}

export type MeteringDashboardSummary = ZevOwnerDashboardSummary | ParticipantDashboardSummary
