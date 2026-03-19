import axios from 'axios'
import type {
    AppSettings,
    AppSettingsInput,
    AuthTokens,
    ChartDataPoint,
    RawMeteringDailyRow,
    DashboardStats,
    EmailLog,
    ImpersonationTokens,
    ImportPreviewResult,
    ImportLog,
    Invoice,
    MeteringDashboardSummary,
    MeteringPoint,
    MeteringPointAssignment,
    MeteringPointAssignmentInput,
    MeteringPointInput,
    PaginatedResponse,
    Participant,
    ParticipantAccountCreateResult,
    ParticipantInput,
    PdfTemplateResponse,
    Tariff,
    TariffInput,
    TariffPreset,
    TariffPeriod,
    TariffPeriodInput,
    User,
    UserInput,
    Zev,
    ZevInput,
    ZevWizardInput,
    ZevWizardResult,
} from '../types/api'

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000/api/v1'

export const api = axios.create({
    baseURL: API_BASE_URL,
})

function flattenErrorMessages(data: unknown, prefix = ''): string[] {
    if (data == null) {
        return []
    }

    if (typeof data === 'string') {
        return [prefix ? `${prefix}: ${data}` : data]
    }

    if (Array.isArray(data)) {
        return data.flatMap((entry) => flattenErrorMessages(entry, prefix))
    }

    if (typeof data === 'object') {
        const entries = Object.entries(data as Record<string, unknown>)
        return entries.flatMap(([key, value]) => {
            const nextPrefix = prefix ? `${prefix}.${key}` : key
            return flattenErrorMessages(value, nextPrefix)
        })
    }

    return [prefix ? `${prefix}: ${String(data)}` : String(data)]
}

export function formatApiError(error: unknown, fallbackMessage = 'Request failed.'): string {
    if (!axios.isAxiosError(error)) {
        return fallbackMessage
    }

    const responseData = error.response?.data
    if (!responseData) {
        return error.message || fallbackMessage
    }

    if (typeof responseData === 'string') {
        return responseData
    }

    if (typeof responseData === 'object' && responseData !== null) {
        const detail = (responseData as { detail?: unknown }).detail
        if (typeof detail === 'string' && detail.trim()) {
            return detail
        }
    }

    const flattened = flattenErrorMessages(responseData)
    if (!flattened.length) {
        return fallbackMessage
    }

    const cleaned = flattened
        .map((entry) => entry.replace(/^non_field_errors\.?/i, 'Validation'))
        .map((entry) => entry.replace(/\./g, ' → '))

    return cleaned.join(' | ')
}

api.interceptors.request.use((config) => {
    const accessToken = localStorage.getItem('openzev.access')
    if (accessToken) {
        config.headers.Authorization = `Bearer ${accessToken}`
    }
    return config
})

export async function login(username: string, password: string): Promise<AuthTokens> {
    const { data } = await api.post<AuthTokens>('/auth/token/', { username, password })
    return data
}

export async function fetchMe(): Promise<User> {
    const { data } = await api.get<User>('/auth/me/')
    return data
}

export async function fetchAppSettings(): Promise<AppSettings> {
    const { data } = await api.get<AppSettings>('/auth/app-settings/')
    return data
}

export async function updateAppSettings(payload: AppSettingsInput): Promise<AppSettings> {
    const { data } = await api.patch<AppSettings>('/auth/app-settings/', payload)
    return data
}

export async function fetchUsers(): Promise<PaginatedResponse<User>> {
    const { data } = await api.get<PaginatedResponse<User>>('/auth/users/')
    return data
}

export async function impersonateParticipant(userId: number): Promise<ImpersonationTokens> {
    const { data } = await api.post<ImpersonationTokens>(`/auth/users/${userId}/impersonate/`)
    return data
}

export async function updateUser(userId: number, payload: Partial<UserInput>): Promise<User> {
    const { data } = await api.patch<User>(`/auth/users/${userId}/`, payload)
    return data
}

