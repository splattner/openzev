import { createElement } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { MyEnergyPage } from '../src/pages/MyEnergyPage'
import { renderWithProviders } from './helpers/render'

vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key }) }))

const access = vi.hoisted(() => ({ isZevScope: true }))
vi.mock('../src/lib/communityAccess', () => ({
    useCommunityAccess: () => ({ isZevScope: access.isZevScope, isParticipantScope: !access.isZevScope }),
    useScopeNote: () => undefined,
}))
vi.mock('../src/lib/auth', () => ({ useAuth: () => ({ user: { memberships: [] } }) }))
vi.mock('../src/lib/managedZev', () => ({
    useManagedZev: () => ({ selectedZevId: 'zev-1', selectedZev: { id: 'zev-1', name: 'Sonnenhof', billing_interval: 'monthly' }, entries: [] }),
}))
vi.mock('../src/lib/useBillingPeriodParams', () => ({
    useBillingPeriodParams: () => ({ period: { from: '2026-10-01', to: '2026-10-31' }, setPeriod: vi.fn(), isReady: true }),
}))
vi.mock('../src/components/ScopeGuard', () => ({ ScopeGuard: () => null }))
vi.mock('../src/components/PageHeader', () => ({
    PageHeader: ({ title, description }: { title: string; description: string }) => createElement('header', null, createElement('h1', null, title), createElement('p', null, description)),
}))

const cleanups: Array<() => void> = []
beforeEach(() => { access.isZevScope = true })
afterEach(() => cleanups.splice(0).forEach((cleanup) => cleanup()))

describe('MyEnergyPage', () => {
    it('is the community\'s Live energy for a manager, viewer or admin, who see all of it', async () => {
        const { container } = await renderWithProviders(createElement(MyEnergyPage), cleanups)

        expect(container.querySelector('h1')!.textContent).toBe('pages.myEnergy.titleCommunity')
        expect(container.querySelector('p')!.textContent).toBe('pages.myEnergy.descriptionCommunity')
    })

    it('is My energy system for a participant, whose own devices it shows', async () => {
        access.isZevScope = false
        const { container } = await renderWithProviders(createElement(MyEnergyPage), cleanups)

        expect(container.querySelector('h1')!.textContent).toBe('pages.myEnergy.title')
        expect(container.querySelector('p')!.textContent).toBe('pages.myEnergy.description')
    })
})
