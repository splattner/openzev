import type { InputFactory, InputProps, MantineTheme, MantineThemeOverride } from '@mantine/core'
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
 *
 * Single-line fields share the field-token dimensions with native controls
 * (`design/tokens.json` → `fields`): the `Input` vars below set the box
 * height, value size, and radius from the same CSS variables the native
 * text-like input rule consumes, at every size — field sizing must not be
 * solved with per-field `size` props. `size` still drives the calendar,
 * dropdown options, and section icons, which keep their own sizing.
 * `InputWrapper` owns the label → input → description → error order plus
 * label/help typography. Only the default, neutral border is normalized;
 * Mantine retains ownership of focus, error, success, and disabled states.
 */
const overlay = { zIndex: Z_POPOVER }

const INPUT_WRAPPER_ORDER: ('label' | 'input' | 'description' | 'error')[] = [
  'label',
  'input',
  'description',
  'error',
]

/** Field-box vars; skipped for Textarea so multiline fields keep growing. */
const fieldInputVars = (_theme: MantineTheme, props: InputProps, ctx?: InputFactory['ctx']) => {
  if (props.multiline || props.__staticSelector === 'Textarea') return {}

  const hasStateBorder = (props.error && props.withErrorStyles !== false)
    || (props.success && props.withSuccessStyles !== false)
  return {
    wrapper: {
      '--input-height': 'var(--field-height)',
      '--input-fz': 'var(--field-font-size)',
      '--input-radius': 'var(--field-radius)',
      '--input-padding': props.variant === 'unstyled' ? undefined : 'var(--field-padding-inline)',
      '--input-margin-top': ctx?.offsetTop ? 'var(--field-gap)' : undefined,
      '--input-margin-bottom': ctx?.offsetBottom ? 'var(--field-gap)' : undefined,
      // Error/success borders are set on this same wrapper. An unconditional
      // inline variable would mask them, even with the native CSS fixed.
      '--input-bd': !hasStateBorder && (!props.variant || props.variant === 'default')
        ? 'var(--border-default)'
        : undefined,
    },
  }
}

export const mantineTheme: MantineThemeOverride = {
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
    Input: {
      vars: fieldInputVars,
      styles: (_theme: MantineTheme, props: InputProps) => props.multiline || props.__staticSelector === 'Textarea'
        ? {}
        : { input: { lineHeight: 'var(--field-line-height)' } },
    },
    InputWrapper: {
      defaultProps: { inputWrapperOrder: INPUT_WRAPPER_ORDER },
      vars: () => ({
        label: { '--input-label-size': 'var(--field-label-size)' },
        description: { '--input-description-size': 'var(--field-help-size)' },
        error: { '--input-error-size': 'var(--field-help-size)' },
      }),
      styles: {
        label: { fontWeight: 'var(--field-label-weight)', marginBottom: 'var(--field-gap)' },
        description: { color: 'var(--text-muted)', lineHeight: 'var(--field-line-height)' },
      },
    },
  },
}
