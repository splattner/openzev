import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { Membership } from '../src/types/api'

// Platform → Accounts: a manager through a role names it on its chip (#761).

vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key }) }))
vi.mock('react-router-dom', () => ({ useNavigate: () => vi.fn() }))
vi.mock('../src/lib/managedZev', () => ({ useManagedZev: () => ({ setSelectedZevId: vi.fn() }) }))

import { AccountMemberships } from '../src/features/accounts/AccountMemberships'

const membership = (zev: string, over: Partial<Membership> = {}): Membership => ({
    zev, zev_name: `ZEV ${zev}`, zev_disabled: false, access: null, participants: [], ...over,
})

const cleanups: (() => void)[] = []
afterEach(() => cleanups.splice(0).forEach((cleanup) => cleanup()))

function render(memberships: Membership[]) {
    const container = document.createElement('div')
    document.body.append(container)
    const root = createRoot(container)
    cleanups.push(() => { act(() => root.unmount()); container.remove() })
    act(() => root.render(createElement(AccountMemberships, { memberships })))
    return [...container.querySelectorAll('.account-membership-kind')].map((node) => node.textContent)
}

describe('AccountMemberships', () => {
    it('names the role a manager holds, and nothing for a grant', () => {
        expect(render([
            membership('a', { access: 'manager', roles: ['issuer'] }),
            membership('b', { access: 'manager', roles: ['representative'] }),
            membership('c', { access: 'manager' }),
            membership('d', { access: 'viewer', roles: [] }),
        ])).toEqual([
            'pages.accounts.membership.manager · pages.accounts.membership.issuer',
            'pages.accounts.membership.manager · pages.accounts.membership.representative',
            'pages.accounts.membership.manager',
            'pages.accounts.membership.viewer',
        ])
    })
})
