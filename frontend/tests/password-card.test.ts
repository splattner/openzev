import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { EmailChangeForm } from '../src/features/account/EmailChangeForm'
import { waitForCondition } from './helpers/waitForCondition'
import { PasswordCard } from '../src/features/account/PasswordCard'
import { changePassword, resetPassword, setInitialPassword } from '../src/lib/api/auth'

const state = vi.hoisted(() => ({
    user: { has_usable_password: true, can_change_email: true, password_recovery_expires_at: null as string | null },
    refreshUser: vi.fn(), pushToast: vi.fn(),
}))
vi.mock('../src/lib/auth', () => ({ useAuth: () => state }))
vi.mock('../src/lib/toast', () => ({ useToast: () => state }))
vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key }) }))
vi.mock('../src/lib/api/auth', () => ({ changePassword: vi.fn(), resetPassword: vi.fn(), setInitialPassword: vi.fn(), requestEmailChange: vi.fn() }))

const cleanups: (() => void)[] = []
const rerenders = new WeakMap<HTMLElement, () => void>()
afterEach(() => {
    cleanups.splice(0).forEach((cleanup) => cleanup())
    vi.useRealTimers()
})
beforeEach(() => {
    vi.clearAllMocks()
    state.refreshUser.mockResolvedValue(undefined)
    state.user = { has_usable_password: true, can_change_email: true, password_recovery_expires_at: null }
    vi.mocked(changePassword).mockResolvedValue({ detail: 'ok' })
    vi.mocked(resetPassword).mockResolvedValue()
    vi.mocked(setInitialPassword).mockResolvedValue()
})

function render(component = PasswordCard) {
    const container = document.createElement('div')
    document.body.append(container)
    const root = createRoot(container)
    const client = new QueryClient({ defaultOptions: { mutations: { retry: false } } })
    cleanups.push(() => { act(() => root.unmount()); client.clear(); container.remove() })
    const rerender = () => root.render(createElement(QueryClientProvider, { client }, createElement(component)))
    rerenders.set(container, rerender)
    act(rerender)
    return container
}

async function submit(container: HTMLElement) {
    act(() => {
        for (const input of container.querySelectorAll<HTMLInputElement>('input')) {
            const value = input.name === 'oldPassword' ? 'Current-password42!' : 'Replacement-password42!'
            Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!.call(input, value)
            input.dispatchEvent(new Event('input', { bubbles: true }))
        }
    })
    await act(async () => {
        container.querySelector('form')!.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }))
    })
    await waitForCondition(() => state.pushToast.mock.calls.length > 0, 'password mutation result')
}

function recover(container: HTMLElement) {
    const button = [...container.querySelectorAll('button')].find((b) => b.textContent === 'account.recoverPassword')!
    act(() => button.click())
}

