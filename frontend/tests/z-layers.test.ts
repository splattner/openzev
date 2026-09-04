import { describe, expect, it } from 'vitest'
import { mantineTheme } from '../src/lib/mantineTheme'
import { Z_MODAL, Z_POPOVER, Z_TOAST } from '../src/lib/zLayers'

/**
 * Our `FormModal` is a plain fixed div at `Z_MODAL`, while Mantine portals its
 * overlays to `document.body` at its own default of 300. A dropdown opened
 * inside a modal therefore renders *behind* it unless the theme lifts it —
 * which is how the create-tariff date picker became impossible to use: the
 * calendar opened, but the modal was painted on top of it.
 *
 * The values are only correct relative to each other, and a component missing
 * from the theme is invisible until someone opens that dropdown inside a
 * modal. So both are asserted here rather than left to manual QA.
 */
describe('z-layer ordering', () => {
  it('puts overlays above modals, and toasts above both', () => {
    expect(Z_POPOVER).toBeGreaterThan(Z_MODAL)
    expect(Z_TOAST).toBeGreaterThan(Z_POPOVER)
  })
})

describe('mantine overlay defaults', () => {
  const components = mantineTheme.components as Record<
    string,
    { defaultProps?: Record<string, unknown> }
  >

  // Everything portalled that we open from inside a modal, or could.
  const cases: Array<[string, string]> = [
    ['Popover', 'zIndex'],
    ['Menu', 'zIndex'],
    ['Tooltip', 'zIndex'],
    ['Autocomplete', 'comboboxProps'],
    ['Select', 'comboboxProps'],
    ['MultiSelect', 'comboboxProps'],
    ['DatePickerInput', 'popoverProps'],
  ]

  it.each(cases)('lifts %s above the modal layer', (name, prop) => {
    const defaults = components[name]?.defaultProps
    expect(defaults, `${name} has no theme defaults`).toBeDefined()
    const value = defaults![prop]
    const zIndex = prop === 'zIndex' ? value : (value as { zIndex: number }).zIndex
    expect(zIndex, `${name}.${prop} does not carry a z-index`).toBe(Z_POPOVER)
    expect(zIndex as number).toBeGreaterThan(Z_MODAL)
  })
})
