import { act, createElement } from 'react'
import { afterEach, expect, it, vi } from 'vitest'
import { TariffDraftBands } from '../src/features/tariffs/TariffDraftBands'
import { defaultTariffPeriodFormValues, type TariffPeriodFormValues } from '../src/features/tariffs/useTariffForms'
import { renderWithProviders, setInputValue } from './helpers/render'
import { waitForCondition } from './helpers/waitForCondition'

vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key }) }))

const cleanups: Array<() => void> = []
afterEach(() => cleanups.splice(0).forEach((cleanup) => cleanup()))

it('adds the band the coverage warning offers to the new tariff’s bands, with its days and months', async () => {
    const summer = '4,5,6,7,8,9'
    const band = (extra: Partial<TariffPeriodFormValues>): TariffPeriodFormValues => ({ ...defaultTariffPeriodFormValues, billing_mode: 'energy', price_chf_per_kwh: '0.2', ...extra })
    const bands = [
        band({ period_type: 'high', time_from: '07:00', time_to: '21:00', weekdays: '0,1,2,3,4', months: summer }),
        band({ period_type: 'low', weekdays: '5,6', months: summer }),
        band({ period_type: 'low', months: '1,2,3,10,11,12' }),
    ]
    const onChange = vi.fn()
    const { container } = await renderWithProviders(createElement(TariffDraftBands, { bands, onChange, validity: {}, onEditingChange: vi.fn() }), cleanups)
    const button = (label: string) => [...container.querySelectorAll('button')].find((candidate) => candidate.textContent === label)!

    await act(async () => button('pages.tariffs.coverage.addBand').click())
    await act(async () => setInputValue(container.querySelector<HTMLInputElement>('.tariff-draft-band-editor input[type="number"]')!, '0.25'))
    await act(async () => button('pages.tariffs.form.keepBand').click())
    await waitForCondition(() => onChange.mock.calls.length > 0, 'kept band')
    expect(onChange.mock.calls[0][0].at(-1)).toMatchObject({
        period_type: 'band', price_chf_per_kwh: '0.25', time_from: '', time_to: '', weekdays: '0,1,2,3,4', months: summer,
    })
})