describe('PasswordCard', () => {
    it('sets a first password without asking for an old one and refreshes the user', async () => {
        state.user.has_usable_password = false
        const container = render()
        expect(container.querySelector('input[name="oldPassword"]')).toBeNull()
        await submit(container)
        expect(setInitialPassword).toHaveBeenCalledWith('Replacement-password42!')
        expect(changePassword).not.toHaveBeenCalled()
        expect(state.refreshUser).toHaveBeenCalledOnce()
    })

    it('keeps the current-password form for ordinary changes', async () => {
        const container = render()
        expect(container.querySelector('input[name="oldPassword"]')).not.toBeNull()
        await submit(container)
        expect(changePassword).toHaveBeenCalledWith('Current-password42!', 'Replacement-password42!')
        expect(resetPassword).not.toHaveBeenCalled()
        expect(container.textContent).not.toContain('account.passwordRecoveryHelp')
    })

    it('requires an explicit choice to recover after link sign-in', async () => {
        state.user.password_recovery_expires_at = new Date(Date.now() + 900_000).toISOString()
        const container = render()
        expect(container.querySelector('input[name="oldPassword"]')).not.toBeNull()
        recover(container)
        expect(container.querySelector('input[name="oldPassword"]')).toBeNull()
        await submit(container)
        expect(resetPassword).toHaveBeenCalledWith('Replacement-password42!')
        expect(state.refreshUser).toHaveBeenCalledOnce()
    })

    it('expires recovery while the form is open', () => {
        vi.useFakeTimers()
        state.user.password_recovery_expires_at = new Date(Date.now() + 1000).toISOString()
        const container = render()
        recover(container)
        act(() => vi.advanceTimersByTime(1001))
        expect(container.textContent).toContain('account.passwordRecoveryExpired')
        expect(container.querySelector<HTMLButtonElement>('button[type="submit"]')!.disabled).toBe(true)
        expect(resetPassword).not.toHaveBeenCalled()
    })

    it('keeps entered fields and explains a server-side recovery denial', async () => {
        state.user.password_recovery_expires_at = new Date(Date.now() + 900_000).toISOString()
        vi.mocked(resetPassword).mockRejectedValue({ isAxiosError: true, response: { data: { code: 'password_recovery_required' } } })
        const container = render()
        recover(container)
        await submit(container)
        expect(state.pushToast).toHaveBeenCalledWith('account.passwordRecoveryExpired', 'error')
        expect(state.refreshUser).toHaveBeenCalledOnce()
        expect(container.querySelector<HTMLInputElement>('input[name="newPassword"]')!.value).toBe('Replacement-password42!')
        expect(container.querySelector('input[name="oldPassword"]')).not.toBeNull()
    })

    it('formats password-validator arrays as readable string errors', async () => {
        state.user.password_recovery_expires_at = new Date(Date.now() + 900_000).toISOString()
        vi.mocked(resetPassword).mockRejectedValue({
            isAxiosError: true, response: { data: { detail: ['Too common.', 'Too similar.'] } },
        })
        const container = render()
        recover(container)
        await submit(container)
        const message = state.pushToast.mock.calls[0][0]
        expect(typeof message).toBe('string')
        expect(message).toContain('Too common')
        expect(message).toContain('Too similar')
    })

    it('keeps participant email manager-maintained even with a password', () => {
        state.user.can_change_email = false
        const container = render(EmailChangeForm)
        expect(container.textContent).toContain('account.emailChange.managed')
        expect(container.querySelector('button')).toBeNull()
    })

    it('reports password success separately when refreshing the profile fails', async () => {
        state.user.has_usable_password = false
        state.refreshUser.mockRejectedValueOnce(new Error('Profile unavailable'))
        const container = render()
        await submit(container)
        expect(setInitialPassword).toHaveBeenCalledOnce()
        expect(state.pushToast.mock.calls).toEqual([
            ['account.passwordChangedSuccess', 'success'],
            ['account.profileRefreshFailed', 'info'],
        ])
        expect(container.querySelector<HTMLInputElement>('input[name="newPassword"]')!.value).toBe('')
    })

    it('keeps recovery denial separate from a failed profile refresh', async () => {
        state.user.password_recovery_expires_at = new Date(Date.now() + 900_000).toISOString()
        state.refreshUser.mockRejectedValueOnce(new Error('Profile unavailable'))
        vi.mocked(resetPassword).mockRejectedValue({
            isAxiosError: true, response: { data: { code: 'password_recovery_required' } },
        })
        const container = render()
        recover(container)
        await submit(container)
        expect(state.pushToast.mock.calls).toEqual([
            ['account.passwordRecoveryExpired', 'error'],
            ['account.profileRefreshFailed', 'info'],
        ])
        expect(container.querySelector('input[name="oldPassword"]')).not.toBeNull()
        expect(container.querySelector<HTMLInputElement>('input[name="newPassword"]')!.value).toBe('Replacement-password42!')
    })

    it('returns to ordinary change when recovery permission changes without losing fields', () => {
        vi.useFakeTimers()
        state.user.password_recovery_expires_at = new Date(Date.now() + 900_000).toISOString()
        const container = render()
        recover(container)
        const input = container.querySelector<HTMLInputElement>('input[name="newPassword"]')!
        act(() => {
            Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!.call(input, 'Keep-my-password42!')
            input.dispatchEvent(new Event('input', { bubbles: true }))
        })
        for (const deadline of [null, new Date(Date.now() + 800_000).toISOString()]) {
            state.user.password_recovery_expires_at = deadline
            act(rerenders.get(container)!)
            expect(container.querySelector('input[name="oldPassword"]')).not.toBeNull()
            expect(container.querySelector<HTMLInputElement>('input[name="newPassword"]')!.value).toBe('Keep-my-password42!')
            expect(container.textContent).not.toContain('account.passwordRecoveryActive')
        }
    })

})
