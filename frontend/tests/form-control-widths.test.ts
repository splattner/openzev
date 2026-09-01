import { describe, it, expect, beforeAll } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

/**
 * The global `input, select { width: 100% }` rule is written for text fields.
 * Without an exclusion a checkbox inherits it, stretches across its flex row
 * and shoves its own label to the far right, where the label wraps onto two
 * lines (#490).
 *
 * jsdom does not lay out, but it does resolve the cascade for `width`, which
 * is the whole of the bug — so these assertions catch a regression without a
 * browser or a running stack.
 */
function control(type: string): HTMLInputElement {
    const input = document.createElement('input')
    input.type = type
    document.body.appendChild(input)
    return input
}

describe('global form-control widths', () => {
    beforeAll(() => {
        const style = document.createElement('style')
        style.textContent = readFileSync(resolve(__dirname, '../src/index.css'), 'utf8')
        document.head.appendChild(style)
    })

    it('leaves checkboxes at their intrinsic width', () => {
        expect(getComputedStyle(control('checkbox')).width).toBe('auto')
    })

    it('leaves radios at their intrinsic width', () => {
        // MeteringDeleteDataModal renders two; they were stretched exactly like
        // the checkboxes before the exclusion existed.
        expect(getComputedStyle(control('radio')).width).toBe('auto')
    })

    it('still stretches text-like inputs to fill their field', () => {
        // The guard must be narrow: these are what the 100% rule is for.
        for (const type of ['text', 'email', 'password', 'number', 'date', 'search']) {
            expect(getComputedStyle(control(type)).width, `${type} input`).toBe('100%')
        }
    })

    it('still stretches selects to fill their field', () => {
        const select = document.createElement('select')
        document.body.appendChild(select)
        expect(getComputedStyle(select).width).toBe('100%')
    })
})