export async function deleteUser(userId: number): Promise<void> {
    await api.delete(`/auth/users/${userId}/`)
}

export async function updateProfile(payload: Partial<Pick<User, 'email' | 'first_name' | 'last_name' | 'phone'>>): Promise<User> {
    const { data } = await api.patch<User>('/auth/me/', payload)
    return data
}

export async function changePassword(oldPassword: string, newPassword: string): Promise<{ detail: string }> {
    const { data } = await api.post<{ detail: string }>('/auth/me/change-password/', {
        old_password: oldPassword,
        new_password: newPassword,
    })
    return data
}

export async function fetchZevs(): Promise<PaginatedResponse<Zev>> {
    const { data } = await api.get<PaginatedResponse<Zev>>('/zev/zevs/')
    return data
}

export async function fetchParticipants(): Promise<PaginatedResponse<Participant>> {
    const { data } = await api.get<PaginatedResponse<Participant>>('/zev/participants/')
    return data
}

export async function fetchInvoices(): Promise<PaginatedResponse<Invoice>> {
    const { data } = await api.get<PaginatedResponse<Invoice>>('/invoices/invoices/')
    return data
}

export async function fetchInvoice(invoiceId: string): Promise<Invoice> {
    const { data } = await api.get<Invoice>(`/invoices/invoices/${invoiceId}/`)
    return data
}

export async function fetchTariffs(): Promise<PaginatedResponse<Tariff>> {
    const { data } = await api.get<PaginatedResponse<Tariff>>('/tariffs/tariffs/')
    return data
}

export async function fetchTariffPeriods(): Promise<PaginatedResponse<TariffPeriod>> {
    const { data } = await api.get<PaginatedResponse<TariffPeriod>>('/tariffs/periods/')
    return data
}

export async function fetchMeteringPoints(): Promise<PaginatedResponse<MeteringPoint>> {
    const { data } = await api.get<PaginatedResponse<MeteringPoint>>('/zev/metering-points/')
    return data
}

export async function fetchImportLogs(): Promise<PaginatedResponse<ImportLog>> {
    const { data } = await api.get<PaginatedResponse<ImportLog>>('/metering/import-logs/')
    return data
}

export async function createZev(payload: ZevInput): Promise<Zev> {
    const { data } = await api.post<Zev>('/zev/zevs/', payload)
    return data
}

export async function createZevWithOwner(payload: ZevWizardInput): Promise<ZevWizardResult> {
    const { data } = await api.post<ZevWizardResult>('/zev/zevs/create-with-owner/', payload)
    return data
}

export async function updateZev(id: string, payload: Partial<ZevInput>): Promise<Zev> {
    const { data } = await api.patch<Zev>(`/zev/zevs/${id}/`, payload)
    return data
}

export async function deleteZev(id: string): Promise<void> {
    await api.delete(`/zev/zevs/${id}/`)
}

export async function createParticipant(payload: ParticipantInput): Promise<Participant> {
    const { data } = await api.post<Participant>('/zev/participants/', payload)
    return data
}

export async function updateParticipant(id: string, payload: Partial<ParticipantInput>): Promise<Participant> {
    const { data } = await api.patch<Participant>(`/zev/participants/${id}/`, payload)
    return data
}

export async function deleteParticipant(id: string): Promise<void> {
    await api.delete(`/zev/participants/${id}/`)
}

export async function sendParticipantInvitation(id: string): Promise<{ detail: string; username: string; temporary_password: string }> {
    const { data } = await api.post<{ detail: string; username: string; temporary_password: string }>(`/zev/participants/${id}/send-invitation/`)
    return data
}

export async function linkParticipantAccount(participantId: string, userId: number): Promise<Participant> {
    const { data } = await api.post<Participant>(`/zev/participants/${participantId}/link-account/`, { user_id: userId })
    return data
}

export async function unlinkParticipantAccount(participantId: string): Promise<Participant> {
    const { data } = await api.post<Participant>(`/zev/participants/${participantId}/unlink-account/`)
    return data
}

