import { act, createElement } from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { AnalyticsPrivacySection } from '../src/features/settings/AnalyticsPrivacySection'
import type { AppSettings } from '../src/types/api'
import { renderWithProviders, setInputValue } from './helpers/render'

const state = vi.hoisted(() => ({ settings: {} as AppSettings }))
const api = vi.hoisted(() => ({ update: vi.fn() }))
const pushToast = vi.fn()

vi.mock('react-i18next', () => ({
    useTranslation: () => ({ t: (key: string, options?: Record<string, unknown>) => (options ? `${key}${JSON.stringify(options)}` : key) }),
}))
vi.mock('../src/lib/toast', () => ({ useToast: () => ({ pushToast }) }))
vi.mock('../src/lib/api/auth', () => ({ updateAppSettings: api.update }))
vi.mock('../src/lib/appSettings', () => ({ useAppSettings: () => ({ settings: state.settings, isLoading: false, isError: false }) }))

const FORMATS = { date_format_short: 'dd.MM.yyyy', date_format_long: 'd. MMMM yyyy', date_time_format: 'dd.MM.yyyy HH:mm', updated_at: '2026-01-01T00:00:00Z' } as const
const withPrivacy = (stored: number | null): AppSettings => ({
    ...FORMATS, analytics_min_participants_for_aggregate: stored, analytics_min_participants_default: 5, analytics_min_participants_floor: 3,
})

const cleanups: Array<() => void> = []
afterEach(() => { cleanups.splice(0).forEach((cleanup) => cleanup()); vi.clearAllMocks() })

async function mount(settings: AppSettings) {
    state.settings = settings
    const view = await renderWithProviders(createElement(AnalyticsPrivacySection), cleanups)
    return {
        ...view,
        input: () => view.container.querySelector<HTMLInputElement>('input[type="number"]')!,
        save: () => view.container.querySelector<HTMLButtonElement>('button[type="submit"]')!,
    }
}

describe('AnalyticsPrivacySection', () => {
    it('shows the platform default as the placeholder when nothing is set, and the floor as the minimum', async () => {
        const { input, container } = await mount(withPrivacy(null))

        expect(input().value).toBe('')
        expect(input().placeholder).toBe('5')
        expect(input().min).toBe('3')
        expect(container.textContent).toContain('"default":5')
    })

    it('shows a stored value', async () => {
        const { input } = await mount(withPrivacy(7))

        expect(input().value).toBe('7')
    })

    it('saves a number', async () => {
        api.update.mockResolvedValue(withPrivacy(4))
        const { input, save } = await mount(withPrivacy(null))

        await act(async () => { setInputValue(input(), '4') })
        await act(async () => { save().click() })

        expect(api.update).toHaveBeenCalledWith({ analytics_min_participants_for_aggregate: 4 })
        expect(pushToast).toHaveBeenCalledWith('adminSystemSettings.analyticsPrivacy.saved', 'success')
    })

    it('clearing the field returns to the platform default', async () => {
        api.update.mockResolvedValue(withPrivacy(null))
        const { input, save } = await mount(withPrivacy(7))

        await act(async () => { setInputValue(input(), '') })
        await act(async () => { save().click() })

        expect(api.update).toHaveBeenCalledWith({ analytics_min_participants_for_aggregate: null })
    })

    it.each(['2', '1', '0', '101', '3.5', '-4'])('refuses %s before it reaches the server', async (typed) => {
        const { input, save, container } = await mount(withPrivacy(null))

        await act(async () => { setInputValue(input(), typed) })

        expect(save().disabled).toBe(true)
        expect(container.querySelector('[role="alert"]')!.textContent).toContain('adminSystemSettings.analyticsPrivacy.invalid')
        await act(async () => { save().click() })
        expect(api.update).not.toHaveBeenCalled()
    })

    it('stays disabled until the admin settings have loaded', async () => {
        const { container } = await mount({ ...FORMATS })

        expect(container.querySelector('fieldset')!.disabled).toBe(true)
    })
})
