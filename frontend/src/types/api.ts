/** Platform role: an administrator, or not. Access to a community comes from `memberships` (#761). */
export type UserRole = 'admin' | 'user'

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
    /** From /auth/me: whether the account can re-authenticate with a password (participants and OAuth-only accounts cannot). */
    has_usable_password?: boolean
    /** Present when this session is an impersonation session. */
    impersonated_by?: User
    /** From /auth/me: every community the account relates to (#761). */
    memberships?: Membership[]
    /** From /auth/me: whether the account may set up a ZEV of its own. */
    may_create_zev?: boolean
}

/** Per-ZEV access an account holds through a grant (#761). */
export type ZevAccessRole = 'manager' | 'viewer'

/** One manager or viewer grant on a ZEV, as the access API returns it (#761).
 * Entries with `source: 'role'` are not grants: the account manages the ZEV
 * because its party is issuer or representative (read-only, ends with the role). */
export interface ZevAccessGrant {
    id: string
    zev: string
    role: ZevAccessRole
    valid_from: string
    valid_to: string | null
    is_active: boolean
    granted_by: { id: number; full_name: string } | null
    created_at: string
    user: { id: number; email: string; first_name: string; last_name: string; pending_invitation: boolean }
    source?: 'grant' | 'role'
    /** For `source: 'role'`: the role that gives the access, and whose it is. */
    party_role?: { role: 'issuer' | 'representative'; party: string; party_display_name: string }
}

/** POST /zev/zevs/{id}/access/ answers with the grant and whether its email went out. */
export interface ZevAccessGrantCreated extends ZevAccessGrant {
    email_sent: boolean
}

/** Give access to an email address or to a party of the ZEV (one of the two). */
export interface ZevAccessGrantInput {
    email?: string
    /** A party without a login is invited at its own email address and linked to the new account. */
    party?: string
    role: ZevAccessRole
    valid_to?: string | null
}

/** One participant row an account is linked to in a community. */
export interface MembershipParticipant {
    id: string
    valid_from: string
    valid_to: string | null
    /** The row is current: no end date, or it has not passed. */
    live: boolean
}

/** One community an account relates to: its grant there and its participant rows (/auth/me and the admin accounts list). */
export interface Membership {
    zev: string
    zev_name: string
    zev_disabled: boolean
    access: ZevAccessRole | null
    /** Roles that make the account a manager here today (issuer, representative). */
    roles?: Array<'issuer' | 'representative'>
    participants: MembershipParticipant[]
}

/** Where an account stands against `AppSettings.mfa_required`; `null` when the policy is off. */
export interface MfaCompliance {
    status: 'compliant' | 'grace' | 'overdue'
    /** ISO datetime: when enrolment stops being optional. */
    deadline: string
}

/** A user as the admin accounts list returns it: the account plus where it belongs and its second factors. */
export interface AdminUser extends User {
    is_active: boolean
    memberships: Membership[]
    mfa_methods: Array<'totp' | 'passkey'>
    mfa_compliance: MfaCompliance | null
    /** ISO datetime of the account's last completed sign-in (any door), or null if it has never signed in. */
    last_login: string | null
}

/** Admin: create-account payload. No password field — the server always mints one for a console-created account. */
export interface CreateUserInput {
    username: string
    email: string
    first_name: string
    last_name: string
    role: UserRole
}

/** Admin: create-account response. `generated_password` is present only once, in this response. */
export interface CreatedUser extends Pick<AdminUser, 'id' | 'username' | 'email' | 'first_name' | 'last_name' | 'role'> {
    generated_password?: string
}

export interface UserInput {
    username: string
    email: string
    first_name: string
    last_name: string
    role: UserRole
    must_change_password?: boolean
    is_active?: boolean
}

