import { act, createElement, type ReactNode } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { MemoryRouter, Outlet } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MantineProvider } from '@mantine/core'
import { AppRoutes } from '../src/components/AppRoutes'
import type { ZevInput } from '../src/types/api'

const mocks = vi.hoisted(() => ({
    zev: { id: 'z1', name: 'First community', start_date: '2025-01-01', billing_interval: 'monthly' },
    update: vi.fn().mockResolvedValue({}),
}))
vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key }) }))
vi.mock('../src/lib/auth', () => ({ useAuth: () => ({ isAuthenticated: true, user: { role: 'zev_owner' } }) }))
vi.mock('../src/components/Layout', () => ({ Layout: () => createElement(Outlet) }))
vi.mock('../src/lib/managedZev', () => ({
    ManagedZevProvider: ({ children }: { children: ReactNode }) => children,
    useManagedZev: () => ({ selectedZevId: mocks.zev.id, selectedZev: mocks.zev, isLoading: false }),
}))
vi.mock('../src/lib/toast', () => ({ useToast: () => ({ pushToast: vi.fn() }) }))
vi.mock('../src/lib/api/zev', () => ({ updateZev: mocks.update }))
vi.mock('../src/features/zev/ZevExportModal', () => ({ ZevExportModal: () => null }))
vi.mock('../src/pages/AdminAuditLogsPage', () => ({ AuditLogsPage: () => createElement('div', null, 'audit') }))
vi.mock('../src/components/ZevGeneralSettingsFields', () => ({
    ZevGeneralSettingsFields: ({ form, group, onChange }: {
        form: ZevInput; group: string; onChange: (patch: Partial<ZevInput>) => void
    }) => createElement('input', {
        'aria-label': group,
        value: group === 'general' ? form.name : form.bank_iban,
        onChange: (event: { target: { value: string } }) => onChange(
            group === 'general' ? { name: event.target.value } : { bank_iban: event.target.value },
        ),
    }),
}))

const cleanups: (() => void)[] = []
afterEach(() => cleanups.splice(0).forEach((cleanup) => cleanup()))

describe('ZEV settings routed form', () => {
    it('preserves edits from the root through tabs and saves the shared form', async () => {
        const container = document.createElement('div')
        document.body.append(container)
        const root = createRoot(container)
        const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
        cleanups.push(() => { act(() => root.unmount()); client.clear(); container.remove() })
        await act(async () => root.render(createElement(MemoryRouter, { initialEntries: ['/zev-settings'] },
            createElement(QueryClientProvider, { client }, createElement(MantineProvider, null, createElement(AppRoutes))))))
        for (let i = 0; i < 30 && !container.querySelector('input'); i++) {
            await act(async () => { await new Promise((resolve) => setTimeout(resolve, 50)) })
        }
        const input = container.querySelector('input')!
        await act(async () => {
            Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!.call(input, 'Unsaved name')
            input.dispatchEvent(new Event('input', { bubbles: true }))
        })
        const tab = (key: string) => Array.from(container.querySelectorAll<HTMLButtonElement>('[role="tab"]'))
            .find((button) => button.textContent === `pages.zevSettings.tabs.${key}`)!
        await act(async () => tab('billingPayment').click())
        await act(async () => tab('general').click())
        expect(container.querySelector('input')?.value).toBe('Unsaved name')
        await act(async () => tab('billingPayment').click())
        await act(async () => container.querySelector('form')!.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true })))
        expect(mocks.update).toHaveBeenCalledWith('z1', expect.objectContaining({ name: 'Unsaved name' }))
    })
})
