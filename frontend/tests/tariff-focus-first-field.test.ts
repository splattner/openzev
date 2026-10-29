import { createElement } from 'react'
import { afterEach, describe, expect, it } from 'vitest'
import { useFocusFirstField } from '../src/features/tariffs/useFocusFirstField'
import { renderWithProviders } from './helpers/render'

const cleanups: (() => void)[] = []
afterEach(() => cleanups.splice(0).forEach((cleanup) => cleanup()))

/** Mounts a form made of the given fields, then reports which one the hook focused. */
async function focused(fields: Array<[tag: string, attrs: Record<string, unknown>]>) {
    const form = document.createElement('form')
    for (const [tag, attrs] of fields) {
        const field = document.createElement(tag)
        for (const [name, value] of Object.entries(attrs)) field.setAttribute(name, String(value))
        form.append(field)
    }
    document.body.append(form)
    cleanups.push(() => form.remove())
    const ref = { current: form }
    function Probe() {
        useFocusFirstField(ref)
        return null
    }
    await renderWithProviders(createElement(Probe), cleanups)
    return document.activeElement?.getAttribute('name')
}

describe('useFocusFirstField', () => {
    it('focuses the first enabled field, skipping a disabled one', async () => {
        expect(await focused([
            ['select', { name: 'source', disabled: '' }],
            ['input', { name: 'first' }],
            ['textarea', { name: 'notes' }],
        ])).toBe('first')
    })

    it('counts a date picker button as a field, so a version does not start in its notes', async () => {
        expect(await focused([
            ['select', { name: 'source', disabled: '' }],
            ['button', { type: 'button', name: 'valid_from', 'data-dates-input': 'true' }],
            ['textarea', { name: 'notes' }],
        ])).toBe('valid_from')
    })
})
