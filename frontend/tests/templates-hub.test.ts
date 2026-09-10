import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { MemoryRouter, useLocation } from 'react-router-dom'
import { MantineProvider } from '@mantine/core'
import { AdminTemplatesHubPage } from '../src/pages/AdminTemplatesHubPage'

vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key }) }))
vi.mock('../src/pages/AdminPdfTemplatesPage', () => ({
    AdminPdfTemplatesPage: ({ template }: { template: string }) => createElement('main', null, template),
}))
vi.mock('../src/pages/AdminEmailTemplatesPage', () => ({
    AdminEmailTemplatesPage: ({ template }: { template: string }) => createElement('main', null, template),
}))

function RoutedHub() {
    const location = useLocation()
    return createElement('div', null,
        createElement('output', null, location.pathname + location.search),
        createElement(AdminTemplatesHubPage, { tab: location.pathname.endsWith('/email') ? 'email' : 'pdf' }),
    )
}

const cleanups: (() => void)[] = []
afterEach(() => cleanups.splice(0).forEach((cleanup) => cleanup()))

async function render(url: string) {
    const container = document.createElement('div')
    document.body.append(container)
    const root = createRoot(container)
    cleanups.push(() => { act(() => root.unmount()); container.remove() })
    await act(async () => root.render(
        createElement(MantineProvider, null,
            createElement(MemoryRouter, { initialEntries: [url] }, createElement(RoutedHub))),
    ))
    return container
}

const tab = (container: Element, value: string) =>
    Array.from(container.querySelectorAll<HTMLButtonElement>('[role="tab"]'))
        .find((button) => button.textContent === `pages.adminTemplates.items.${value}`)!

describe('templates tab strip', () => {
    it('renders two labelled tab rows and no icon tiles', async () => {
        const container = await render('/admin/templates/pdf?template=contract&source=bookmark')
        const tabs = container.querySelectorAll('[role="tab"]')
        expect(tabs).toHaveLength(7)
        const lists = container.querySelectorAll('[role="tablist"]')
        expect(lists).toHaveLength(2)
        expect(lists[0].getAttribute('aria-labelledby')).toBe('template-tabs-group-pdf')
        expect(lists[1].getAttribute('aria-labelledby')).toBe('template-tabs-group-email')
        expect(container.querySelector('#template-tabs-group-pdf')?.textContent)
            .toBe('pages.adminTemplates.tabs.pdf')
        expect(container.querySelector('#template-tabs-group-email')?.textContent)
            .toBe('pages.adminTemplates.tabs.email')
        expect(container.querySelector('nav')).toBeNull()
        expect(container.querySelector('svg')).toBeNull()
        expect(container.querySelector('select')).toBeNull()
        expect(tab(container, 'contract').hasAttribute('data-active')).toBe(true)
        expect(container.querySelector('main')?.textContent).toBe('contract')
    })

    it('switches documents across categories and preserves unrelated query parameters', async () => {
        const container = await render('/admin/templates/pdf?template=contract&source=bookmark')
        for (const value of ['participant_magic_link', 'annual_statement']) {
            await act(async () => { tab(container, value).click() })
            expect(container.querySelector('main')?.textContent).toBe(value)
            expect(container.querySelector('output')?.textContent).toContain(`template=${value}&source=bookmark`)
            expect(container.querySelector('output')?.textContent).toContain(
                value === 'annual_statement' ? '/admin/templates/pdf?' : '/admin/templates/email?',
            )
            expect(tab(container, value).hasAttribute('data-active')).toBe(true)
        }
    })

    it.each([
        ['/admin/templates', 'invoice'],
        ['/admin/templates/email', 'invoice_email'],
        ['/admin/templates/pdf?template=unknown', 'invoice'],
        ['/admin/templates/email?template=contract', 'invoice_email'],
        ['/admin/templates/email?template=email_verification', 'email_verification'],
    ])('resolves %s to %s', async (url, expected) => {
        const container = await render(url)
        expect(tab(container, expected).hasAttribute('data-active')).toBe(true)
        expect(container.querySelector('main')?.textContent).toBe(expected)
    })
})
