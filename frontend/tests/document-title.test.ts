import { afterEach, describe, expect, it, vi } from 'vitest'
import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { PageHeader } from '../src/components/PageHeader'
import { useDocumentTitle } from '../src/lib/useDocumentTitle'

const interpolate = (template: string, values: Record<string, unknown> = {}) =>
    template.replace(/\{\{(\w+)\}\}/g, (_, name: string) => String(values[name]))

// The real English templates, so the tests pin the visible format.
vi.mock('react-i18next', async () => {
    const { en } = await import('../src/i18n/locales/en')
    return { useTranslation: () => ({
        t: (key: string, values?: Record<string, unknown>) => {
            if (key === 'app.title') return en.app.title
            if (key === 'app.documentTitle') return interpolate(en.app.documentTitle, values)
            if (key === 'app.documentTitleScoped') return interpolate(en.app.documentTitleScoped, values)
            return key
        },
        i18n: { language: 'en' },
    }) }
})

function TitleOnly({ page }: { page?: string }) {
    useDocumentTitle(page)
    return null
}

const mounted: Array<() => void> = []

async function render(element: ReturnType<typeof createElement>) {
    const container = document.createElement('div')
    document.body.appendChild(container)
    const root = createRoot(container)
    mounted.push(() => { act(() => root.unmount()); container.remove() })
    await act(async () => { root.render(element) })
    return {
        rerender: async (next: ReturnType<typeof createElement>) => { await act(async () => { root.render(next) }) },
    }
}

afterEach(() => {
    mounted.splice(0).forEach((unmount) => unmount())
    document.title = 'OpenZEV'
})

describe('document title', () => {
    it('names the page and its scope from the page header', async () => {
        await render(createElement(PageHeader, { eyebrow: 'Muster ZEV', title: 'Billing' }))
        expect(document.title).toBe('Billing · Muster ZEV – OpenZEV')
    })

    it('shows a scope note beside the community but keeps it out of the title', async () => {
        await render(createElement(PageHeader, { eyebrow: 'Muster ZEV', scopeNote: 'Viewer (read only)', title: 'Billing' }))
        expect(document.querySelector('.eyebrow')?.textContent).toBe('Muster ZEV · Viewer (read only)')
        expect(document.title).toBe('Billing · Muster ZEV – OpenZEV')
    })

    it('describes the focusable title by its scope line, note included', async () => {
        await render(createElement(PageHeader, { eyebrow: 'Muster ZEV', scopeNote: 'Viewer (read only)', title: 'Billing' }))
        const heading = document.querySelector('h1')!
        const description = document.getElementById(heading.getAttribute('aria-describedby')!)
        expect(description?.textContent).toBe('Muster ZEV · Viewer (read only)')
    })

    it('omits the scope when the header has none, and follows title changes', async () => {
        const view = await render(createElement(PageHeader, { title: 'Account' }))
        expect(document.title).toBe('Account – OpenZEV')
        await view.rerender(createElement(PageHeader, { title: 'Accounts', eyebrow: 'Platform administration' }))
        expect(document.title).toBe('Accounts · Platform administration – OpenZEV')
    })

    it('keeps the previous title until a page names itself', async () => {
        document.title = 'Billing – OpenZEV'
        const view = await render(createElement(TitleOnly))
        expect(document.title).toBe('Billing – OpenZEV')
        await view.rerender(createElement(TitleOnly, { page: 'Sign in' }))
        expect(document.title).toBe('Sign in – OpenZEV')
        mounted.splice(0).forEach((unmount) => unmount())
        expect(document.title).toBe('Sign in – OpenZEV')
    })

    it('can say more than the heading, so a tab of a hub names itself', async () => {
        await render(createElement(PageHeader, {
            eyebrow: 'Muster ZEV', title: 'Settings', documentTitle: 'Billing & payment · Settings',
        }))
        expect(document.title).toBe('Billing & payment · Settings · Muster ZEV – OpenZEV')
        expect(document.querySelector('h1')?.textContent).toBe('Settings')
    })
})
