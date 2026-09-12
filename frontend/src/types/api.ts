export type UserRole = 'admin' | 'zev_owner' | 'participant' | 'guest'

export interface ImpersonationResult {
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
    /** Account-level default community (ZEV id), always present; null = first managed by name. */
    preferred_zev: string | null
    /** Participants only: name of their community (from /auth/me). */
    zev_name?: string | null
    /** Participants only: number of held memberships (from /auth/me). */
    zev_count?: number | null
    /** Present when this session is an impersonation session. */
    impersonated_by?: User
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

/** Admin-only platform health snapshot (nav-regroup phase 3):
 * every probe is best-effort — "unknown" means the probe could not run
 * (e.g. no broker in this environment), not that the system is broken. */
export type SystemHealthStatus = 'ok' | 'degraded' | 'unknown'

export interface SystemHealth {
    database: {
        status: SystemHealthStatus
        engine: string
        size_bytes: number | null
    }
    celery: {
        status: SystemHealthStatus
        workers_responding: number | null
        queue_depth: number | null
        broker_configured: boolean
        detail?: string
    }
    email: {
        status: SystemHealthStatus
        mode: 'smtp' | 'console' | 'memory' | 'other'
        backend: string
    }
    checked_at: string
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

export interface FeatureFlag {
    id: number
    name: string
    description: string
    enabled: boolean
    updated_at: string
}

export interface FeatureFlagInput {
    enabled: boolean
}

export interface Zev {
    id: string
    name: string
    start_date: string
    owner: number
    zev_type: 'zev' | 'vzev'
    /** Postal code of the grid connection — used only to suggest a grid operator, not an address. */
    postal_code?: string
    grid_operator: string
    grid_operator_elcom_id?: number | null
    tariff_source_url?: string
    grid_connection_point?: string
    billing_interval: string
    invoice_prefix?: string
    invoice_language?: 'de' | 'fr' | 'it' | 'en'
    payment_term_days?: number
    bank_iban?: string
    bank_name?: string
    vat_mode?: 'not_registered' | 'registered' | 'inclusive'
    vat_number?: string
    itemize_tariff_bands?: boolean
    participant_invoice_access?: boolean
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
    postal_code?: string
    grid_operator?: string
    grid_operator_elcom_id?: number | null
    tariff_source_url?: string
    grid_connection_point?: string
    billing_interval: 'monthly' | 'quarterly' | 'semi_annual' | 'annual'
    invoice_prefix?: string
    invoice_language?: 'de' | 'fr' | 'it' | 'en'
    payment_term_days?: number
    bank_iban?: string
    bank_name?: string
    vat_mode?: 'not_registered' | 'registered' | 'inclusive'
    vat_number?: string
    itemize_tariff_bands?: boolean
    participant_invoice_access?: boolean
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
    location_description?: string
}

export interface ZevWizardInput extends Omit<ZevInput, 'owner'> {
    owner: ZevOwnerInput
    metering_points: OwnerMeteringPointInput[]
}

export interface RegisterInput {
    email: string
}

export interface OAuthProvider {
    id: number
    name: string
    display_name: string
    enabled: boolean
}

export interface OAuthProviderConfig extends OAuthProvider {
    client_id: string
    has_client_secret: boolean
    authorization_url: string
    token_url: string
    userinfo_url: string
    redirect_url: string
    scope: string
    created_at: string
    updated_at: string
}

export interface OAuthProviderConfigInput {
    name: string
    display_name: string
    client_id: string
    client_secret?: string
    authorization_url: string
    token_url: string
    userinfo_url: string
    redirect_url: string
    scope: string
    enabled: boolean
}

export interface SocialAccount {
    id: number
    provider_name: string
    provider_display_name: string
    uid: string
    created_at: string
}

export interface ApiKey {
    id: string
    name: string
    prefix: string
    read_only: boolean
    created_at: string
    expires_at: string | null
    last_used_at: string | null
    is_expired: boolean
}

/** The one response that carries the secret. It is never retrievable again. */
export interface ApiKeyWithSecret extends ApiKey {
    key: string
}

/** A key as the admin console sees it: same fields, plus its owner. */
export interface AdminApiKey extends ApiKey {
    user: number
    username: string
    user_email: string
    user_role: string
    revoked_at: string | null
    is_revoked: boolean
}

export interface ApiKeyInput {
    name: string
    read_only: boolean
    expires_at?: string | null
}

export interface OAuthLoginInitiateResponse {
    redirect_url: string
}

export interface SelfSetupZevInput {
    name: string
    start_date: string
    zev_type: 'zev' | 'vzev'
    billing_interval: 'monthly' | 'quarterly' | 'semi_annual' | 'annual'
    postal_code?: string
    grid_operator?: string
    grid_operator_elcom_id?: number | null
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

// The real OSM building footprint (its actual, possibly angled, outline) —
// GeoJSON coordinate order is always [longitude, latitude].
export interface ParticipantBuildingFootprint {
    type: 'Polygon' | 'MultiPolygon'
    coordinates: number[][][] | number[][][][]
}

export type ParticipantOnboardingStatus = 'not_sent' | 'sent' | 'active' | 'revoked'

export interface Participant {
    id: string
    zev: string
    user: number | null
    account_username?: string | null
    onboarding_status?: ParticipantOnboardingStatus
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
    building_footprint?: ParticipantBuildingFootprint | null
    allocation_weight: string
}

export interface ParticipantOnboardingLinkResult {
    onboarding_url: string
    participant: Participant
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
    allocation_weight?: string
}

export interface MeteringPoint {
    id: string
    zev: string
    meter_id: string
    meter_type: 'consumption' | 'production' | 'bidirectional'
    is_active: boolean
    location_description?: string
    /** Readings that a delete of this metering point would cascade-delete. */
    reading_count: number
    /** Assignment windows (any state) that a delete of this metering point would cascade-delete. */
    assignment_count: number
    first_reading_at: string | null
    last_reading_at: string | null
}

export interface MeteringPointInput {
    zev: string
    meter_id: string
    meter_type: 'consumption' | 'production' | 'bidirectional'
    is_active: boolean
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
    allocation_mode: 'personal' | 'community'
}

export interface MeteringPointAssignmentInput {
    metering_point: string
    participant: string
    valid_from: string
    valid_to?: string | null
    allocation_mode: 'personal' | 'community'
}

export type DataQualitySeverity = 'green' | 'yellow' | 'red'

export interface MeteringPointGap {
    start_date: string
    end_date: string
    duration_days: number
}

export interface MeteringPointDataQuality {
    id: string
    meter_id: string
    participant_name: string
    severity: DataQualitySeverity
    data_completeness: number
    days_with_data: number
    total_days: number
    gaps: MeteringPointGap[]
    unassigned_days: number
    unassigned_readings: number
    assignment_overlap: boolean
}

export interface DataQualityStatusResponse {
    date_from: string
    date_to: string
    metering_points: MeteringPointDataQuality[]
}

export type TariffBillingMode = 'energy' | 'percentage_of_energy' | 'monthly_fee' | 'yearly_fee' | 'per_metering_point_monthly_fee' | 'per_metering_point_yearly_fee' | 'shared_monthly_fee' | 'shared_yearly_fee'

export interface Tariff {
    id: string
    zev: string
    name: string
    category: 'energy' | 'grid_fees' | 'levies' | 'metering'
    billing_mode: TariffBillingMode
    energy_type?: 'local' | 'grid' | 'feed_in' | null
    fixed_price_chf?: string | null
    percentage?: string | null
    split_key: 'equal' | 'weight'
    valid_from: string
    valid_to?: string | null
    notes?: string
    /** Written by the Art. 7b importer; blank for tariffs entered by hand. */
    source_component?: 'base' | 'energy' | ''
    source_series_name?: string
    /** Set when this tariff is priced from a fetched series instead of bands. */
    dynamic_source?: string | null
}

export interface TariffInput {
    zev: string
    name: string
    category: 'energy' | 'grid_fees' | 'levies' | 'metering'
    billing_mode: TariffBillingMode
    energy_type?: 'local' | 'grid' | 'feed_in' | null
    fixed_price_chf?: string | null
    percentage?: string | null
    split_key?: 'equal' | 'weight'
    valid_from: string
    valid_to?: string | null
    notes?: string
    dynamic_source?: string | null
}

/**
 * The VSE tariff types a dynamic price source can be fetched as. `integrated`
 * already combines `electricity` + `grid` — billing it beside a separate grid
 * fee or levy tariff double-counts, see `docs/specs/2026-09-dynamic-tariffs.md` §3.3.
 */
export type DynamicTariffType =
    | 'electricity' | 'grid' | 'metering' | 'national_fees' | 'regional_fees'
    | 'dso' | 'dso_complete' | 'integrated' | 'integrated_complete' | 'feed_in' | 'refund'

export type DynamicApiVersion = 'v1_0_5' | 'v2_0_0'

/**
 * A shared price series, fetched from one operator endpoint. Global, not
 * scoped to any one ZEV — two communities on the same product share one
 * source and one fetch (ADR 0018).
 */
export interface DynamicTariffSource {
    id: string
    label: string
    url: string
    api_version: DynamicApiVersion
    tariff_type: DynamicTariffType
    tariff_name: string
    last_fetch_status: 'pending' | 'ok' | 'failed'
    last_fetch_at: string | null
    last_success_at: string | null
    last_fetch_error: string
    /** Extent of the stored series; null before anything has been fetched. */
    covers_from: string | null
    covers_to: string | null
    point_count: number
    linked_tariff_count: number
    linked_zev_count: number
    supports_backfill: boolean
    created_at: string
    updated_at: string
}

export interface DynamicTariffSourceInput {
    label: string
    url: string
    api_version: DynamicApiVersion
    tariff_type: DynamicTariffType
    tariff_name?: string
}

export interface DynamicSourceDiscovery {
    api_version: DynamicApiVersion
    version_detected: boolean
    components_discovered: boolean
    components: Array<{
        tariff_type: DynamicTariffType
        tariff_name: string
    }>
}

export interface DynamicPricePoint {
    valid_from: string
    valid_to: string
    price_chf_per_kwh: string
}

export interface DynamicPriceHistory {
    source: string
    date_from: string
    date_to: string
    stats: {
        point_count: number
        minimum_chf_per_kwh: string | null
        maximum_chf_per_kwh: string | null
        average_chf_per_kwh: string | null
        negative_count: number
        gap_count: number
    }
    gaps: Array<{ from: string; to: string }>
    points: DynamicPricePoint[]
}

export interface DynamicSourceFetchResult {
    task_id: string
    correlation_id: string
    backfill: boolean
    queued_at: string
}

/**
 * `flat` prices every hour; `high`/`low` are the HT/NT pair a Swiss tariff
 * traditionally has and that the contract PDF and price chart name; `band` is
 * a tariff with three or more prices, whose bands the standard does not name.
 */
export type TariffPeriodType = 'flat' | 'high' | 'low' | 'band'

export interface TariffPeriod {
    id: string
    tariff: string
    period_type: TariffPeriodType
    /** Name for a `band`; blank falls back to its time window. */
    label?: string
    price_chf_per_kwh: string
    time_from?: string | null
    time_to?: string | null
    weekdays?: string
    /** Comma-separated month numbers 1-12; blank means every month. */
    months?: string
}

/** One version of a tariff, as returned nested inside a series. */
export interface TariffVersion extends Tariff {
    periods: TariffPeriod[]
}

/** An uncovered stretch between two versions. Both bounds inclusive. */
export interface TariffGap {
    start: string
    end: string
}

/**
 * Every tariff in a ZEV sharing a name, treated as versions of one tariff. The
 * identity fields are invariant across versions, so they live on the series.
 */
export interface TariffSeries {
    zev: string
    name: string
    category: Tariff['category']
    billing_mode: TariffBillingMode
    energy_type?: Tariff['energy_type']
    version_count: number
    /** `null` when today falls in a gap, or the tariff has been retired. */
    active_version_id: string | null
    gaps: TariffGap[]
    /** Newest first. */
    versions: TariffVersion[]
}

/**
 * Body for new-version / duplicate. Prices are optional: omitting them copies
 * the source version's, which is what a pure validity shift wants.
 */
export interface TariffVersionInput {
    valid_from: string
    fixed_price_chf?: string | null
    percentage?: string | null
    periods?: Array<Omit<TariffPeriodInput, 'tariff'>>
}

export interface TariffPeriodInput {
    tariff: string
    period_type: TariffPeriodType
    label?: string
    price_chf_per_kwh: string
    time_from?: string | null
    time_to?: string | null
    weekdays?: string
    months?: string
}

export interface GridOperator {
    id: number
    name: string
    uid: string
    website: string
    /** ElCom's registered address for this operator's machine-readable tariffs. A suggestion — fetch it before saving it as tariff_source_url. */
    tariff_url: string
    /** Whether tariff_url looks like the tariff file itself rather than a page about it. */
    tariff_url_is_direct: boolean
}

export interface GridOperatorList {
    source: string
    cube: string
    licence: string
    period: string
    fetched_on: string
    operators: GridOperator[]
}

export interface GridOperatorSuggestion {
    operators: GridOperator[]
}

export type InvoicePdfStatus = 'none' | 'pending' | 'ready' | 'failed'

export interface Invoice {
    id: string
    invoice_number: string
    zev: string
    zev_name: string
    participant: string
    participant_name: string
    period_start: string
    period_end: string
    due_date?: string | null
    subtotal_chf?: string
    vat_rate?: string
    vat_chf?: string
    total_chf: string
    total_local_kwh?: string
    total_grid_kwh?: string
    total_feed_in_kwh?: string
    status: string
    pdf_url?: string | null
    /**
     * Where the document is, as distinct from the invoice's own `status`.
     *
     * `pdf_url` says whether one exists; this says whether one is coming. A
     * queued render and a failed one both leave `pdf_url` null.
     */
    pdf_status?: InvoicePdfStatus
    /** Status of the newest email attempt; present on list and detail. */
    last_email_status?: 'pending' | 'sent' | 'failed' | null
    items?: InvoiceItem[]
    email_logs?: EmailLog[]
    /** Detail reads only; never carries the secret (see InvoiceAccessLink). */
    access_link?: InvoiceAccessLink | null
    /** Id of the newest email attempt (list serializer annotation).
     * The retry endpoint is log-scoped, so the email-delivery tab needs the
     * log id to offer an inline retry off the list payload. */
    last_email_log_id?: string | null
}

/**
 * State of the QR link printed on one invoice.
 *
 * The `prefix` identifies the token but cannot open anything on its own — the
 * secret stays on the printed document — so this is safe to render.
 */
export interface InvoiceAccessLink {
    prefix: string
    created_at: string
    /** Stamped at most hourly, so it answers "opened at all?", not "how often". */
    last_used_at: string | null
}

/** Per-row generation eligibility for a viewed billing period: `eligible`
 * offers Generate, `blocked` links to the locking invoice, `covered` links
 * to the first invoice that already settles the period. */
export interface GenerationEligibility {
    state: 'eligible' | 'covered' | 'blocked'
    invoice_id: string | null
    invoice_number: string | null
}

export interface InvoicePeriodParticipantRow {    participant_id: string
    participant_name: string
    participant_email?: string
    invoice: Invoice | null
    /** Generation eligibility for rows without a live exact-period invoice
     * (null when the row's own invoice governs the actions). */
    generation_eligibility: GenerationEligibility | null
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
    tariff_category: 'energy' | 'grid_fees' | 'levies' | 'metering'
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

// ---------------------------------------------------------------------------
// Readiness / attention (nav-regroup phase 2)
// ---------------------------------------------------------------------------

export type ReadinessStepKey =
    | 'metering'
    | 'assignments'
    | 'tariffs'
    | 'generated'
    | 'generation_conflicts'
    | 'approved'
    | 'sent'
    | 'paid'

export type ReadinessStepStatus = 'ok' | 'warn' | 'todo' | 'done'

export type ReadinessNextAction =
    | 'fix_metering'
    | 'fix_assignments'
    | 'fix_tariffs'
    | 'generate'
    | 'review_generation_conflicts'
    | 'approve'
    | 'send'
    | 'track_payments'
    | 'none'

export interface ReadinessStepMeterGap {
    meter_id: string
    missing_days: number
    from: string
    to: string
}

export interface ReadinessStepDetailData {
    /** metering warn: days missing across the affected points. */
    missing_days?: number
    /** metering warn: affected meters (first three). */
    meters?: ReadinessStepMeterGap[]
    /** metering warn: how many further meters were cut off. */
    more_meters?: number
    /** assignments warn. */
    unassigned_readings?: number
    unassigned_days?: number
    /** tariffs warn: uncovered stretches (first four). */
    ranges?: Array<{ from: string; to: string }>
    more_ranges?: number
    /** generated todo. */
    missing?: number
    missing_participants?: string[]
    more_missing?: number
    /** generation_conflicts warn: participants blocked by locked overlap. */
    conflict_count?: number
    conflicts?: ReadinessConflict[]
    more_conflicts?: number
    /** paid todo: active invoices not yet paid. */
    unpaid?: number
}

/** One participant blocked by locked overlapping invoices. */
export interface ReadinessConflict {
    participant_id: string
    participant_name: string
    invoices: ReadinessConflictInvoice[]
}

export interface ReadinessConflictInvoice {
    id: string
    number: string
    status: string
    start: string
    end: string
}

export interface ReadinessStep {
    key: ReadinessStepKey
    status: ReadinessStepStatus
    /** Invoices / readings / days affected. Data steps count affected points
     * (metering) or readings (assignments); generated counts participants
     * that have an invoice against `total` eligible ones; workflow steps
     * count invoices waiting at that step against `total` active ones. */
    count: number
    /** Denominator: eligible participants (generated) or active invoices. */
    total?: number
    /** Unresolved (not retried-to-success) email failures for the period. */
    failed?: number | null
    /** English API fallback — never rendered by the UI. */
    detail?: string | null
    /** Structured fields the UI localizes from (spec §7). */
    detail_data?: ReadinessStepDetailData
    /** Route to the page holding the step's action; absent while a
     * downstream step merely waits on an upstream one. */
    link?: string | null
}

export interface ReadinessSetupBlock {
    participants: number
    metering_points: number
    tariffs: number
    settings_complete: boolean
    /** False when participants/meters exist but no active participant holds a
     * current-or-future assignment (or when master data is empty). */
    complete: boolean
    reason: 'no_master_data' | 'no_billable_assignment' | null
    /** Assignment management destination, present when `complete` is false. */
    assignment_link: string | null
    /** Blank IBAN is advisory: reported here without failing `complete`. */
    billing_settings_complete: boolean
    billing_settings_link: string | null
}

export interface ReadinessResponse {
    zev_id: string
    period: {
        start: string
        end: string
        interval: 'monthly' | 'quarterly' | 'semi_annual' | 'annual'
    } | null
    steps: ReadinessStep[]
    next_action: ReadinessNextAction
    /** Present only in first-run mode (period null, master data empty). */
    setup?: ReadinessSetupBlock | null
    /** Master data exists but no billing period has ended yet. */
    awaiting_first_period?: boolean
    /** No ended period has open work; `period` is the most recent ended one
     * (its steps may still show trailing items like unpaid invoices). */
    caught_up?: boolean
}

/** One entry of the `periods=all` readiness list: like ReadinessResponse
 * without the top-level `zev_id` (it lives on the envelope), but the period
 * carries calendar-versus-invoice provenance — historical entries only keep
 * the configured interval when their exact dates align to it. */
export interface ReadinessPeriod {
    period: {
        start: string
        end: string
        interval: string | null
        source: 'calendar' | 'invoice'
        /** False while the period is still collecting data. */
        ended: boolean
    }
    steps: ReadinessStep[]
    next_action: ReadinessNextAction
    caught_up?: boolean
    setup?: ReadinessSetupBlock | null
}

/**
 * Cross-period attention items only (nav-regroup phase 2, spec §7): the types
 * the readiness cockpit cannot show as steps. Overview groups them by period
 * or into community notices; tariff/metering/assignment gaps and setup state are readiness
 * concerns and are not emitted here.
 */
export type AttentionItemType = 'email_failed' | 'invoice_overdue' | 'participant_validity'

export interface AttentionItem {
    /** UUID for concrete records; type-prefixed for aggregate items. */
    id: string
    type: AttentionItemType
    /** English fallback for API-only consumers; the UI localizes from the
     * structured fields below and never renders this. */
    label: string
    /** Period the item refers to, when item-scoped (interval echoes the ZEV's). */
    period?: { start: string; end: string; interval?: string } | null
    /** Invoice reference for invoice-scoped items. */
    invoice_id?: string | null
    /** In-app route to the page that resolves the item. */
    link: string
    // Structured fields the frontend localizes from:
    invoice_number?: string
    recipient?: string
    due_date?: string | null
    participant_id?: string
    participant_name?: string
    valid_to?: string
    expired?: boolean
}

export type AuditActionCategory =
    | 'auth'
    | 'governance'
    | 'participant'
    | 'metering'
    | 'tariff'
    | 'invoice'
    | 'import'
    | 'template'
    | 'system'

export type AuditEventStatus = 'started' | 'queued' | 'success' | 'failed' | 'denied'

export interface AuditEvent {
    id: string
    created_at: string
    actor_user: number | null
    actor_role_snapshot: string
    actor_display: string
    zev: string | null
    action_category: AuditActionCategory
    action_type: string
    target_type: string
    target_id: string
    target_display: string
    status: AuditEventStatus
    request_id: string | null
    correlation_id: string | null
    source: 'api' | 'celery' | 'system' | 'management_command'
    ip_address: string | null
    user_agent: string
    summary: string
    reason: string
    changes_json: Record<string, unknown>
    metadata_json: Record<string, unknown>
}

export interface AuditEventFilters {
    page?: number
    actor_user?: number
    zev?: string
    action_category?: AuditActionCategory
    action_type?: string
    target_type?: string
    target_id?: string
    status?: AuditEventStatus
    date_from?: string
    date_to?: string
    q?: string
}

export interface AuditFilterOption {
    id: string
    name: string
}

export interface AuditActorOption {
    id: number
    username: string
}

export interface AuditFilterOptions {
    zevs: AuditFilterOption[]
    actors: AuditActorOption[]
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

export interface ImportDeletionResult {
    deleted_logs: number
    deleted_readings: number
    mode?: 'all' | 'period'
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
    is_customized: boolean
    is_stale?: boolean
    detail?: string
}

export interface EmailTemplateResponse {
    template_key: string
    subject: string
    body: string
    is_customized: boolean
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
    zev_totals: {
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
    zev_totals: {
        produced_kwh: number
        consumed_kwh: number
        imported_kwh: number
        exported_kwh: number
    }
    zev_participant_stats: Array<{
        participant_id: string
        participant_name: string
        total_consumed_kwh: number
        total_produced_kwh: number
        from_zev_kwh: number
        from_grid_kwh: number
    }>
    current_participant_id: string | null
}

export type MeteringDashboardSummary = ZevOwnerDashboardSummary | ParticipantDashboardSummary

export interface HourlyProfileEntry {
    hour: number
    from_zev_kwh: number
    from_grid_kwh: number
}

export interface HourlyProfileResponse {
    hourly_profile: HourlyProfileEntry[] | null
}

export interface FeasibilityParticipantInput {
    name: string
    annual_production_kwh?: string
    annual_consumption_kwh?: string
}

export interface FeasibilityInput {
    annual_production_kwh: string
    annual_consumption_kwh: string
    self_consumption_rate: string
    retail_price_chf_per_kwh?: string
    feed_in_price_chf_per_kwh?: string
    internal_energy_price_chf_per_kwh?: string
    annual_opex_chf?: string
    capex_chf?: string
    horizon_years?: number
    discount_rate?: string
    participants?: FeasibilityParticipantInput[]
}

export interface FeasibilitySensitivityPoint {
    self_consumption_rate: string
    annual_net_benefit_chf: string
}

export interface FeasibilityPriceSensitivityPoint {
    internal_price_pct_of_retail: string
    internal_price_chf_per_kwh: string
    producer_gain_chf: string
    consumer_savings_chf: string
}

export interface FeasibilityFairPriceRange {
    low_chf_per_kwh: string
    high_chf_per_kwh: string
}

export interface FeasibilityParticipantResult {
    name: string
    annual_production_kwh: string
    annual_consumption_kwh: string
    self_consumed_from_own_production_kwh: string
    exported_kwh: string
    from_local_pool_kwh: string
    from_grid_kwh: string
    producer_gain_chf: string
    consumer_savings_chf: string
    net_benefit_chf: string
}

export interface FeasibilityResult {
    self_consumed_kwh: string
    grid_import_kwh: string
    grid_export_kwh: string
    autarky_rate: string
    baseline_consumer_cost_chf: string
    baseline_producer_revenue_chf: string
    vzev_consumer_cost_chf: string
    vzev_producer_revenue_chf: string
    consumer_savings_chf: string
    producer_gain_chf: string
    annual_gross_benefit_chf: string
    annual_net_benefit_chf: string
    payback_years: string | null
    roi: string | null
    npv_chf: string
    cashflow_by_year: string[]
    sensitivity: FeasibilitySensitivityPoint[]
    break_even_self_consumption_rate: string | null
    price_sensitivity: FeasibilityPriceSensitivityPoint[]
    equal_split_price_chf_per_kwh: string | null
    fair_price_range: FeasibilityFairPriceRange | null
    participants: FeasibilityParticipantResult[]
}

export interface FeasibilityPrefillParticipant {
    name: string
    annual_production_kwh: string
    annual_consumption_kwh: string
    has_metering_data: boolean
}

export interface FeasibilityPrefill {
    participants: FeasibilityPrefillParticipant[]
    self_consumption_rate: string | null
    retail_price_chf_per_kwh: string | null
    feed_in_price_chf_per_kwh: string | null
    internal_energy_price_chf_per_kwh: string | null
}

/**
 * VSE/AES tariff import (Art. 7b StromVV).
 *
 * A candidate is a tariff the import *would* create — it carries the status it
 * would have against this ZEV's existing tariffs, plus everything that could
 * not be represented, so the user decides before anything is written.
 */
export interface VseTariffPeriodPreview {
    period_type: TariffPeriodType
    label: string
    price_chf_per_kwh: string
    time_from: string | null
    time_to: string | null
    weekdays: string
    months: string
}

export type VseTariffCandidateStatus = 'new' | 'new_version' | 'duplicate' | 'conflict' | 'unsupported'

export interface VseTariffCandidate {
    key: string
    name: string
    category: 'energy' | 'grid_fees' | 'levies' | 'metering'
    billing_mode: string
    /** Modes the user may pick instead; empty when there is nothing to choose. */
    billing_mode_options: string[]
    energy_type: string | null
    fixed_price_chf: string | null
    valid_from: string
    valid_to: string | null
    notes: string
    periods: VseTariffPeriodPreview[]
    source_tariff_name: string
    source_tariff_type: string
    source_customer_type: string
    source_voltage_level: number | null
    standard_basegroup: boolean
    /** Set only for a dynamic-tariff candidate: the URL its price would be
     *  fetched from. Blank for every static candidate. */
    dynamic_url: string
    /** Name the created tariff takes; differs from `name` when the series was
     *  matched on provenance and has been renamed since. */
    series_name: string
    status: VseTariffCandidateStatus
    detail: string
    warnings: string[]
    recommended: boolean
    effective_valid_to: string | null
}

export interface VseTariffImportPreview {
    dso_name: string
    dso_number: number | null
    source_url: string
    document_digest: string
    candidates: VseTariffCandidate[]
    errors: Array<{ tariff: string; error: string }>
}

/** One ticked preview row, with the user's answer to how it should be billed. */
export interface VseTariffImportSelection {
    key: string
    billing_mode?: string
}

export interface VseTariffImportResult {
    created: Array<{
        name: string
        category: string
        billing_mode: string
        valid_from: string
        valid_to: string | null
        /** Whether this tariff was linked to a dynamic price source. */
        dynamic: boolean
    }>
    skipped: Array<{ name: string; reason: string }>
    errors: Array<{ name: string; error: string }>
}

/** One line on a publicly-viewable invoice (see `PublicInvoice`). */
export interface PublicInvoiceItem {
    category: 'energy' | 'grid_fees' | 'levies' | 'metering'
    description: string
    quantity: string
    unit: string
    total_chf: string
}

/**
 * One invoice, as served to the bearer of the link printed on it.
 *
 * Deliberately narrow: no contact detail, no other invoice, no other
 * participant, no ZEV-wide figure. That narrowness is the reason the endpoint
 * needs no login at all — see the backend's `views_public` docstring before
 * widening this type to match a wider payload.
 */
export interface PublicInvoice {
    invoice_number: string
    zev_name: string
    /**
     * The language the invoice was issued in — not a reader preference.
     *
     * The line items and the chart labels are already written in it, so the
     * page renders itself in it too rather than in the browser's locale.
     */
    language: string
    participant_name: string
    period_start: string
    period_end: string
    status: string
    is_paid: boolean
    total_chf: string
    currency: string
    /** Null when the invoice has no consumption — then no QR was printed either. */
    energy_summary: {
        local_kwh: string
        grid_kwh: string
        total_kwh: string
        local_share_pct: string
    } | null
    items: PublicInvoiceItem[]
    has_pdf: boolean
}

export type ExportJobStatus = 'queued' | 'running' | 'completed' | 'failed'

export interface ExportJob {
    id: string
    export_type: 'annual_statements'
    zev_id: string
    params: { year: number }
    status: ExportJobStatus
    created_at: string
    started_at: string | null
    completed_at: string | null
    file_expires_at: string | null
    generated_count: number | null
    omitted_count: number | null
    omitted_participant_ids: string[]
    error_message: string
    expired: boolean
}
