import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { BulkDeleteModal } from '../src/features/imports/BulkDeleteModal'

vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key }) }))
vi.mock('../src/lib/appSettings', async (importOriginal) => {
    const actual = await importOriginal<typeof import('../src/lib/appSettings')>()
    return {
        ...actual,
        useAppSettings: () => ({ settings: {} }),
        formatShortDate: (value: string) => value,
    }
})

globalThis.IS_REACT_ACT_ENVIRONMENT = true

let container: HTMLDivElement
let root: ReturnType<typeof createRoot>

beforeEach(() => {
    container = document.createElement('div')
    document.body.appendChild(container)
    root = createRoot(container)
})

afterEach(() => {
    act(() => root.unmount())
    container.remove()
})

function renderModal(overrides: Partial<React.ComponentProps<typeof BulkDeleteModal>> = {}) {
    const props = {
        open: true,
        // 'all' avoids the Mantine date inputs (period mode); the blocker
        // UI under test is mode-independent.
        mode: 'all' as const,
        dateFrom: '2026-02-01',
        dateTo: '2026-02-28',
        armed: false,
        visibleCount: 3,
        protectedCount: 0,
        protectedExamples: [] as string[],
        pending: false,
        zevName: 'ZEV',
        onClose: vi.fn(),
        onModeChange: vi.fn(),
        onDateFromChange: vi.fn(),
        onDateToChange: vi.fn(),
        onReview: vi.fn(),
        onBack: vi.fn(),
        onConfirm: vi.fn(),
        ...overrides,
    }
    act(() => {
        root.render(createElement(BulkDeleteModal, props))
    })
}

function findButton(key: string): HTMLButtonElement {
    const button = Array.from(container.querySelectorAll('button')).find((element) => element.textContent === key)
    if (!button) throw new Error(`button ${key} not found`)
    return button as HTMLButtonElement
}

describe('BulkDeleteModal protected blockers', () => {
    it('allows review when no protected import is in scope', () => {
        renderModal()
        expect(container.textContent).not.toContain('pages.imports.delete.blockedNotice')
        expect(findButton('pages.imports.delete.reviewAction').disabled).toBe(false)
    })

    it('names blockers and disables review while they are included', () => {
        renderModal({ protectedCount: 2, protectedExamples: ['a.csv — 2026-02-10'] })
        expect(container.textContent).toContain('pages.imports.delete.blockedNotice')
        expect(container.textContent).toContain('a.csv — 2026-02-10')
        expect(container.textContent).toContain('pages.imports.delete.blockedMore')
        expect(findButton('pages.imports.delete.reviewAction').disabled).toBe(true)
    })

    it('disables the armed confirmation while blockers are included', () => {
        renderModal({ armed: true, protectedCount: 1, protectedExamples: ['a.csv — 2026-02-10'] })
        expect(findButton('pages.imports.delete.confirmAction').disabled).toBe(true)
    })
})
