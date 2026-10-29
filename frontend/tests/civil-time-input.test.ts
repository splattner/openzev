import { createElement } from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { CivilTimeInput } from '../src/components/CivilTimeInput'
import { renderWithProviders } from './helpers/render'

vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key }) }))

const cleanups: (() => void)[] = []
afterEach(() => cleanups.splice(0).forEach((cleanup) => cleanup()))

const spin = (container: HTMLElement) => [...container.querySelectorAll<HTMLInputElement>('input[role="spinbutton"]')]

describe('CivilTimeInput', () => {
    it('shows a time from the API (with seconds) as 24-hour hours and minutes, with no am/pm', async () => {
        const { container } = await renderWithProviders(createElement(CivilTimeInput, { value: '21:00:00', onChange: vi.fn() }), cleanups)
        expect(spin(container).map((input) => input.value)).toEqual(['21', '00'])
        expect(container.querySelector('select')).toBeNull()
        expect(container.textContent).not.toMatch(/am|pm/i)
    })

    it('is empty for no time, and offers to clear a set one', async () => {
        const empty = await renderWithProviders(createElement(CivilTimeInput, { value: null, onChange: vi.fn() }), cleanups)
        expect(spin(empty.container).map((input) => input.value)).toEqual(['', ''])
        const filled = await renderWithProviders(createElement(CivilTimeInput, { value: '07:00', onChange: vi.fn() }), cleanups)
        expect(filled.container.querySelector('button')).not.toBeNull()
    })

    it('reports a cleared time as an empty string, not the previous value', async () => {
        const onChange = vi.fn()
        const { container } = await renderWithProviders(createElement(CivilTimeInput, { value: '07:00', onChange }), cleanups)
        container.querySelector<HTMLButtonElement>('button')!.click()
        expect(onChange).toHaveBeenCalledWith('')
    })
})
