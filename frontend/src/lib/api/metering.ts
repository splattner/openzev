import type {
  ChartDataPoint,
  DataQualityStatusResponse,
  HourlyProfileResponse,
  ImportDeletionResult,
  ImportLog,
  ImportPreviewResult,
  MeteringDashboardSummary,
  RawMeteringDailyRow,
  RawMeteringReading,
} from '../../types/api'
import { api } from './client'
import { fetchAllPages } from './pagination'

export async function fetchImportLogs(): Promise<ImportLog[]> {
  return fetchAllPages<ImportLog>('/metering/import-logs/')
}

export async function deleteImportLog(id: string): Promise<ImportDeletionResult> {
  const { data } = await api.delete<ImportDeletionResult>(`/metering/import-logs/${id}/`)
  return data
}

export async function bulkDeleteImportLogs(payload: {
  mode: 'all' | 'period'
  dateFrom?: string
  dateTo?: string
  zevId?: string
}): Promise<ImportDeletionResult> {
  const { data } = await api.post<ImportDeletionResult>('/metering/import-logs/bulk-delete/', {
    mode: payload.mode,
    date_from: payload.dateFrom,
    date_to: payload.dateTo,
    zev_id: payload.zevId,
  })
  return data
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

/** Compact per-day summary (no individual readings) for the raw-data overview table. */
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

/** Individual readings for a single day, fetched lazily when a day row is expanded. */
export async function fetchRawMeteringDay(params: {
  meteringPoint: string
  date: string
}): Promise<RawMeteringReading[]> {
  const { data } = await api.get<RawMeteringReading[]>('/metering/readings/raw-data/', {
    params: {
      metering_point: params.meteringPoint,
      date: params.date,
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

export async function fetchHourlyProfile(params: {
  dateFrom: string
  dateTo: string
  zevId?: string
  participantId?: string
}): Promise<HourlyProfileResponse> {
  const { data } = await api.get<HourlyProfileResponse>('/metering/readings/hourly-profile/', {
    params: {
      date_from: params.dateFrom,
      date_to: params.dateTo,
      zev_id: params.zevId,
      participant_id: params.participantId,
    },
  })
  return data
}

export async function fetchMeteringDataQualityStatus(params: {
  dateFrom: string
  dateTo: string
  zevId?: string
  meteringPointId?: string
}): Promise<DataQualityStatusResponse> {
  const queryParams = new URLSearchParams({
    date_from: params.dateFrom,
    date_to: params.dateTo,
  })
  if (params.zevId) {
    queryParams.set('zev_id', params.zevId)
  }
  if (params.meteringPointId) {
    queryParams.set('metering_point', params.meteringPointId)
  }

  const { data } = await api.get<DataQualityStatusResponse>(`/metering/readings/data-quality-status/?${queryParams.toString()}`)
  return data
}
