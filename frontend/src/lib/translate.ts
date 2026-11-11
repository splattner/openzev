/**
 * The shape of `t` that helpers outside React components accept.
 *
 * Declared as two overloads rather than `(key, options?) => string`: i18next's
 * `TFunction` rejects an optional `options` parameter, so the optional form
 * would not accept `t` itself.
 */
export type Translate = {
    (key: string): string
    (key: string, options: Record<string, unknown>): string
}
