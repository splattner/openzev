import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { AppSettings } from '../src/types/api'
import { MfaPolicySection } from '../src/features/settings/MfaPolicySection'
import { waitForCondition } from './helpers/waitForCondition'

const DATE_FORMATS = {
    date_format_short: 'dd.MM.yyyy',
    date_format_long: 'd. MMMM yyyy',
    date_time_format: 'dd.MM.yyyy HH:mm',
    updated_at: '2026-01-01T00:00:00Z',
} as const

const state = vi.hoisted(() => ({ settings: {} as AppSettings, isError: false }))
const api = vi.hoisted(() => ({ health: vi.fn(), update: vi.fn() }))

vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key }) }))
vi.mock('../src/lib/toast', () => ({ useToast: () => ({ pushToast: vi.fn() }) }))
vi.mock('../src/lib/api/auth', () => ({
    fetchSystemHealth: api.health.mockResolvedValue({ mfa: { status: 'ok', encryption_key_configured: true } }),
    updateAppSettings: api.update,
}))
vi.mock('../src/lib/appSettings', () => ({
    useAppSettings: () => ({ settings: state.settings, isLoading: false, isError: state.isError }),
}))

const cleanups: (() => void)[] = []
afterEach(() => {
    cleanups.splice(0).forEach((cleanup) => cleanup())
    vi.clearAllMocks()
})

function mountSection() {
    const container = document.createElement('div')
    document.body.append(container)
    const root = createRoot(container)
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    cleanups.push(() => { act(() => root.unmount()); client.clear(); container.remove() })
    const renderWith = (settings: AppSettings, isError = false) => {
        state.settings = settings
        state.isError = isError
        return act(async () => root.render(createElement(QueryClientProvider, { client }, createElement(MfaPolicySection))))
    }
    return {
        container,
        renderWith,
        checkbox: () => container.querySelector<HTMLInputElement>('input[type="checkbox"]')!,
        graceDays: () => container.querySelector<HTMLInputElement>('input[type="number"]')!,
        save: () => container.querySelector<HTMLButtonElement>('button[type="submit"]')!,
    }
}

describe('MfaPolicySection', () => {
    it('stays disabled until the policy loads, then shows it', async () => {
        const { container, renderWith, checkbox, graceDays, save } = mountSection()

        await renderWith({ ...DATE_FORMATS })
        expect(container.querySelector('[role="alert"]')).toBeNull()
        expect(checkbox().matches(':disabled')).toBe(true)
        expect(graceDays().value).toBe('')
        expect(graceDays().matches(':disabled')).toBe(true)
        expect(save().matches(':disabled')).toBe(true)

        await renderWith({ ...DATE_FORMATS, mfa_required: true, mfa_grace_period_days: 30 })
        expect(checkbox().checked).toBe(true)
        expect(checkbox().matches(':disabled')).toBe(false)
        expect(graceDays().value).toBe('30')
        expect(graceDays().matches(':disabled')).toBe(false)
        expect(save().matches(':disabled')).toBe(false)
    })

    it('shows a settings fetch error, then hides it after a successful fetch', async () => {
        const { container, renderWith, checkbox, graceDays, save } = mountSection()

        await renderWith({ ...DATE_FORMATS }, true)
        expect(container.querySelector('[role="alert"]')?.textContent).toContain('adminSystemSettings.mfaPolicy.loadError')
        expect(checkbox().matches(':disabled')).toBe(true)
        expect(graceDays().matches(':disabled')).toBe(true)
        expect(save().matches(':disabled')).toBe(true)

        await renderWith({ ...DATE_FORMATS, mfa_required: false, mfa_grace_period_days: 0 }, false)
        expect(container.querySelector('[role="alert"]')).toBeNull()
        expect(checkbox().checked).toBe(false)
        expect(checkbox().matches(':disabled')).toBe(false)
        expect(graceDays().value).toBe('0')
        expect(graceDays().matches(':disabled')).toBe(false)
        expect(save().matches(':disabled')).toBe(false)
    })

    it('preserves and submits a local policy edit after a failed refresh', async () => {
        const { container, renderWith, checkbox, graceDays, save } = mountSection()
        const policy = { ...DATE_FORMATS, mfa_required: true, mfa_grace_period_days: 14 }
        await renderWith(policy)

        act(() => {
            checkbox().click()
            Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!.call(graceDays(), '21')
            graceDays().dispatchEvent(new Event('input', { bubbles: true }))
        })
        expect(checkbox().checked).toBe(false)
        expect(graceDays().value).toBe('21')

        await renderWith(policy, true)

        expect(container.querySelector('[role="alert"]')).toBeNull()
        expect(checkbox().checked).toBe(false)
        expect(checkbox().matches(':disabled')).toBe(false)
        expect(graceDays().value).toBe('21')
        expect(graceDays().matches(':disabled')).toBe(false)
        expect(save().matches(':disabled')).toBe(false)

        api.update.mockResolvedValueOnce({ ...policy, mfa_required: false, mfa_grace_period_days: 21 })
        await act(async () => save().click())
        await waitForCondition(() => api.update.mock.calls.length === 1, 'submitted MFA policy')
        expect(api.update.mock.calls[0][0]).toEqual({ mfa_required: false, mfa_grace_period_days: 21 })
    })

    it('shows a polite missing-key warning and disables the policy controls', async () => {
        api.health.mockResolvedValueOnce({ mfa: { status: 'unconfigured', encryption_key_configured: false } })
        const { container, renderWith, checkbox, graceDays, save } = mountSection()
        await renderWith({ ...DATE_FORMATS, mfa_required: true, mfa_grace_period_days: 14 })
        await waitForCondition(() => container.querySelector('[role="status"]') !== null, 'missing encryption key warning')

        expect(container.querySelector('[role="status"]')?.textContent).toContain('adminSystemSettings.mfaPolicy.keyMissing')
        expect(container.querySelector('.warning-banner')).toBeNull()
        expect(container.querySelector('[role="alert"]')).toBeNull()
        expect(checkbox().matches(':disabled')).toBe(true)
        expect(graceDays().matches(':disabled')).toBe(true)
        expect(save().matches(':disabled')).toBe(true)
    })
})
