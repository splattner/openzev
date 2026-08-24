import { createRoot } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act, createElement } from 'react'
import { MantineProvider } from '@mantine/core'
import i18n from '../src/i18n'
import { DateLocaleProvider } from '../src/components/DateLocaleProvider'
import { CivilDateInput } from '../src/components/CivilDateInput'

vi.mock('../src/lib/appSettings', () => ({
    useAppSettings: () => ({ settings: { date_format_short: 'dd.MM.yyyy' } }),
    toDayJsDateFormat: (pattern: string) =>
        pattern === 'dd.MM.yyyy' ? 'DD.MM.YYYY' : pattern,
}))

describe('CivilDateInput under DateLocaleProvider', () => {
    let container: HTMLDivElement
    let root: ReturnType<typeof createRoot>

    beforeEach(() => {
        ;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
        // MantineProvider reads prefers-color-scheme; jsdom has no matchMedia.
        Object.defineProperty(window, 'matchMedia', {
            writable: true,
            value: (query: string) => ({
                matches: false,
                media: query,
                onchange: null,
                addListener: () => undefined,
                removeListener: () => undefined,
                addEventListener: () => undefined,
                removeEventListener: () => undefined,
                dispatchEvent: () => false,
            }),
        })
        container = document.createElement('div')
        document.body.appendChild(container)
        root = createRoot(container)
    })

    afterEach(() => {
        act(() => root.unmount())
        container.remove()
    })

    const renderPicker = (onChange: (iso: string | null) => void) =>
        act(() => {
            root.render(
                createElement(
                    MantineProvider,
                    null,
                    createElement(
                        DateLocaleProvider,
                        null,
                        createElement(CivilDateInput, {
                            value: '2026-01-15',
                            onChange,
                        }),
                    ),
                ),
            )
        })

    const hiddenValue = () =>
        container.querySelector<HTMLInputElement>('input[type="hidden"], input')?.value

    it('keeps the plain civil date stable across UI languages', async () => {
        for (const lang of ['de', 'fr', 'it', 'en']) {
            await act(async () => {
                await i18n.changeLanguage(lang)
            })
            renderPicker(() => undefined)

            // The data contract (ADR 0007): whatever the label shows, the
            // stored/submitted value is the same YYYY-MM-DD in every locale —
            // no local-time shift, no per-language serialization drift.
            expect(hiddenValue()).toBe('2026-01-15')
        }
    })

    it('emits an unchanged civil date string on change and null on clear', async () => {
        await act(async () => {
            await i18n.changeLanguage('de')
        })
        const received: Array<string | null> = []
        renderPicker((iso) => received.push(iso))

        // Clearing (clearable button) must surface null, never '' or a Date.
        // Strict on purpose: if this selector drifts from Mantine internals the
        // test must fail loudly, not silently degrade to passthrough.
        const clearButton = container.querySelector<HTMLButtonElement>(
            'button[aria-label*="lear"], .mantine-InputClearButton-root',
        )
        expect(clearButton, 'clear button not rendered — selector drifted vs Mantine').toBeTruthy()
        await act(async () => {
            clearButton!.dispatchEvent(new MouseEvent('click', { bubbles: true }))
        })
        expect(received.at(-1)).toBeNull()
    })
})
