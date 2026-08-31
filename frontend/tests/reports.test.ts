import { describe, expect, it, vi, beforeEach } from 'vitest'
import { de } from '../src/i18n/locales/de'
import { en } from '../src/i18n/locales/en'
import { fr } from '../src/i18n/locales/fr'
import { it as itLocale } from '../src/i18n/locales/it'

vi.mock('react-i18next', () => ({
    useTranslation: () => ({ t: (k: string) => k }),
}))

import { createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { act } from 'react'
import { YearDownloadCard } from '../src/features/reports/YearDownloadCard'
import { canSeeReports } from '../src/components/Layout'

// jsdom does not enable the React act() environment by default; without this
// flag every act() call warns and deferred work is not flushed reliably.
globalThis.IS_REACT_ACT_ENVIRONMENT = true

function renderCard(props: Parameters<typeof YearDownloadCard>[0]) {
    const container = document.createElement('div')
    document.body.appendChild(container)
    const root = createRoot(container)
    act(() => {
        root.render(createElement(YearDownloadCard, props))
    })
    return {
        container,
        unmount: () => {
            act(() => root.unmount())
            container.remove()
        },
    }
}

describe('reports i18n', () => {
    it('has nav.reports in all locales', () => {
        expect((en as any).nav.reports).toBeTruthy()
        expect((de as any).nav.reports).toBeTruthy()
        expect((fr as any).nav.reports).toBeTruthy()
        expect((itLocale as any).nav.reports).toBeTruthy()
    })

    it('has pages.reports.* moved from dashboard in all locales', () => {
        for (const locale of [en, de, fr, itLocale] as any[]) {
            expect(locale.pages.reports).toBeTruthy()
            expect(locale.pages.reports.annualStatement).toBeTruthy()
            expect(locale.pages.reports.annualStatement.title).toBeTruthy()
            expect(locale.pages.reports.financialSummary).toBeTruthy()
            expect(locale.pages.reports.financialSummary.title).toBeTruthy()
            expect((locale.pages.dashboard as any).annualStatement).toBeUndefined()
            expect((locale.pages.dashboard as any).financialSummary).toBeUndefined()
            // dead nested year/downloading keys should be gone (shared top-level used)
            expect((locale.pages.reports.annualStatement as any).year).toBeUndefined()
            expect((locale.pages.reports.annualStatement as any).downloading).toBeUndefined()
            expect((locale.pages.reports.financialSummary as any).year).toBeUndefined()
            expect((locale.pages.reports.financialSummary as any).downloading).toBeUndefined()
        }
    })

    it('has empty-state keys in all locales', () => {
        for (const locale of [en, de, fr, itLocale] as any[]) {
            expect(locale.pages.reports.selectZevTitle).toBeTruthy()
            expect(locale.pages.reports.selectZevDescription).toBeTruthy()
            expect(locale.pages.reports.noZevTitle).toBeTruthy()
            expect(locale.pages.reports.noZevDescription).toBeTruthy()
        }
    })

    it('deleted dashboard.quickStart', () => {
        for (const locale of [en, de, fr, itLocale] as any[]) {
            expect((locale.dashboard as any).quickStart).toBeUndefined()
        }
    })
})

describe('reports nav visibility', () => {
    it('canSeeReports matches the route allowedRoles', () => {
        expect(canSeeReports('admin')).toBe(true)
        expect(canSeeReports('zev_owner')).toBe(true)
        expect(canSeeReports('participant')).toBe(true)
        expect(canSeeReports('guest')).toBe(false)
        expect(canSeeReports(undefined)).toBe(false)
    })
})

describe('YearDownloadCard', () => {
    beforeEach(() => {
        document.body.innerHTML = ''
    })

    const baseProps = {
        titleKey: 'pages.reports.annualStatement.title',
        descriptionKey: 'pages.reports.annualStatement.description',
        busy: false,
        error: null,
        onDownload: () => {},
    }

    it('renders no year selector (the year lives on the page)', () => {
        const { container, unmount } = renderCard({ ...baseProps })
        expect(container.querySelector('select')).toBeNull()
        unmount()
    })

    it('busy disables button and shows downloading label', () => {
        const { container, unmount } = renderCard({
            ...baseProps,
            busy: true,
            actionLabelKey: 'pages.reports.annualStatement.downloadAll',
        })
        const button = container.querySelector('button') as HTMLButtonElement
        expect(button.disabled).toBe(true)
        expect(button.textContent).toBe('pages.reports.downloading')
        unmount()
    })

    it('error renders as alert with error-text styling hook', () => {
        const { container, unmount } = renderCard({ ...baseProps, error: 'boom' })
        expect(container.textContent).toContain('boom')
        expect(container.querySelector('.error-text')).toBeTruthy()
        expect(container.querySelector('[role="alert"]')).toBeTruthy()
        unmount()
    })

    it('has type=button to avoid form submit', () => {
        const { container, unmount } = renderCard({ ...baseProps })
        const button = container.querySelector('button') as HTMLButtonElement
        expect(button.type).toBe('button')
        unmount()
    })

    it('onDownload fires on click', () => {
        const spy = vi.fn()
        const { container, unmount } = renderCard({ ...baseProps, onDownload: spy })
        const button = container.querySelector('button') as HTMLButtonElement
        act(() => {
            button.click()
        })
        expect(spy).toHaveBeenCalledOnce()
        unmount()
    })
})
