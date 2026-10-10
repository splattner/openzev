import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { MemoryRouter } from 'react-router-dom'
import { MantineProvider } from '@mantine/core'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { waitForCondition } from './helpers/waitForCondition'
import type { InvoiceRowFilter } from '../src/features/invoices/invoiceRowFilters'

vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key }) }))

import { InvoiceBatchActions } from '../src/features/invoices/InvoiceBatchActions'
import { InvoiceRowFilterTabs } from '../src/features/invoices/InvoiceRowFilterTabs'

const COUNTS = { all: 9, invoices: 6, drafts: 2, approved: 3, sent: 1, issues: 2, pdfs: 4 }
const cleanups: Array<() => void> = []
afterEach(() => cleanups.splice(0).forEach((cleanup) => cleanup()))
beforeEach(() => vi.clearAllMocks())

function render(element: ReturnType<typeof createElement>) {
    const container = document.createElement('div')
    document.body.append(container)
    const root = createRoot(container)
    act(() => root.render(createElement(MemoryRouter, null, createElement(MantineProvider, null, element))))
    cleanups.push(() => { act(() => root.unmount()); container.remove() })
    return container
}

type ActionProps = Parameters<typeof InvoiceBatchActions>[0]

function mountActions(overrides: Partial<ActionProps> = {}) {
    const props: ActionProps = {
        recommendedAction: {
            key: 'generate-all', label: 'Generate 2 invoices', icon: null,
            onClick: vi.fn(), disabled: false,
        },
        menuItems: [],
        pdfCount: 4,
        anyBatchPending: false,
        onDownloadAll: vi.fn(),
        ...overrides,
    }
    return { container: render(createElement(InvoiceBatchActions, props)), props }
}

function mountFilters(activeFilter: InvoiceRowFilter = null, counts = COUNTS) {
    const changes: InvoiceRowFilter[] = []
    const container = render(createElement(InvoiceRowFilterTabs, {
        counts, activeFilter, onFilterChange: (next) => changes.push(next),
    }))
    return { container, changes }
}

const segments = (container: HTMLElement) => [...container.querySelectorAll<HTMLButtonElement>('.filter-tab')]
const segment = (container: HTMLElement, label: string) =>
    segments(container).find((button) => button.textContent?.includes(label))!

describe('invoice row filter segments', () => {
    it('shows the whole period first, then the workflow stages and the rows needing attention', () => {
        const { container } = mountFilters()
        expect(segments(container).map((button) => button.textContent)).toEqual([
            'pages.invoices.filters.all 9',
            'pages.invoices.filters.drafts 2',
            'pages.invoices.filters.approved 3',
            'pages.invoices.filters.sent 1',
            'pages.invoices.filters.issues 2',
        ])
        const group = container.querySelector('[role="group"]')!
        expect(group.getAttribute('aria-label')).toBe('pages.invoices.filters.label')
        // The unfiltered period is the pressed segment.
        expect(segments(container).map((button) => button.getAttribute('aria-pressed')))
            .toEqual(['true', 'false', 'false', 'false', 'false'])
        // Rows needing attention stand out.
        expect(segment(container, 'filters.issues').className).toContain('filter-tab--attention')
    })

    it('narrows to a segment and clears it on a second press or on All', () => {
        const unfiltered = mountFilters()
        act(() => segment(unfiltered.container, 'filters.drafts').click())
        expect(unfiltered.changes).toEqual(['drafts'])

        const filtered = mountFilters('issues')
        expect(segment(filtered.container, 'filters.issues').getAttribute('aria-pressed')).toBe('true')
        expect(segment(filtered.container, 'filters.all').getAttribute('aria-pressed')).toBe('false')
        act(() => segment(filtered.container, 'filters.issues').click())
        act(() => segment(filtered.container, 'filters.all').click())
        expect(filtered.changes).toEqual([null, null])
    })
})

