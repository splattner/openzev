import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { StrictMode, act, createElement } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { MemoryRouter } from 'react-router-dom'
import {
    confirmEmailChange,
    requestEmailChange,
    revokeOtherSessions,
    revokeUserSessions,
} from '../src/lib/api/auth'
import { api } from '../src/lib/api/client'
import { ConfirmEmailChangePage } from '../src/pages/ConfirmEmailChangePage'

vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key }) }))

describe('account security API calls', () => {
    beforeEach(() => vi.restoreAllMocks())

    it('asks for an email change with the new address and the current password', async () => {
        const post = vi.spyOn(api, 'post').mockResolvedValue({ data: { detail: 'sent' } })
        await requestEmailChange('new@example.org', 'hunter2')
        expect(post).toHaveBeenCalledWith('/auth/me/email-change/', {
            new_email: 'new@example.org',
            current_password: 'hunter2',
        })
    })

    it('confirms an email change with just the token', async () => {
        const post = vi.spyOn(api, 'post').mockResolvedValue({ data: { detail: 'ok' } })
        await confirmEmailChange('signed-token')
        expect(post).toHaveBeenCalledWith('/auth/confirm-email-change/', { token: 'signed-token' })
    })

    it('signs out other sessions without a body, and an admin signs an account out by id', async () => {
        const post = vi.spyOn(api, 'post').mockResolvedValue({ data: { detail: 'ok' } })
        await revokeOtherSessions()
        expect(post).toHaveBeenLastCalledWith('/auth/me/sessions/revoke/')
        await revokeUserSessions(42)
        expect(post).toHaveBeenLastCalledWith('/auth/users/42/revoke-sessions/')
    })
})

describe('ConfirmEmailChangePage', () => {
    let container: HTMLDivElement
    let root: Root

    beforeEach(() => {
        vi.restoreAllMocks()
        container = document.createElement('div')
        document.body.appendChild(container)
        root = createRoot(container)
    })

    afterEach(() => {
        act(() => root.unmount())
        container.remove()
    })

    async function renderAt(url: string) {
        await act(async () => {
            // StrictMode runs effects twice in development — the link is single-use,
            // so the page must not spend it twice.
            root.render(
                createElement(StrictMode, null,
                    createElement(MemoryRouter, { initialEntries: [url] }, createElement(ConfirmEmailChangePage))),
            )
            await new Promise((resolve) => setTimeout(resolve, 0))
        })
    }

    it('spends the link exactly once and points at sign-in on success', async () => {
        const post = vi.spyOn(api, 'post').mockResolvedValue({ data: { detail: 'ok' } })
        await renderAt('/confirm-email-change?token=abc')
        expect(post).toHaveBeenCalledTimes(1)
        expect(post).toHaveBeenCalledWith('/auth/confirm-email-change/', { token: 'abc' })
        expect(container.textContent).toContain('auth.emailChange.successTitle')
        expect(container.querySelector('a[href="/login"]')).not.toBeNull()
    })

    it('shows one generic message for any refusal', async () => {
        vi.spyOn(api, 'post').mockRejectedValue({ response: { status: 400 } })
        await renderAt('/confirm-email-change?token=bad')
        expect(container.textContent).toContain('auth.emailChange.errorTitle')
        expect(container.textContent).not.toContain('auth.emailChange.successTitle')
    })

    it('does not call the server without a token', async () => {
        const post = vi.spyOn(api, 'post').mockResolvedValue({ data: {} })
        await renderAt('/confirm-email-change')
        expect(post).not.toHaveBeenCalled()
        expect(container.textContent).toContain('auth.emailChange.errorTitle')
    })
})
