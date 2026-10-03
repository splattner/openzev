import type { Page } from '@playwright/test'

export const apiErrors = new WeakMap<Page, string[]>()

const currentPeriod: [string, string] = ['2026-10-01', '2026-10-31']
const defaultZev = { id: '42', name: 'Review ZEV' }
export type ApiState = {
  role?: 'admin' | 'manager' | 'viewer' | 'participant' | 'former' | 'none'
  zevs?: Array<{ id: string; name: string; disabled_at?: string | null }>
  membershipIds?: string[]
  preferred?: string | null
  expectedScope?: string
  transitionScope?: string
  scopeFailed?: boolean
  scopeEmpty?: boolean
  qualityEmpty?: boolean
  qualityPeriod?: [string, string]
  populated?: boolean
  endpoint?: string
  failed?: boolean
  pending?: Promise<void>
  pendingScope?: string
  onPending?: () => void
  year?: number
}

export async function mockApi(page: Page, state: ApiState = {}) {
  const errors: string[] = []
  apiErrors.set(page, errors)
  const expectedFailures = new Set<string>()
  page.on('pageerror', error => errors.push(error.message))
  page.on('requestfailed', request => errors.push(`${request.method()} ${request.url()}: ${request.failure()?.errorText}`))
  page.on('console', message => {
    if (message.type() === 'error' && !(expectedFailures.has(message.location().url) && message.text().includes('Failed to load resource'))) {
      errors.push(message.text())
    }
  })
  await page.clock.setFixedTime(new Date('2026-10-02T12:00:00Z'))
  await page.addInitScript(() => localStorage.setItem('openzev.language', 'en'))
  const zevs = () => state.scopeEmpty ? [] : state.zevs ?? [defaultZev]
  const user = () => ({
    id: 1, role: !state.role || state.role === 'admin' ? 'admin' : 'user',
    username: 'review', email: 'review@example.test', first_name: 'Review', last_name: 'User',
    must_change_password: false, preferred_zev: state.preferred ?? null, may_create_zev: false,
    memberships: state.role === 'none' ? [] : zevs()
      .filter(zev => !state.membershipIds || state.membershipIds.includes(zev.id))
      .map(zev => ({
        zev: zev.id, zev_name: zev.name, zev_disabled: !!zev.disabled_at,
        access: ['participant', 'former'].includes(state.role ?? '') ? null : state.role === 'viewer' ? 'viewer' : 'manager',
        participants: ['participant', 'former'].includes(state.role ?? '')
          ? [{ id: `p${zev.id}`, valid_from: '2026-01-01', valid_to: state.role === 'former' ? '2026-09-30' : null, live: state.role !== 'former' }]
          : [],
      })),
  })
  await page.route('**/api/v1/**', async route => {
    const request = route.request()
    const url = new URL(request.url())
    const path = url.pathname
    const params = url.searchParams
    const failure = (message: string) => {
      errors.push(message)
      return route.fulfill({ status: 501, json: { detail: message } })
    }
    if (path.endsWith('/auth/me/') && request.method() === 'PATCH') {
      const preferred = request.postDataJSON().preferred_zev
      if (!zevs().some(zev => zev.id === preferred)) return failure(`Invalid selection: ${preferred}`)
      state.preferred = preferred
      return route.fulfill({ json: user() })
    }
    if (request.method() !== 'GET') return failure(`Unexpected API request: ${request.method()} ${path}`)
    const selectedId = state.expectedScope ?? (state.preferred && zevs().some(zev => zev.id === state.preferred) ? state.preferred : zevs()[0]?.id)
    const scope = params.get('zev_id')
    const isManagement = !['participant', 'former', 'none'].includes(state.role ?? 'admin')
    // Only removal scenarios allow an old-scope request during reconciliation.
    if (scope && scope !== selectedId && scope !== state.transitionScope) return failure(`Wrong scope for ${path}: ${scope}, expected ${selectedId}`)
    const requiredScope = ['/dashboard-summary/', '/hourly-profile/', '/data-quality-status/', '/annual-report/', '/invoices/invoices/', '/invoices/invoices/period-overview/', '/readiness/', '/attention/']
    if (isManagement && requiredScope.some(endpoint => path.endsWith(endpoint)) && !scope) {
      return failure(`Missing scope for ${path}`)
    }
    // Point/participant lists and platform endpoints may be unscoped. Chart requests may select a meter instead of a ZEV.
    const dated = ['/dashboard-summary/', '/hourly-profile/', '/data-quality-status/', '/chart-data/'].some(endpoint => path.endsWith(endpoint))
    const periodOverview = path.endsWith('/invoices/invoices/period-overview/')
    for (const key of dated ? ['date_from', 'date_to'] : periodOverview ? ['period_start', 'period_end'] : []) {
      if (!params.has(key)) return failure(`Missing ${key} for ${path}`)
    }
    // Charts open the current month; meter health uses a rolling window.
    const [dateFrom, dateTo] = path.endsWith('/data-quality-status/')
      ? state.qualityPeriod ?? currentPeriod
      : currentPeriod
    for (const [key, expected] of Object.entries({ date_from: dateFrom, date_to: dateTo, period_start: '2026-09-01', period_end: '2026-09-30' })) {
      if (params.has(key) && params.get(key) !== expected) return failure(`Wrong ${key} for ${path}: ${params.get(key)}`)
    }
    if (path.endsWith('/annual-report/') && params.get('year') !== String(state.year ?? 2025)) {
      return failure(`Wrong report year: ${params.get('year')}`)
    }
    if (path.endsWith('/auth/me/mfa/')) return route.fulfill({ json: {
      totp_enabled: false, passkeys: [], recovery_codes_remaining: 0, required: false, grace_until: null,
    } })
    if (path.endsWith('/auth/me/')) return route.fulfill({ json: user() })
    if (path.endsWith('/auth/app-settings/')) return route.fulfill({ json: {
      date_format_short: 'dd.MM.yyyy', date_format_long: 'd MMMM yyyy', date_time_format: 'dd.MM.yyyy HH:mm',
      mfa_required: false, mfa_grace_period_days: 14,
    } })
    if (state.endpoint && path.endsWith(state.endpoint)) {
      if (state.pending && (!state.pendingScope || state.pendingScope === scope)) {
        state.onPending?.()
        await state.pending
      }
      if (state.failed) {
        expectedFailures.add(request.url())
        return route.fulfill({ status: 500, json: { detail: 'Test failure' } })
      }
    }
    if (path.endsWith('/zev/zevs/')) {
      if (state.scopeFailed) {
        expectedFailures.add(request.url())
        return route.fulfill({ status: 500, json: { detail: 'Test scope failure' } })
      }
      const results = zevs().map(zev => ({ ...zev, updated_at: '2026-01-01T00:00:00Z', billing_interval: 'monthly', zev_type: 'zev', start_date: '2026-01-01' }))
      return route.fulfill({ json: { count: results.length, next: null, previous: null, results } })
    }
    if (path.endsWith('/dashboard-summary/')) return route.fulfill({ json: {
      summary_kind: state.role === 'participant' ? 'participant' : 'zev', bucket: 'day',
      totals: state.role === 'participant'
        ? { consumed_from_zev_kwh: 35, imported_from_grid_kwh: 15, total_consumed_kwh: 50 }
        : { produced_kwh: 100, consumed_kwh: 80, imported_kwh: 20, exported_kwh: 40 },
      timeline: [], zev_totals: { produced_kwh: 100, consumed_kwh: 80, imported_kwh: 20, exported_kwh: 40 },
      zev_participant_stats: [], participant_stats: [], current_participant_id: null,
    } })
    if (path.endsWith('/data-quality-status/')) return route.fulfill({ json: {
      date_from: dateFrom, date_to: dateTo, metering_points: state.qualityEmpty ? [] : [{
        id: 'mp1', meter_id: 'MP-1', participant_name: 'Review',
        severity: 'red', data_completeness: 0, days_with_data: 0, total_days: 31,
        gaps: [], unassigned_days: 0, unassigned_readings: 0, assignment_overlap: false,
      }],
    } })
    if (path.endsWith('/zev/grid-operators/')) return route.fulfill({ json: {
      source: 'Test', cube: '', licence: '', period: '2026', fetched_on: '2026-01-01', operators: [],
    } })
    if (path.endsWith('/hourly-profile/')) return route.fulfill({ json: { hourly_profile: null } })
    if (path.endsWith('/chart-data/')) return route.fulfill({ json: [] })
    if (path.endsWith('/annual-report/')) return route.fulfill({ json: { has_data: false, year: Number(params.get('year')) } })
    if (path.endsWith('/invoices/invoices/email-template/invoice_email/')) return route.fulfill({ json: {
      template_key: 'invoice_email', subject: 'Invoice {{ invoice_number }}', body: 'Dear participant', is_customized: false, fields: [],
    } })
    if (path.endsWith('/invoices/invoices/readiness/')) return route.fulfill({ json: {
      zev_id: scope, periods: [], period: null, steps: [], next_action: 'none', awaiting_first_period: true,
    } })
    if (path.endsWith('/invoices/invoices/attention/')) return route.fulfill({ json: { zev_id: scope, items: [] } })
    if (['/exports/jobs/', '/tariffs/dynamic-sources/'].some(endpoint => path.endsWith(endpoint))) return route.fulfill({ json: [] })
    if (path.endsWith('/feasibility/enabled/')) return route.fulfill({ json: { enabled: false } })
    if (path.endsWith('/zev/participants/geocoding-enabled/')) return route.fulfill({ json: { enabled: false } })
    const ids = (state.zevs ?? [defaultZev]).map(zev => zev.id)
    const names = new Map(ids.map(id => [id, `Participant ${id === '42' ? 'A' : 'B'}`]))
    const invoice = { id: '1', invoice_number: 'R-1', zev: scope ?? '42', zev_name: 'Review ZEV',
      participant: `p${scope ?? '42'}`, participant_name: names.get(scope ?? '42'),
      period_start: '2026-09-01', period_end: '2026-09-30', status: 'sent', total_chf: '10.00', pdf_url: null,
    }
    if (path.endsWith('/invoices/invoices/1/')) return route.fulfill({ json: invoice })
    if (path.endsWith('/invoices/invoices/period-overview/')) return route.fulfill({ json: {
      rows: state.populated ? [{ participant_id: invoice.participant, participant_name: invoice.participant_name,
        invoice, generation_eligibility: null, metering_data_complete: true,
        metering_points_total: 1, metering_points_with_data: 1, missing_meter_ids: [],
      }] : [],
    } })
    if (path.endsWith('/tariffs/tariffs/series/')) {
      const id = scope ?? '42'
      const name = `Tariff ${id}`
      return route.fulfill({ json: state.populated ? [{ zev: id, name, category: 'energy', billing_mode: 'energy',
        energy_type: 'grid', version_count: 1, active_version_id: 't1', gaps: [], versions: [{
          id: 't1', zev: id, name, category: 'energy', billing_mode: 'energy', energy_type: 'grid',
          valid_from: '2026-01-01', valid_to: null, fixed_price_chf: null, split_key: 'equal', notes: '', periods: [],
        }],
      }] : [] })
    }
    const participants = ids.map((id, index) => ({ id: `p${id}`, zev: id, user: 2 + index, first_name: 'Participant',
      last_name: id === '42' ? 'A' : 'B', email: `p${id}@example.test`, valid_from: '2026-01-01', valid_to: null,
    }))
    const lists: Record<string, unknown[]> = {
      '/zev/participants/': participants,
      '/zev/metering-points/': ids.filter(id => !scope || id === scope).map(id => ({ id: `mp${id}`, zev: id, meter_id: `MP-${id}`, metering_code: `MP-${id}`,
        meter_type: 'consumption', is_active: true, has_behind_meter_generation: false,
        reading_count: 0, assignment_count: 0, first_reading_at: null, last_reading_at: null })),
      '/zev/metering-point-assignments/': [],
      '/invoices/invoices/': [invoice],
      '/metering/import-logs/': [],
      '/auth/users/': [{ ...user(), id: 2, username: 'account@example.test', email: 'account@example.test',
        is_active: true, mfa_methods: [], mfa_compliance: null, last_login: null, date_joined: '2026-01-01T00:00:00Z',
      }],
    }
    const endpoint = Object.keys(lists).find(endpoint => path.endsWith(endpoint))
    if (endpoint) {
      const results = state.populated ? lists[endpoint] : []
      return route.fulfill({ json: { count: results.length, next: null, previous: null, results } })
    }
    return failure(`Unexpected API request: ${request.method()} ${path}`)
  })
  return errors
}
