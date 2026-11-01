import { act, createElement, type ReactElement } from 'react'
import { createRoot } from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MantineProvider } from '@mantine/core'
import { MemoryRouter, RouterProvider, createMemoryRouter } from 'react-router-dom'

/** Mounts `element` with the providers the app gives every page, and returns a way to tear it down. */
export async function renderWithProviders(element: ReactElement, cleanups: Array<() => void>) {
    const container = document.createElement('div')
    document.body.append(container)
    const root = createRoot(container)
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    cleanups.push(() => {
        act(() => root.unmount())
        client.clear()
        container.remove()
    })
    await act(async () =>
        root.render(
            createElement(QueryClientProvider, { client },
                createElement(MantineProvider, null,
                    createElement(MemoryRouter, null, element))),
        ),
    )
    return { container, client }
}

export function setInputValue(input: HTMLInputElement, value: string) {
    const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!
    setter.call(input, value)
    input.dispatchEvent(new Event('input', { bubbles: true }))
}

/**
 * The same, in a data router: what a page needs that blocks navigation (`useBlocker`) or reads the history
 * state. Returns the router so a test can look at the location and go back.
 */
export async function renderWithDataRouter(element: ReactElement, cleanups: Array<() => void>, initialEntries: string[] = ['/']) {
    const container = document.createElement('div')
    document.body.append(container)
    const root = createRoot(container)
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    const router = createMemoryRouter([{ path: '*', element }], { initialEntries })
    cleanups.push(() => {
        act(() => root.unmount())
        client.clear()
        container.remove()
    })
    await act(async () =>
        root.render(
            createElement(QueryClientProvider, { client },
                createElement(MantineProvider, null,
                    createElement(RouterProvider, { router }))),
        ),
    )
    return { container, client, router }
}
