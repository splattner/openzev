import { act, createElement, type ReactElement } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { MantineProvider } from '@mantine/core'
import { TariffToolbar } from '../src/features/tariffs/TariffToolbar'

// The Valid · All tabs filter the list; the overview PDF's scope is chosen at
// the download (SPEC-2026-08-ui-redesign-pdf-style §15.3, SPEC-2026-09-tariff-overview-pdf §11).

vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key }) }))

const cleanups: (() => void)[] = []
afterEach(() => cleanups.splice(0).forEach((cleanup) => cleanup()))

async function render(element: ReactElement) {
    const container = document.createElement('div')
    document.body.append(container)
    const root = createRoot(container)
    cleanups.push(() => { act(() => root.unmount()); container.remove() })
    await act(async () => root.render(createElement(MantineProvider, null, element)))
    return container
}

const props = {
    validCount: 6, totalCount: 6, hasOutOfForceVersions: false, validityFilter: 'valid' as const,
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

    it('downloads the valid tariffs from a plain button when every version is in force', async () => {
        const onDownloadOverview = vi.fn()
        const container = await render(createElement(TariffToolbar, { ...props, onDownloadOverview }))
        const button = [...container.querySelectorAll('button')]
            .find((candidate) => candidate.textContent?.includes('pages.tariffs.overviewPdf.action'))
        expect(button?.getAttribute('aria-haspopup')).toBeNull()
        act(() => button?.click())
        expect(onDownloadOverview).toHaveBeenCalledWith('valid')
    })

    it('offers the PDF scope as a menu while a version is out of force', async () => {
        const container = await render(createElement(TariffToolbar, { ...props, hasOutOfForceVersions: true }))
        const button = [...container.querySelectorAll('button')]
            .find((candidate) => candidate.textContent?.includes('pages.tariffs.overviewPdf.action'))
        expect(button?.getAttribute('aria-haspopup')).toBe('menu')
        expect(button?.classList.contains('button-compact')).toBe(false)
    })
})
