import { generatedTheme } from '../styles/generatedTheme'
import { Z_POPOVER } from './zLayers'

/**
 * Mantine theme: the generated design tokens, plus the overlay stacking fix.
 *
 * Every Mantine overlay that can be opened from inside a `FormModal` has to be
 * lifted above it. Mantine's own default is 300, our modal is at 1000, and
 * both are portalled to `document.body` — so a dropdown opened inside a modal
 * rendered behind the thing that opened it, which is how the create-tariff
 * date picker became impossible to use.
 *
 * Set here rather than at each call site so a Select or Menu added later
 * inherits it instead of quietly reintroducing the bug. `z-layers.test.ts`
 * holds the list to this rule.
 *
 * Colors live in styles/generatedTheme.ts (generated from design/tokens.json),
 * never here. `fontFamily` must stay in the generated theme: Mantine's
 * stylesheet sets `body { font-family }` and would otherwise override
 * index.css.
 */
const overlay = { zIndex: Z_POPOVER }

export const mantineTheme = {
  ...generatedTheme,
  defaultRadius: 'md',
  components: {
    Popover: { defaultProps: overlay },
    Menu: { defaultProps: overlay },
    Tooltip: { defaultProps: overlay },
    Autocomplete: { defaultProps: { comboboxProps: overlay } },
    Select: { defaultProps: { comboboxProps: overlay } },
    MultiSelect: { defaultProps: { comboboxProps: overlay } },
    DatePickerInput: { defaultProps: { popoverProps: overlay } },
  },
} as const