export async function createParticipantAccount(participantId: string, payload: { username?: string; email?: string }): Promise<ParticipantAccountCreateResult> {
    const { data } = await api.post<ParticipantAccountCreateResult>(`/zev/participants/${participantId}/create-account/`, payload)
    return data
}

export async function createTariff(payload: TariffInput): Promise<Tariff> {
    const { data } = await api.post<Tariff>('/tariffs/tariffs/', payload)
    return data
}

export async function updateTariff(id: string, payload: Partial<TariffInput>): Promise<Tariff> {
    const { data } = await api.patch<Tariff>(`/tariffs/tariffs/${id}/`, payload)
    return data
}

export async function deleteTariff(id: string): Promise<void> {
    await api.delete(`/tariffs/tariffs/${id}/`)
}

export async function createTariffPeriod(payload: TariffPeriodInput): Promise<TariffPeriod> {
    const { data } = await api.post<TariffPeriod>('/tariffs/periods/', payload)
    return data
}

export async function updateTariffPeriod(id: string, payload: Partial<TariffPeriodInput>): Promise<TariffPeriod> {
    const { data } = await api.patch<TariffPeriod>(`/tariffs/periods/${id}/`, payload)
    return data
}

export async function deleteTariffPeriod(id: string): Promise<void> {
    await api.delete(`/tariffs/periods/${id}/`)
}

export async function exportTariffs(zevId: string): Promise<TariffPreset[]> {
    const { data } = await api.get<TariffPreset[]>('/tariffs/tariffs/export/', {
        params: { zev_id: zevId },
    })
    return data
}

export async function importTariffs(zevId: string, tariffs: TariffPreset[]): Promise<{ created: number; tariffs: Tariff[] }> {
    const { data } = await api.post<{ created: number; tariffs: Tariff[] }>('/tariffs/tariffs/import/', {
        zev_id: zevId,
        tariffs,
    })
    return data
}

export async function createMeteringPoint(payload: MeteringPointInput): Promise<MeteringPoint> {
    const { data } = await api.post<MeteringPoint>('/zev/metering-points/', payload)
    return data
}

export async function updateMeteringPoint(id: string, payload: Partial<MeteringPointInput>): Promise<MeteringPoint> {
    const { data } = await api.patch<MeteringPoint>(`/zev/metering-points/${id}/`, payload)
    return data
}

export async function deleteMeteringPoint(id: string): Promise<void> {
    await api.delete(`/zev/metering-points/${id}/`)
}

export async function fetchMeteringPointAssignments(meteringPointId?: string): Promise<PaginatedResponse<MeteringPointAssignment>> {
    const params = meteringPointId ? { metering_point: meteringPointId } : {}
    const { data } = await api.get<PaginatedResponse<MeteringPointAssignment>>('/zev/metering-point-assignments/', { params })
    return data
}

export async function createMeteringPointAssignment(payload: MeteringPointAssignmentInput): Promise<MeteringPointAssignment> {
    const { data } = await api.post<MeteringPointAssignment>('/zev/metering-point-assignments/', payload)
    return data
}

export async function updateMeteringPointAssignment(id: string, payload: Partial<MeteringPointAssignmentInput>): Promise<MeteringPointAssignment> {
    const { data } = await api.patch<MeteringPointAssignment>(`/zev/metering-point-assignments/${id}/`, payload)
    return data
}

export async function deleteMeteringPointAssignment(id: string): Promise<void> {
    await api.delete(`/zev/metering-point-assignments/${id}/`)
}

export async function generateInvoice(payload: {
    participant_id: string
    period_start: string
    period_end: string
}): Promise<Invoice> {
    const { data } = await api.post<Invoice>('/invoices/invoices/generate/', payload)
    return data
}

export async function generateInvoicesForZev(payload: {
    zev_id: string
    period_start: string
    period_end: string
}): Promise<Invoice[]> {
    const { data } = await api.post<Invoice[]>('/invoices/invoices/generate-all/', payload)
    return data
}