export type ShortDateFormat = 'dd.MM.yyyy' | 'dd/MM/yyyy' | 'MM/dd/yyyy' | 'yyyy-MM-dd'
export type LongDateFormat = 'd MMMM yyyy' | 'd. MMMM yyyy' | 'MMMM d, yyyy' | 'yyyy-MM-dd'
export type DateTimeFormat = 'dd.MM.yyyy HH:mm' | 'dd/MM/yyyy HH:mm' | 'MM/dd/yyyy HH:mm' | 'yyyy-MM-dd HH:mm'

export interface AppSettings {
    date_format_short: ShortDateFormat
    date_format_long: LongDateFormat
    date_time_format: DateTimeFormat
    /** Every account must hold a second factor (a passkey or TOTP). */
    mfa_required: boolean
    mfa_grace_period_days: number
    updated_at: string
}

export interface AppSettingsInput {
    date_format_short?: ShortDateFormat
    date_format_long?: LongDateFormat
    date_time_format?: DateTimeFormat
    mfa_required?: boolean
    mfa_grace_period_days?: number
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
    /** ADR 0021: whether TOTP secrets can be encrypted at rest. "unknown"
     * means MFA_ENCRYPTION_KEYS is unset — expected on an instance that
     * hasn't opted into two-factor authentication, not a fault. */
    mfa: {
        status: SystemHealthStatus
        encryption_key_configured: boolean
    }
    email: {
        status: SystemHealthStatus
        mode: 'smtp' | 'console' | 'memory' | 'other'
        backend: string
    }
    /** Is the instance protected by a recent backup? "unknown": no destination is enabled. */
    backups: {
        status: SystemHealthStatus
        destinations_enabled?: number
        schedule_enabled?: boolean
        last_successful_at?: string | null
        age_hours?: number | null
        stale?: boolean
        encrypted?: boolean
        encryption_required?: boolean
        encryption_key_problem?: boolean
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
    /** Server revision used to ignore list responses older than an accepted save. */
    updated_at: string
    name: string
    start_date: string
    /** Today's issuer of the ZEV's documents (#761), or null when none is set. */
    issuer?: { party: string; display_name: string } | null
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
    /** Set when disabled (retired, not deleted); null means active. */
    disabled_at?: string | null
    disabled_by?: number | null
    disabled_reason?: string
}

export interface ZevInput {
    name: string
    start_date: string
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

export interface ZevWizardInput extends ZevInput {
    owner: ZevOwnerInput
    metering_points: OwnerMeteringPointInput[]
}

export interface RegisterInput {
    email: string
}

/** spec 2026-09-two-factor-authentication.md §4.1 — never carries the secret. */
export interface TotpDevice {
    id: string
    confirmed_at: string | null
    created_at: string
}

/** A registered WebAuthn credential (passkey). `credential_id` and
 * `public_key` are never sent to the client. */
export interface Passkey {
    id: string
    name: string
    aaguid: string
    transports: string[]
    created_at: string
    last_used_at: string | null
}

export interface MfaStatus {
    totp: TotpDevice | null
    passkeys: Passkey[]
    recovery_codes_remaining: number
    /** Whether AppSettings.mfa_required is on. */
    required: boolean
    /** ISO datetime after which enrolment is no longer optional; null when
     * no policy applies or the user already has a factor. */
    grace_until: string | null
}

/** POST /auth/me/passkeys/register/complete/ — `recovery_codes` is non-empty
 * only when this passkey is the account's first factor. */
export interface PasskeyRegistration {
    passkey: Passkey
    recovery_codes: string[]
}

/** Result of DELETE /auth/users/<id>/mfa/: what the admin's reset removed. */
export interface MfaResetResult {
    removed: { totp: number; passkeys: number; recovery_codes: number }
}

export interface TotpEnrolment {
    provisioning_uri: string
    /** Plain text, once — the user must be able to type it into an
     * authenticator that cannot scan a QR code. */
    secret: string
    qr_svg: string
}

/** POST /auth/token/ returns this instead of setting cookies when the
 * account has an active second factor. */
export interface MfaChallenge {
    mfa_required: true
    mfa_token: string
    methods: ('totp' | 'recovery_code')[]
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
    /** Spec 2026-09-two-factor-authentication.md §5.4 door 4: refuse login
     * unless the provider's userinfo response names an MFA method in its
     * amr claim. Opt-in; the IdP already owns authentication otherwise. */
    require_mfa_claim: boolean
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
    require_mfa_claim: boolean
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
    bank_iban?: string
    bank_name?: string
    owner_address_line1?: string
    owner_address_line2?: string
    owner_postal_code?: string
    owner_city?: string
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
export interface BuildingFootprint {
    type: 'Polygon' | 'MultiPolygon'
    coordinates: number[][][] | number[][][][]
}

export type ParticipantOnboardingStatus = 'not_sent' | 'sent' | 'active' | 'revoked' | 'expired'

/** Whether a party is a person or an organisation (#761). */
export type PartyKind = 'person' | 'organisation'

/** A role a party holds in a ZEV for a dated window (#761). */
export type PartyRoleName = 'issuer' | 'representative' | 'landowner'

/** One of a party's roles as listed on the party or its participations (active today or later). */
export interface PartyRoleWindow {
    id: string
    role: PartyRoleName
    valid_from: string
    valid_to: string | null
}

/** GET /zev/parties/ — a person or organisation of a ZEV (#761, ADR 0028). */
export interface Party {
    id: string
    zev: string
    kind: PartyKind
    title: 'mr' | 'mrs' | 'ms' | 'dr' | 'prof' | ''
    first_name: string
    last_name: string
    organisation_name: string
    name_addition: string
    email: string
    phone: string
    address_line1: string
    address_line2: string
    postal_code: string
    city: string
    notes: string
    display_name: string
    participations: { id: string; valid_from: string; valid_to: string | null }[]
    roles: PartyRoleWindow[]
    /** The party's logins (its own, then its participations'); as issuer or representative each manages the ZEV. */
    accounts: { id: number; email: string; full_name: string; is_active: boolean }[]
    created_at: string
    updated_at: string
}

/** The editable fields of a party (POST/PATCH /zev/parties/). */
export type PartyInput = Pick<Party,
    'kind' | 'title' | 'first_name' | 'last_name' | 'organisation_name' | 'name_addition'
    | 'email' | 'phone' | 'address_line1' | 'address_line2' | 'postal_code' | 'city' | 'notes'>

/** GET /zev/party-roles/ — the issuer, representative and landowners of a ZEV, and since when. */
export interface ZevPartyRole {
    id: string
    zev: string
    party: string
    party_display_name: string
    role: PartyRoleName
    valid_from: string
    valid_to: string | null
    /** The building a landowner owns (#890); null is "not specified" and for other roles. */
    building: string | null
    building_name: string | null
    created_at: string
    updated_at: string
}

/** A site of a ZEV: where its metering points are (#890). */
export interface Building {
    id: string
    zev: string
    name: string
    address_line1: string
    address_line2: string
    postal_code: string
    city: string
    egid: number | null
    notes: string
    metering_point_count: number
    /** Cached OSM outline of the building, for the participants map (null: not located). */
    building_footprint: BuildingFootprint | null
    /** Participants with an assignment active today on the building's meters. */
    current_participants: { id: string; display_name: string }[]
    created_at: string
    updated_at: string
}

export type BuildingInput = Pick<
    Building,
    'zev' | 'name' | 'address_line1' | 'address_line2' | 'postal_code' | 'city' | 'egid' | 'notes'
>

export interface Participant {
    id: string
    zev: string
    user: number | null
    account_username?: string | null
    onboarding_status?: ParticipantOnboardingStatus
    /** ISO datetime of the latest non-revoked onboarding link, even when expired; null when never sent or revoked. */
    onboarding_link_expires_at?: string | null
    /** The participant's party (#761, ADR 0028): names, contact data and address are the party's and shared by every participation of it. */
    party?: string
    kind?: PartyKind
    /** The name the participant is billed under: the organisation's name, or the person's. */
    display_name?: string
    full_name?: string
    organisation_name?: string
    /** Second name line: another household member, "c/o …". */
    name_addition?: string
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
    /** The party's roles active today or later. */
    roles?: PartyRoleWindow[]
    allocation_weight: string
}

export interface ParticipantOnboardingLinkResult {
    onboarding_url: string
    /** ISO datetime when the link in onboarding_url expires (always a live link). */
    onboarding_expires_at: string
    participant: Participant
}

export interface SendOnboardingLinkResult {
    detail: string
    onboarding_url: string
    /** ISO datetime when the link in onboarding_url expires (always a live link). */
    onboarding_expires_at: string
}

export interface ParticipantInput {
    zev: string
    /** On create: attach to this existing party (a second participation); its name and address are then kept. */
    party?: string
    kind?: PartyKind
    organisation_name?: string
    name_addition?: string
    title?: 'mr' | 'mrs' | 'ms' | 'dr' | 'prof' | ''
    first_name?: string
    last_name?: string
    email?: string
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
    building: string
    building_name: string
    /** PV (or other generation) sits behind this meter: it records only the
     * surplus fed in and the residual grid draw (net / surplus metering). */
    has_behind_meter_generation: boolean
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
    /** Omitted: the ZEV's only building (the backend asks for a choice when it has several). */
    building?: string
    has_behind_meter_generation?: boolean
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

export interface DynamicPriceSummary {
    status: 'complete' | 'partial' | 'unavailable'
    average_chf_per_kwh: string | null
    reference_from: string | null
    reference_to: string | null
}

export interface Tariff {
    id: string
    zev: string
    name: string
    category: 'energy' | 'grid_fees' | 'levies' | 'metering'
    billing_mode: TariffBillingMode
    energy_type?: 'local' | 'grid' | 'feed_in' | null
    fixed_price_chf?: string | null
    split_key: 'equal' | 'weight'
    valid_from: string
    valid_to?: string | null
    notes?: string
    /** Written by the Art. 7b importer; blank for tariffs entered by hand. */
    source_component?: 'base' | 'energy' | ''
    source_series_name?: string
    /** Set when this tariff is priced from a fetched series instead of bands. */
    dynamic_source?: string | null
    /** Floor under a fetched series: the greater of this and the fetched price is billed. Feed-in only. */
    minimum_price_chf_per_kwh?: string | null
    /** Bounded, duration-weighted display summary for the fetched series. */
    dynamic_price_summary?: DynamicPriceSummary | null
    /** Shared document/display grid base at today clamped to this version's validity. */
    percentage_base_summary?: {
        price_chf_per_kwh: string | null
        dynamic_status: 'complete' | 'partial' | 'unavailable' | null
        reference_date: string
    } | null
}

export interface TariffInput {
    zev: string
    name: string
    category: 'energy' | 'grid_fees' | 'levies' | 'metering'
    billing_mode: TariffBillingMode
    energy_type?: 'local' | 'grid' | 'feed_in' | null
    fixed_price_chf?: string | null
    /**
     * Create-only, percentage-of-energy mode only: creates one flat band in
     * the same request. Ignored (and rejected) on update — bands are managed
     * from the tariff's own drawer once it exists.
     */
    initial_percentage?: string | null
    split_key?: 'equal' | 'weight'
    valid_from: string
    valid_to?: string | null
    notes?: string
    dynamic_source?: string | null
    minimum_price_chf_per_kwh?: string | null
}

/**
 * The VSE tariff types a dynamic price source can be fetched as. `integrated`
 * already combines `electricity` + `grid` — billing it beside a separate grid
 * fee or levy tariff double-counts, see `docs/specs/2026-09-dynamic-tariffs.md` §3.3.
 */
export type DynamicTariffType =
    | 'electricity' | 'grid' | 'metering' | 'national_fees' | 'regional_fees'
    | 'dso' | 'dso_complete' | 'integrated' | 'integrated_complete' | 'feed_in' | 'refund'

export type DynamicApiVersion = 'v1_0_5' | 'v2_0_0' | 'bfe_rmp'

/** The technology column a BFE reference-market-price source reads. */
export type BfeRmpTechnology = 'pv' | 'wasserkraft' | 'windenergie' | 'biomasse'

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
    enabled: boolean
    last_fetch_status: 'pending' | 'ok' | 'failed'
    last_fetch_at: string | null
    last_success_at: string | null
    last_fetch_error: string
    /** Extent of the stored series; null before anything has been fetched. */
    covers_from: string | null
    covers_to: string | null
    /** Earliest range that a prior refresh could not fetch or store. */
    recovery_from?: string | null
    point_count: number
    linked_tariff_count: number
    linked_zev_count: number
    supports_backfill: boolean
    empty_on_not_found: boolean
    /** Leaf components this source's type already bundles (server-computed per API version). */
    aggregated_tariff_types: DynamicTariffType[]
    created_at: string
    updated_at: string
}

export interface DynamicTariffSourceInput {
    label: string
    url: string
    api_version: DynamicApiVersion
    tariff_type: DynamicTariffType
    tariff_name?: string
    enabled?: boolean
}

export interface DynamicSourceDiscovery {
    api_version: DynamicApiVersion
    version_detected: boolean
    components_discovered: boolean
    components: Array<{
        tariff_type: DynamicTariffType
        tariff_name: string
        aggregated_tariff_types: DynamicTariffType[]
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
    /** Required on a band of an energy tariff; null on a percentage tariff. */
    price_chf_per_kwh: string | null
    /** Required on a band of a percentage-of-energy tariff; null otherwise. */
    percentage?: string | null
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
    minimum_price_chf_per_kwh?: string | null
    periods?: Array<Omit<TariffPeriodInput, 'tariff'>>
}

export interface TariffPeriodInput {
    tariff: string
    period_type: TariffPeriodType
    label?: string
    price_chf_per_kwh?: string | null
    percentage?: string | null
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
    sent_at?: string | null
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
    /** Advisory too: without an issuer today, or with its address incomplete,
     * invoices carry no QR bill. */
    issuer_complete: boolean
    issuer_missing: 'issuer' | 'address' | null
    issuer_link: string | null
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
    source: 'api' | 'api_key' | 'invoice_link' | 'onboarding_link' | 'celery' | 'system' | 'management_command' | 'mcp'
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

/** Zone offset-less import timestamps are read in (ADR 0026). */
export type ImportTimestampTimezone = 'Europe/Zurich' | 'UTC'

export interface ImportLog {
    id: string
    batch_id?: string
    zev?: string
    zev_name?: string | null
    imported_by?: number | null
    imported_by_display?: string | null
    filename: string
    rows_total?: number
    rows_imported: number
    rows_overwritten: number
    rows_skipped: number
    source: string
    errors?: Array<{ row: number | null; error: string; meter_id?: string | null }>
    warnings?: Array<{ row: number | null; warning: string }>
    /** '' for batches imported before ADR 0026 (offset-less values read as UTC). */
    timestamp_timezone?: ImportTimestampTimezone | ''
    created_at: string
}

export interface ImportDeletionResult {
    deleted_logs: number
    deleted_readings: number
    mode?: 'all' | 'period'
    timezone?: 'Europe/Zurich'
}

export interface ImportPreviewRow {
    row: number
    meter_id: string | null
    metering_point_exists: boolean
    meter_type?: string | null
    timestamp?: string | null
    energy?: string | null
    existing_data?: boolean
    /** Reading directions this row would import ('in' / 'out'). */
    directions?: string[]
    interval_minutes?: number
    values_count?: number
}

/** Import settings the backend suggests from a CSV/Excel file's content. */
export interface CsvDetectResult {
    /** False when the file cannot be mapped without manual settings. */
    detected: boolean
    /** Settings that could not be determined (`meter_id`, `timestamp`, `energy_kwh`, `timestamp_format`, `file`). */
    undetected: string[]
    settings: {
        has_header: boolean
        delimiter: string
        format_profile: 'standard' | 'daily_15min'
        timestamp_format: string
        timestamp_timezone: ImportTimestampTimezone
        interval_minutes: number
        values_count: number
        column_map: {
            meter_id: string | null
            timestamp: string | null
            energy_kwh: string | null
            direction: string | null
            energy_start: string | null
        }
    }
}

export interface ImportPreviewResult {
    rows_total: number
    preview_rows: ImportPreviewRow[]
    summary: {
        existing_metering_points: number
        missing_metering_points: number
        rows_previewed: number
        rows_skipped_existing: number
        readings_existing: number
    }
    missing_meter_ids: string[]
    errors: Array<{ row: number | null; error: string }>
    timestamp_timezone: ImportTimestampTimezone
    /** Zero-energy rows at a time that does not exist in Swiss time (DST start); skipped, not errors. */
    rows_skipped_dst_gap: number
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

export interface TemplateField {
    variable: string
    description_key: string
    /** Example value resolved from the backend sample context, when one exists. */
    example: string | null
}

export interface TemplateFieldGroup {
    group_key: string
    group_title_key: string | null
    fields: TemplateField[]
}

export interface PdfTemplateResponse {
    template_name: string
    content: string
    is_customized: boolean
    is_stale?: boolean
    detail?: string
    fields: TemplateFieldGroup[]
}

/** Template mutations return the saved state; the field catalog remains unchanged. */
export type PdfTemplateMutationResponse = Omit<PdfTemplateResponse, 'fields'> & { detail: string }

export interface EmailTemplateResponse {
    template_key: string
    subject: string
    body: string
    is_customized: boolean
    detail?: string
    fields: TemplateFieldGroup[]
}

export type EmailTemplateMutationResponse = Omit<EmailTemplateResponse, 'fields'> & { detail: string }

export interface ZevOwnerDashboardSummary {
    summary_kind: 'zev'
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
        /** Personally holds a metering point with generation behind it for at least one reading in the window: no self-sufficiency rate is shown for this participant. */
        has_behind_meter_generation: boolean
    }>
    /** Any metering point with readings in this window is flagged (has generation behind it). */
    zev_has_behind_meter_generation: boolean
}

export interface ParticipantDashboardSummary {
    summary_kind: 'participant'
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
        has_behind_meter_generation: boolean
    }>
    current_participant_id: string | null
    /** The current participant is net-metered (personally holds a flagged meter) in this window. */
    has_behind_meter_generation: boolean
    /** Any metering point with readings in this window is flagged. */
    zev_has_behind_meter_generation: boolean
}

export type MeteringDashboardSummary = ZevOwnerDashboardSummary | ParticipantDashboardSummary

/** A ZEV's energy balance over a period, with the two rates derived from it. Rates are percentages (one decimal), null when undefined. */
export interface AnnualReportBalance {
    produced_kwh: number
    consumed_kwh: number
    imported_kwh: number
    exported_kwh: number
    self_consumed_kwh: number
    self_consumption_rate: number | null
    self_sufficiency_rate: number | null
}

export interface AnnualReportMonth extends AnnualReportBalance {
    /** Calendar month, 1–12. */
    month: number
    previous_self_consumption_rate: number | null
    previous_self_sufficiency_rate: number | null
}

/** Same shape and strings as the annual statement's savings box. */
export interface AnnualReportSavings {
    local_kwh: string
    local_chf: string
    local_rp: string
    grid_rp: string
    hypothetical_chf: string
    saved_chf: string
}

export interface AnnualReportParticipant {
    participant_id: string
    participant_name: string
    consumed_kwh: number
    produced_kwh: number
    from_zev_kwh: number
    from_grid_kwh: number
    self_sufficiency_rate: number | null
    /** Personally holds a metering point with generation behind it for at least one reading in the year: `self_sufficiency_rate` is null. */
    has_behind_meter_generation: boolean
    savings: AnnualReportSavings | null
}

export interface AnnualReport {
    zev_id: string
    year: number
    has_data: boolean
    /** Any metering point with generation behind it had readings in the year. */
    has_behind_meter_generation: boolean
    totals: AnnualReportBalance
    previous_totals: AnnualReportBalance | null
    /** Always twelve entries, January first. */
    months: AnnualReportMonth[]
    participants: AnnualReportParticipant[]
    savings_total_chf: string | null
}

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
    dynamic_tariff_name?: string
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
        dynamic_source_warnings: string[]
    }>
    skipped: Array<{ name: string; reason: string }>
    errors: Array<{ name: string; error: string }>
}

export type TransferSectionName = 'zev' | 'participants' | 'metering_points' | 'tariffs' | 'readings' | 'invoices' | 'invoice_pdfs'

export interface ZevArchiveImportResult {
    zev_id: string
    zev_name: string
    sections: TransferSectionName[]
    counts: Record<string, number>
    warnings: string[]
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

// ── Backups (SPEC-2026-09-backup-and-restore) ────────────────────────────────

export type BackupDestinationKind = 'local' | 's3'
/** Where an S3 destination's credentials come from, in order of precedence. */
export type BackupCredentialMode = 'environment' | 'stored' | 'instance_role'
export type BackupJobScope = 'instance' | 'zev'
export type BackupJobTrigger = 'manual' | 'scheduled' | 'pre_restore'
export type BackupJobStatus = 'queued' | 'running' | 'completed' | 'failed'

export interface BackupDestination {
    id: string
    name: string
    kind: BackupDestinationKind
    enabled: boolean
    path: string
    bucket: string
    prefix: string
    region: string
    endpoint_url: string
    access_key_id: string
    /** `''` disables server-side encryption for stores that lack it. */
    server_side_encryption: string
    /** How many backups of each kind to keep here; `0` keeps them all. */
    retention_count: number
    credential_mode: BackupCredentialMode
    /** The secret is never returned; this reports whether one is stored. */
    has_secret_access_key: boolean
    created_at: string
    updated_at: string
}

export interface BackupDestinationInput {
    name: string
    kind: BackupDestinationKind
    enabled: boolean
    path: string
    bucket: string
    prefix: string
    region: string
    endpoint_url: string
    access_key_id: string
    server_side_encryption: string
    retention_count: number
    /** Absent leaves a stored secret untouched; `''` clears it. */
    secret_access_key?: string
}

export interface BackupManifestMedia {
    files: number
    bytes: number
    /** Referenced by the database but absent from storage, so not in the archive. */
    missing: string[]
    unsafe: string[]
}

export interface BackupManifestZev {
    id: string
    name: string
    counts: Record<string, number>
    media: BackupManifestMedia
}

export interface BackupManifest {
    kind: 'backup'
    format_version: number
    created_at: string
    instance_name: string
    openzev_version: string
    scope: BackupJobScope
    zev_id: string | null
    counts: Record<string, number>
    zevs: BackupManifestZev[]
    encryption: { algorithm: string; key_fingerprint: string } | null
}

export interface BackupJob {
    id: string
    scope: BackupJobScope
    zev_id: string | null
    zev_name: string
    trigger: BackupJobTrigger
    destination_id: string | null
    destination_name: string
    status: BackupJobStatus
    created_at: string
    started_at: string | null
    completed_at: string | null
    archive_name: string
    /** An absolute path, or `s3://bucket/key`. */
    archive_location: string
    archive_bytes: number | null
    archive_sha256: string
    encrypted: boolean
    encryption_key_fingerprint: string
    /** Empty until the job completes. */
    manifest_json: BackupManifest | Record<string, never>
    error_message: string
    /** Only a safety backup expires by date. */
    file_expires_at: string | null
    /** The row outlives its file; set once retention, expiry or an administrator removed it. */
    artifact_deleted_at: string | null
    artifact_deleted_reason: '' | 'retention' | 'expired' | 'manual'
    /** A finished backup whose file has not been deleted. */
    artifact_available: boolean
    /** A check of the stored file is running. */
    verifying: boolean
    verified_at: string | null
    /** `null`: never checked. */
    verification_ok: boolean | null
    verification_message: string
}

export interface BackupJobInput {
    scope: BackupJobScope
    zev_id?: string
    destination_id: string
}

export interface BackupStatus {
    /** Whether a usable encryption key is configured (not whether the last archive used it). */
    encrypted: boolean
    /** Whether the server refuses to create unencrypted backups. */
    encryption_required: boolean
    encryption_key_fingerprint: string
    /** Set when a key is configured but unusable, so it is not mistaken for "no key". */
    encryption_key_problem: string
    /** S3 credentials come from the server environment and override any stored ones. */
    environment_credentials: boolean
    destinations_enabled: number
    last_successful: BackupJob | null
    last_failed: BackupJob | null
    age_hours: number | null
    /** The schedule has fallen behind: no backup for twice its interval (or ever). */
    stale: boolean
    schedule_enabled: boolean
    schedule_interval_hours: number | null
}

export type BackupScheduleFrequency = 'daily' | 'weekly'

export interface BackupSchedule {
    enabled: boolean
    frequency: BackupScheduleFrequency
    hour: number
    minute: number
    /** Cron numbering: 0 is Sunday. Only meaningful when weekly. */
    day_of_week: number
    /** The server's time zone, which `hour` and `minute` are in. */
    timezone: string
    interval_hours: number
    last_run_at: string | null
}

export type BackupScheduleInput = Pick<BackupSchedule, 'enabled' | 'frequency' | 'hour' | 'minute' | 'day_of_week'>

// ── Per-ZEV restore (SPEC-2026-09-backup-and-restore §6.6) ───────────────────

export type RestoreConflictKind =
    | 'sent_invoice_deleted'
    | 'sent_invoice_reverted'
    | 'contract_issue_deleted'
    | 'meter_id_owned_by_other_zev'
    | 'referenced_row_missing'
    | 'export_in_progress'
    | 'restore_in_progress'

export interface RestoreConflict {
    kind: RestoreConflictKind
    /** A business identifier or a count line ("and 5 more"), safe to show. */
    detail: string
    /** `true` needs `force`; `false` can never be forced past. */
    overridable: boolean
}

export interface RestorePlanSection {
    /** Rows in the backup. */
    backup: number
    /** Rows now. */
    current: number
    /** The audit trail: never restored, so never replaced. */
    kept: boolean
}

export interface RestorePlan {
    zev: { id: string; name: string; exists_now: boolean; current_name: string }
    backup: { created_at: string; scope: BackupJobScope; instance_name: string; openzev_version: string }
    sections: Record<string, RestorePlanSection>
    accounts: { relink: number; missing: string[] }
    media: { files: number; missing: number }
    conflicts: RestoreConflict[]
    blocked: boolean
    safety_backup_id: string | null
    /** Rows written per model; `null` for a preview. */
    restored: Record<string, number> | null
}

export interface RestoreJob {
    id: string
    target_zev_id: string
    target_zev_name: string
    source_backup_id: string | null
    source_archive_name: string
    source_created_at: string | null
    source_description: string
    dry_run: boolean
    force: boolean
    status: BackupJobStatus
    /** `{}` until the job finishes; the plan, or `{verification_failures}` for a damaged archive. */
    plan_json: RestorePlan | { verification_failures?: string[] } | Record<string, never>
    safety_backup_id: string | null
    created_at: string
    started_at: string | null
    completed_at: string | null
    error_message: string
}

export interface RestoreJobInput {
    source_backup_id: string
    target_zev_id: string
    dry_run: boolean
    force?: boolean
    safety_destination_id?: string
}
