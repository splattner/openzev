import { act, createElement, type ReactElement } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { MantineProvider } from '@mantine/core'
import { TariffToolbar } from '../src/features/tariffs/TariffToolbar'
import { waitForCondition } from './helpers/waitForCondition'

// The Valid · Upcoming · All tabs filter the list; the overview PDF's scope is chosen at
// the download (SPEC-2026-08-ui-redesign-pdf-style §15.3, SPEC-2026-09-tariff-overview-pdf §11).

vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key }) }))

const cleanups: (() => void)[] = []
afterEach(() => {
    cleanups.splice(0).forEach((cleanup) => cleanup())
    document.body.innerHTML = ''
})

async function render(element: ReactElement) {
    const container = document.createElement('div')
    document.body.append(container)
    const root = createRoot(container)
    cleanups.push(() => { act(() => root.unmount()); container.remove() })
    await act(async () => root.render(createElement(MantineProvider, null, element)))
    return container
}

const props = {
    validCount: 6, upcomingCount: 0, totalCount: 6, validityFilter: 'valid' as const,
    onValidityFilterChange: vi.fn(), onOpenCreateTariffModal: vi.fn(), onDownloadOverview: vi.fn(),
}

describe('TariffToolbar', () => {
    it('leaves the validity tabs out when All would list the same series', async () => {
        const container = await render(createElement(TariffToolbar, props))
        expect(container.querySelector('.filter-tabs')).toBeNull()
    })

    it('shows the validity tabs when All lists more series', async () => {
        const container = await render(createElement(TariffToolbar, { ...props, totalCount: 7 }))
        expect(container.querySelector('.filter-tabs')).not.toBeNull()
    })

    it('shows Upcoming whenever a version is still to start, even at the valid count', async () => {
        // Next year's prices often arrive as a new version of every series at once.
        const container = await render(createElement(TariffToolbar, { ...props, upcomingCount: 6 }))
        const tabs = [...container.querySelectorAll('.filter-tab')].map((tab) => tab.textContent)
        expect(tabs).toEqual(['pages.tariffs.filters.validOnly 6', 'pages.tariffs.filters.upcoming 6'])
    })

    it('offers the PDF scope as a menu', async () => {
        const onDownloadOverview = vi.fn()
        const container = await render(createElement(TariffToolbar, { ...props, onDownloadOverview }))
        const button = [...container.querySelectorAll('button')]
            .find((candidate) => candidate.textContent?.includes('pages.tariffs.overviewPdf.action'))
        expect(button?.getAttribute('aria-haspopup')).toBe('menu')
        expect(button?.classList.contains('button-compact')).toBe(false)
        await act(async () => button?.click())
        await waitForCondition(() => !!document.querySelector('[role="menuitem"]'), 'overview scope menu')
        const all = [...document.querySelectorAll('[role="menuitem"]')]
            .find((item) => item.textContent?.includes('pages.tariffs.overviewPdf.scope.all')) as HTMLElement | undefined
        await act(async () => all?.click())
        expect(onDownloadOverview).toHaveBeenCalledWith('all')
    })
})
