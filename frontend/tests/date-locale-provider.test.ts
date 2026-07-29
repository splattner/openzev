import { createRoot } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { act, createElement } from 'react'
import dayjs from 'dayjs'
import { DatePicker } from '@mui/x-date-pickers/DatePicker'
import i18n from '../src/i18n'
import { DateLocaleProvider } from '../src/components/DateLocaleProvider'

describe('DateLocaleProvider', () => {
  let container: HTMLDivElement
  let root: ReturnType<typeof createRoot>

  beforeEach(() => {
    ;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
    container = document.createElement('div')
    document.body.appendChild(container)
    root = createRoot(container)
  })

  afterEach(() => {
    act(() => root.unmount())
    container.remove()
  })

  const renderPicker = () =>
    act(() => {
      root.render(
        createElement(
          DateLocaleProvider,
          null,
          // Without an explicit `format`, the field is formatted by the dayjs
          // adapter's localized `L` format, so the rendered value proves which
          // `adapterLocale` the app-level LocalizationProvider supplies.
          createElement(DatePicker, {
            value: dayjs('2026-01-15'),
            onChange: () => undefined,
          }),
        ),
      )
    })

  const inputValue = () => container.querySelector('input')?.value

  it('formats picker values using the active UI language', async () => {
    await act(async () => {
      await i18n.changeLanguage('de')
    })
    renderPicker()

    expect(inputValue()).toBe('15.01.2026') // German dayjs `L`: DD.MM.YYYY
  })

  it('re-localizes pickers when the language changes at runtime', async () => {
    await act(async () => {
      await i18n.changeLanguage('de')
    })
    renderPicker()
    expect(inputValue()).toBe('15.01.2026')

    await act(async () => {
      await i18n.changeLanguage('fr')
    })
    expect(inputValue()).toBe('15/01/2026') // French dayjs `L`: DD/MM/YYYY
  })

  it('falls back to English formatting', async () => {
    await act(async () => {
      await i18n.changeLanguage('en')
    })
    renderPicker()

    expect(inputValue()).toBe('01/15/2026') // English dayjs `L`: MM/DD/YYYY
  })

  // `adapterLocale` only covers dayjs-derived content; picker chrome (the
  // "Choose date" aria-label, action bar, month navigation) comes from MUI's
  // separate `localeText` bundles. Assert on the closed-state aria-label so
  // this stays independent of popup interaction quirks in jsdom.
  const expectLocalizedPickerChrome = (needle: string) =>
    expect(container.querySelector(`[aria-label*="${needle}"]`), `expected aria-label containing "${needle}"`).not.toBeNull()

  it('localizes MUI picker component text for every supported language', async () => {
    await act(async () => {
      await i18n.changeLanguage('de')
    })
    renderPicker()
    expectLocalizedPickerChrome('Datum auswählen')

    await act(async () => {
      await i18n.changeLanguage('fr')
    })
    expectLocalizedPickerChrome('Choisir la date')

    await act(async () => {
      await i18n.changeLanguage('it')
    })
    expectLocalizedPickerChrome('Scegli la data')

    await act(async () => {
      await i18n.changeLanguage('en')
    })
    expectLocalizedPickerChrome('Choose date')
  })
})
