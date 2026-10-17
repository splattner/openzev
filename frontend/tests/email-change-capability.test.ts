import { act, createElement } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { beforeEach, afterEach, describe, expect, it, vi } from 'vitest'
import { EmailChangeForm } from '../src/features/account/EmailChangeForm'
import { requestEmailChange } from '../src/lib/api/auth'

const state = vi.hoisted(() => ({ user: {
    email: 'participant@example.com', has_usable_password: true, can_change_email: false,
} }))
vi.mock('../src/lib/auth', () => ({ useAuth: () => ({ user: state.user }) }))
vi.mock('../src/lib/toast', () => ({ useToast: () => ({ pushToast: vi.fn() }) }))
vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key }) }))
vi.mock('../src/lib/api/auth', () => ({ requestEmailChange: vi.fn() }))

let container: HTMLDivElement
let root: Root
beforeEach(() => {
    vi.mocked(requestEmailChange).mockReset()
    container = document.createElement('div')
    document.body.appendChild(container)
    root = createRoot(container)
})
afterEach(async () => {
    await act(async () => root.unmount())
    container.remove()
})
async function render(canChangeEmail: boolean) {
    state.user.can_change_email = canChangeEmail
    await act(async () => root.render(createElement(QueryClientProvider, {
        client: new QueryClient(), children: createElement(EmailChangeForm),
    })))
}
async function fill(selector: string, value: string) {
    const input = container.querySelector<HTMLInputElement>(selector)!
    await act(async () => {
        Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!.call(input, value)
        input.dispatchEvent(new Event('input', { bubbles: true }))
    })
}

describe('email-change capability', () => {
    it('shows read-only guidance for a usable participant password', async () => {
        await render(false)
        expect(container.textContent).toContain('account.emailChange.managed')
        expect(container.querySelector('button')).toBeNull()
    })
    it('offers the form for an independent password', async () => {
        await render(true)
        const button = container.querySelector('button')!
        await act(async () => button.click())
        expect(container.querySelector('form')).not.toBeNull()
        expect(container.textContent).not.toContain('account.emailChange.managed')
    })
    it.each(['no_password', 'managed_email'])('explains a %s refusal after opening the form', async (code) => {
        vi.mocked(requestEmailChange).mockRejectedValue({
            isAxiosError: true, response: { data: { code, detail: 'Raw server detail' } },
        })
        await render(true)
        await act(async () => container.querySelector('button')!.click())
        await fill('form input[type="email"]', 'new@example.com')
        await fill('form input[type="password"]', 'CurrentPassword42!')
        await act(async () => {
            container.querySelector('form')!.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }))
            await new Promise(resolve => setTimeout(resolve, 0))
        })
        expect(requestEmailChange).toHaveBeenCalledWith('new@example.com', 'CurrentPassword42!')
        expect(container.querySelector('.error-banner')?.textContent).toBe('account.emailChange.managed')
        expect(container.textContent).not.toContain('Raw server detail')
    })
})
