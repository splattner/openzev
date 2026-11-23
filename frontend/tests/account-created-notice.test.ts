import { act, createElement, useState } from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { AccountCreatedNotice, type AccountCreatedNoticeData } from '../src/features/accounts/AccountCreatedNotice'
import { renderWithProviders } from './helpers/render'

vi.mock('react-i18next', () => ({
    useTranslation: () => ({ t: (key: string, options?: Record<string, unknown>) => (options ? `${key}${JSON.stringify(options)}` : key) }),
}))
vi.mock('../src/lib/toast', () => ({ useToast: () => ({ pushToast: vi.fn() }) }))

const cleanups: Array<() => void> = []
afterEach(() => { cleanups.splice(0).forEach((cleanup) => cleanup()) })

/** The admin page's part: it holds the notice and drops it on dismissal. */
function Host({ initial }: { initial: AccountCreatedNoticeData }) {
    const [notice, setNotice] = useState<AccountCreatedNoticeData | null>(initial)
    return notice ? createElement(AccountCreatedNotice, { notice, onDismiss: () => setNotice(null) }) : null
}
const button = (root: ParentNode, label: string) => Array.from(root.querySelectorAll('button')).find((b) => b.textContent?.includes(label))!

describe('AccountCreatedNotice', () => {
    it('shows a generated password once and removes it when the admin has saved it', async () => {
        const { container } = await renderWithProviders(createElement(Host, { initial: { username: 'hmuster', password: 'Kq7-vR2p' } }), cleanups)

        expect(container.textContent).toContain('pages.accounts.createModal.createdTitle')
        expect(container.querySelector('[data-testid="account-created-password"]')!.textContent).toBe('Kq7-vR2p')
        expect(container.querySelector('[role="alert"]')!.textContent).toBe('pages.accounts.createModal.createdMessage{"username":"hmuster"}')

        await act(async () => { button(container, 'secretReveal.dismiss').click() })
        expect(container.textContent).not.toContain('Kq7-vR2p')
    })

    it('only confirms the account when the admin chose no generated password', async () => {
        const { container } = await renderWithProviders(createElement(Host, { initial: { username: 'hmuster' } }), cleanups)

        expect(container.querySelector('[data-testid="account-created-password"]')).toBeNull()
        expect(container.textContent).toContain('pages.accounts.createModal.createdMessageOwnPassword')
        await act(async () => { button(container, 'pages.accounts.createModal.dismiss').click() })
        expect(container.textContent).not.toContain('pages.accounts.createModal.createdMessageOwnPassword')
    })
})
