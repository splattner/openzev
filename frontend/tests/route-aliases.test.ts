import { describe, it, expect } from 'vitest'
import { createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { act } from 'react'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import { AliasNavigate, InvoiceDetailAlias, MeteringDataAlias } from '../src/components/RouteAliases'

function LocationProbe() {
    const location = useLocation()
    return createElement('div', { 'data-testid': 'location' }, `${location.pathname}${location.search}${location.hash}`)
}

function renderAt(path: string, route: string, element: ReturnType<typeof createElement>) {
    const container = document.createElement('div')
    document.body.appendChild(container)
    const root = createRoot(container)
    act(() => {
        root.render(
            createElement(
                MemoryRouter,
                { initialEntries: [path] },
                createElement(
                    Routes,
                    null,
                    createElement(Route, { path: route, element }),
                    createElement(Route, { path: '*', element: createElement(LocationProbe) }),
                ),
            ),
        )
    })
    return {
        location: () => container.querySelector('[data-testid="location"]')?.textContent,
        unmount: () => {
            act(() => root.unmount())
            container.remove()
        },
    }
}

describe('route aliases', () => {
    it('routes a legacy quality bookmark to the guarded quality route, dropping ?tab', () => {
        const page = renderAt('/metering-data?tab=quality', '/metering-data', createElement(MeteringDataAlias))
        expect(page.location()).toBe('/metering/quality')
        page.unmount()
    })

    it('keeps other params when routing the legacy bookmark', () => {
        const page = renderAt(
            '/metering-data?tab=quality&metering_point=7',
            '/metering-data',
            createElement(MeteringDataAlias),
        )
        expect(page.location()).toBe('/metering/quality?metering_point=7')
        page.unmount()
    })

    it('routes a legacy chart bookmark to the chart route', () => {
        const page = renderAt(
            '/metering-data?metering_point=7',
            '/metering-data',
            createElement(MeteringDataAlias),
        )
        expect(page.location()).toBe('/metering/chart?metering_point=7')
        page.unmount()
    })

    it('forwards the path param and the query string for invoice detail', () => {
        const page = renderAt('/invoices/42?from=dashboard', '/invoices/:invoiceId', createElement(InvoiceDetailAlias))
        expect(page.location()).toBe('/billing/invoices/42?from=dashboard')
        page.unmount()
    })

    it('alias without a query string stays clean', () => {
        const page = renderAt('/imports', '/imports', createElement(AliasNavigate, { to: '/metering/imports' }))
        expect(page.location()).toBe('/metering/imports')
        page.unmount()
    })

    it('preserves the hash through aliases', () => {
        const page = renderAt('/invoices/42?from=dashboard#summary', '/invoices/:invoiceId', createElement(InvoiceDetailAlias))
        expect(page.location()).toBe('/billing/invoices/42?from=dashboard#summary')
        page.unmount()
    })

    it('merges inbound query params with a destination that already has some', () => {
        const page = renderAt(
            '/admin/settings/regional?foo=bar',
            '/admin/settings/regional',
            createElement(AliasNavigate, { to: '/admin/system-settings?tab=regional' }),
        )
        expect(page.location()).toBe('/admin/system-settings?tab=regional&foo=bar')
        page.unmount()
    })

    it('keeps the alias-pinned param when the incoming query tries to hijack it', () => {
        const page = renderAt(
            '/admin/settings/regional?tab=vat',
            '/admin/settings/regional',
            createElement(AliasNavigate, { to: '/admin/system-settings?tab=regional' }),
        )
        expect(page.location()).toBe('/admin/system-settings?tab=regional')
        page.unmount()
    })
})
