import { act, createElement, type ReactElement } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { MantineProvider } from '@mantine/core'
import { TariffActions } from '../src/features/tariffs/TariffActions'
import { waitForCondition } from './helpers/waitForCondition'

// The list is grouped (Current, Upcoming, History) rather than filtered; the overview PDF's
// scope is chosen at the download (SPEC-2026-10-tariff-split-view §4, SPEC-2026-09-tariff-overview-pdf §11).

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

const props = { onOpenCreateTariff: vi.fn(), onDownloadOverview: vi.fn() }

describe('TariffActions', () => {
    it('offers no validity filter: the overview groups the list instead', async () => {
        const container = await render(createElement(TariffActions, props))
        expect(container.querySelector('.filter-tabs')).toBeNull()
    })

    it('offers the one primary action to a writer and none to a viewer', async () => {
        const writer = await render(createElement(TariffActions, props))
        expect(writer.querySelector('.button-primary')?.textContent).toContain('pages.tariffs.newTariff')
        const viewer = await render(createElement(TariffActions, { ...props, readOnly: true }))
        expect(viewer.querySelector('.button-primary')).toBeNull()
    })

    it('offers the PDF scope as a menu', async () => {
        const onDownloadOverview = vi.fn()
        const container = await render(createElement(TariffActions, { ...props, onDownloadOverview }))
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
