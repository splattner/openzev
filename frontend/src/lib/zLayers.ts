/**
 * The app's stacking order, in one place.
 *
 * Mantine portals its overlays to `document.body` with its own scale — a
 * popover defaults to 300, a modal to 200 — while our `FormModal` is a plain
 * fixed div at 1000. A Mantine dropdown opened *inside* one of our modals
 * therefore rendered behind it: the date picker in the create-tariff modal
 * could be opened but not seen, so the field could not be filled in.
 *
 * Anything that opens on top of a modal has to outrank it, which means these
 * values are only correct together. Mantine is told about `POPOVER` through
 * component defaults in `main.tsx`; the CSS side (`.toast-stack`) carries a
 * comment pointing back here.
 */
export const Z_MODAL = 1000

/** Dropdowns, date pickers and menus — must clear a modal they open inside. */
export const Z_POPOVER = 1100

/** Feedback outranks everything, including a dropdown left open. */
export const Z_TOAST = 1200