export async function generateInvoicePdf(invoiceId: string): Promise<{ pdf_url: string }> {
    const { data } = await api.post<{ pdf_url: string }>(`/invoices/invoices/${invoiceId}/generate-pdf/`)
    return data
}

export async function sendInvoiceEmail(invoiceId: string, email?: string): Promise<{ detail: string }> {
    const { data } = await api.post<{ detail: string }>(`/invoices/invoices/${invoiceId}/send-email/`, {
        email,
    })
    return data
}

export async function approveInvoice(invoiceId: string): Promise<Invoice> {
    const { data } = await api.post<Invoice>(`/invoices/invoices/${invoiceId}/approve/`)
    return data
}

export async function markInvoiceSent(invoiceId: string): Promise<Invoice> {
    const { data } = await api.post<Invoice>(`/invoices/invoices/${invoiceId}/mark-sent/`)
    return data
}

export async function markInvoicePaid(invoiceId: string): Promise<Invoice> {
    const { data } = await api.post<Invoice>(`/invoices/invoices/${invoiceId}/mark-paid/`)
    return data
}

export async function cancelInvoice(invoiceId: string): Promise<Invoice> {
    const { data } = await api.post<Invoice>(`/invoices/invoices/${invoiceId}/cancel/`)
    return data
}

export async function deleteInvoice(invoiceId: string): Promise<void> {
    await api.delete(`/invoices/invoices/${invoiceId}/`)
}

export async function uploadMeteringFile(payload: {
    source: 'csv' | 'sdatch'
    zevId?: string
    file: File
    columnMap?: {
        meter_id?: string
        timestamp?: string
        energy_kwh?: string
        direction?: string
        energy_start?: string
    }
    hasHeader?: boolean
    delimiter?: string
    formatProfile?: 'standard' | 'daily_15min'
    timestampFormat?: string
    intervalMinutes?: number
    valuesCount?: number
    overwriteExisting?: boolean
}): Promise<ImportLog> {
    const formData = new FormData()
    if (payload.zevId) {
        formData.append('zev_id', payload.zevId)
    }
    formData.append('file', payload.file)
    if (payload.columnMap && payload.source === 'csv') {
        if (payload.columnMap.meter_id) formData.append('col_meter_id', payload.columnMap.meter_id)
        if (payload.columnMap.timestamp) formData.append('col_timestamp', payload.columnMap.timestamp)
        if (payload.columnMap.energy_kwh) formData.append('col_energy_kwh', payload.columnMap.energy_kwh)
        if (payload.columnMap.direction) formData.append('col_direction', payload.columnMap.direction)
        if (payload.columnMap.energy_start) formData.append('col_energy_start', payload.columnMap.energy_start)
        formData.append('has_header', String(payload.hasHeader ?? true))
        formData.append('delimiter', payload.delimiter ?? ',')
        formData.append('format_profile', payload.formatProfile ?? 'standard')
        if (payload.timestampFormat) formData.append('timestamp_format', payload.timestampFormat)
        if (payload.intervalMinutes != null) formData.append('interval_minutes', String(payload.intervalMinutes))
        if (payload.valuesCount != null) formData.append('values_count', String(payload.valuesCount))
        formData.append('overwrite_existing', String(payload.overwriteExisting ?? false))
    }

    const { data } = await api.post<ImportLog>(
        `/metering/import/${payload.source}/`,
        formData,
        { headers: { 'Content-Type': 'multipart/form-data' } },
    )
    return data
}