describe('empty invoice row filter segments', () => {
    it('are left out, but a pressed one that empties stays so it can be released', () => {
        const empty = { ...COUNTS, approved: 0, issues: 0 }
        const { container } = mountFilters(null, empty)
        expect(segments(container).map((button) => button.textContent)).toEqual([
            'pages.invoices.filters.all 9',
            'pages.invoices.filters.drafts 2',
            'pages.invoices.filters.sent 1',
        ])
        const pressed = mountFilters('approved', empty)
        expect(segment(pressed.container, 'filters.approved').getAttribute('aria-pressed')).toBe('true')
        // All left on its own offers no choice: the group is left out.
        const nothing = mountFilters(null, { ...COUNTS, drafts: 0, approved: 0, sent: 0, issues: 0 })
        expect(nothing.container.querySelector('[role="group"]')).toBeNull()
    })

    it('leave out a segment that counts the whole period, as it shows the same rows', () => {
        const allDrafts = { ...COUNTS, all: 2, approved: 0, sent: 0, issues: 0 }
        expect(mountFilters(null, allDrafts).container.querySelector('[role="group"]')).toBeNull()
        const pressed = mountFilters('drafts', allDrafts)
        expect(segment(pressed.container, 'filters.drafts').getAttribute('aria-pressed')).toBe('true')
    })
})

describe('invoice batch actions', () => {
    it('keeps the recommended action primary and the rest in the overflow menu', async () => {
        const { container } = mountActions({
            menuItems: [
                { key: 'generate-all', label: 'duplicate of the primary', onClick: vi.fn() },
                { key: 'send-all', label: 'Send 3 invoices', onClick: vi.fn() },
            ],
        })
        const group = container.querySelector('[role="group"]')!
        expect(group.getAttribute('aria-label')).toBe('pages.invoices.batch.title')
        const primary = [...container.querySelectorAll('button')].filter((button) => button.textContent === 'Generate 2 invoices')
        expect(primary).toHaveLength(1)
        expect(primary[0].className).toContain('button-primary')

        // The promoted action never repeats inside the overflow menu.
        const menuButton = [...container.querySelectorAll('button')].find((button) =>
            button.getAttribute('aria-label') === 'pages.invoices.moreBatchActions')!
        expect(menuButton.getAttribute('title')).toBe('pages.invoices.moreBatchActions')
        expect(menuButton.textContent).toBe('')
        act(() => menuButton.click())
        await waitForCondition(() => document.body.textContent?.includes('Send 3 invoices') === true, 'the overflow menu')
        expect(document.body.textContent).toContain('Send 3 invoices')
        expect(document.body.textContent).not.toContain('duplicate of the primary')
    })

    it('hides the download all button when the period holds no document', () => {
        const withPdfs = mountActions()
        expect(withPdfs.container.textContent).toContain('pages.invoices.batch.downloadAll (4)')

        const withoutPdfs = mountActions({ pdfCount: 0 })
        expect(withoutPdfs.container.textContent).not.toContain('pages.invoices.batch.downloadAll')
    })

    it('leaves no empty action cluster when nothing can be done', () => {
        const { container } = mountActions({ recommendedAction: null, pdfCount: 0 })
        expect(container.querySelector('.invoice-batch-actions')).toBeNull()
        // A pending batch must not create an empty overflow menu.
        const pending = mountActions({ recommendedAction: null, anyBatchPending: true, pdfCount: 0 })
        expect(pending.container.querySelector('.invoice-batch-actions')).toBeNull()
    })

    it('keeps existing batch controls disabled during a mutation', () => {
        const { container } = mountActions({
            anyBatchPending: true,
            recommendedAction: null,
            menuItems: [{ key: 'send-all', label: 'Send 3 invoices', onClick: vi.fn(), disabled: true }],
        })
        const buttons = [...container.querySelectorAll<HTMLButtonElement>('.invoice-batch-actions button')]
        expect(buttons).toHaveLength(2)
        expect(buttons.every(button => button.disabled)).toBe(true)
    })
})