export async function previewCsvImport(payload: {
    file: File
    columnMap?: {
        meter_id?: string
        timestamp?: string
        energy_kwh?: string
        direction?: string
        energy_start?: string
    }
    hasHeader?: boolean
    delimiter?: string
    formatProfile?: 'standard' | 'daily_15min'
    timestampFormat?: string
    intervalMinutes?: number
    valuesCount?: number
}): Promise<ImportPreviewResult> {
    const formData = new FormData()
    formData.append('file', payload.file)
    if (payload.columnMap) {
        if (payload.columnMap.meter_id) formData.append('col_meter_id', payload.columnMap.meter_id)
        if (payload.columnMap.timestamp) formData.append('col_timestamp', payload.columnMap.timestamp)
        if (payload.columnMap.energy_kwh) formData.append('col_energy_kwh', payload.columnMap.energy_kwh)
        if (payload.columnMap.direction) formData.append('col_direction', payload.columnMap.direction)
        if (payload.columnMap.energy_start) formData.append('col_energy_start', payload.columnMap.energy_start)
    }
    formData.append('has_header', String(payload.hasHeader ?? true))
    formData.append('delimiter', payload.delimiter ?? ',')
    formData.append('format_profile', payload.formatProfile ?? 'standard')
    if (payload.timestampFormat) formData.append('timestamp_format', payload.timestampFormat)
    if (payload.intervalMinutes != null) formData.append('interval_minutes', String(payload.intervalMinutes))
    if (payload.valuesCount != null) formData.append('values_count', String(payload.valuesCount))

    const { data } = await api.post<ImportPreviewResult>('/metering/import/preview-csv/', formData, {
        headers: { 'Content-Type': 'multipart/form-data' },
    })
    return data
}

export async function fetchEmailLogs(invoiceId: string): Promise<EmailLog[]> {
    const { data } = await api.get<{ email_logs: EmailLog[] }>(`/invoices/invoices/${invoiceId}/`)
    return data.email_logs || []
}

export async function retryFailedEmail(invoiceId: string, emailLogId: string): Promise<{ detail: string }> {
    const { data } = await api.post<{ detail: string }>(`/invoices/invoices/${invoiceId}/retry-email/${emailLogId}/`)
    return data
}

export async function fetchDashboardStats(): Promise<DashboardStats> {
    const { data } = await api.get<DashboardStats>(`/invoices/invoices/dashboard/`)
    return data
}

export async function fetchInvoicePdfTemplate(): Promise<PdfTemplateResponse> {
    const { data } = await api.get<PdfTemplateResponse>('/invoices/invoices/pdf-template/')
    return data
}

export async function updateInvoicePdfTemplate(content: string): Promise<PdfTemplateResponse> {
    const { data } = await api.patch<PdfTemplateResponse>('/invoices/invoices/pdf-template/', { content })
    return data
}

export async function fetchChartData(params: {
    meteringPoint: string
    dateFrom?: string
    dateTo?: string
    bucket?: 'day' | 'hour' | 'month'
}): Promise<ChartDataPoint[]> {
    const { data } = await api.get<ChartDataPoint[]>('/metering/readings/chart-data/', {
        params: {
            metering_point: params.meteringPoint,
            date_from: params.dateFrom,
            date_to: params.dateTo,
            bucket: params.bucket ?? 'day',
        },
    })
    return data
}

export async function fetchRawMeteringData(params: {
    meteringPoint: string
    dateFrom?: string
    dateTo?: string
}): Promise<RawMeteringDailyRow[]> {
    const { data } = await api.get<RawMeteringDailyRow[]>('/metering/readings/raw-data/', {
        params: {
            metering_point: params.meteringPoint,
            date_from: params.dateFrom,
            date_to: params.dateTo,
        },
    })
    return data
}

export async function fetchMeteringDashboardSummary(params?: {
    dateFrom?: string
    dateTo?: string
    bucket?: 'day' | 'hour' | 'month'
    zevId?: string
    participantId?: string
}): Promise<MeteringDashboardSummary> {
    const { data } = await api.get<MeteringDashboardSummary>('/metering/readings/dashboard-summary/', {
        params: {
            date_from: params?.dateFrom,
            date_to: params?.dateTo,
            bucket: params?.bucket ?? 'day',
            zev_id: params?.zevId,
            participant_id: params?.participantId,
        },
    })
    return data
}

export { API_BASE_URL }
