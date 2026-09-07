import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { join, resolve } from 'node:path'
import { EMAIL_TEMPLATE_FIELDS } from '../src/lib/emailTemplateFields'
import { en } from '../src/i18n/locales/en'

/**
 * Every backend email template must be editable in the admin console.
 *
 * The backend serves all of `EMAIL_TEMPLATE_DEFAULTS` from
 * `GET /invoices/templates/email/`, but the admin page renders a hardcoded tab
 * list. Adding a template on the backend therefore *silently* produces one
 * nobody can edit: no type error, no failing request, no empty state — the tab
 * simply is not there. `participant_magic_link` shipped that way, editable by
 * API only, and nothing in the suite noticed.
 *
 * So the guard reads the backend constant directly rather than trusting a
 * checked-in copy of it. The same shape as `locale-parity`: one side is the
 * source of truth, the other must cover it.
 */

const ROOT = resolve(__dirname, '..', '..')
const MODELS = join(ROOT, 'backend', 'invoices', 'models.py')

/** The keys of `EMAIL_TEMPLATE_DEFAULTS`, read out of the backend source. */
function backendTemplateKeys(): string[] {
    const source = readFileSync(MODELS, 'utf8')
    const start = source.indexOf('EMAIL_TEMPLATE_DEFAULTS = {')
    expect(start, `EMAIL_TEMPLATE_DEFAULTS not found in ${MODELS}`).toBeGreaterThan(-1)

    // The literal ends at the first line that closes it at column zero, which
    // is unambiguous here because the whole dict is one indented block.
    const end = source.indexOf('\n}', start)
    const block = source.slice(start, end)

    return [...block.matchAll(/^\s{4}"([a-z_]+)":/gm)].map((match) => match[1])
}

describe('admin email templates', () => {
    const keys = backendTemplateKeys()

    it('finds the backend templates at all', () => {
        // Guards the parser itself: a refactor that moves or reshapes the
        // constant must fail loudly here rather than silently matching nothing
        // and passing every assertion below.
        expect(keys.length).toBeGreaterThanOrEqual(4)
        expect(keys).toContain('invoice_email')
    })

    it('offers a field reference for every backend template', () => {
        expect(Object.keys(EMAIL_TEMPLATE_FIELDS).sort()).toEqual([...keys].sort())
    })

    it('gives every template a tab label', () => {
        const page = readFileSync(
            join(ROOT, 'frontend', 'src', 'pages', 'AdminEmailTemplatesPage.tsx'),
            'utf8',
        )
        for (const key of keys) {
            expect(page, `no tab renders '${key}'`).toContain(`key: '${key}'`)
        }
    })

    it('translates every field description it references', () => {
        const fields = en.admin.emailTemplates.fields as Record<string, string>
        for (const [key, entries] of Object.entries(EMAIL_TEMPLATE_FIELDS)) {
            for (const entry of entries) {
                const name = entry.descriptionKey.replace('admin.emailTemplates.fields.', '')
                expect(fields[name], `${key} references a missing ${entry.descriptionKey}`)
                    .toBeTruthy()
            }
        }
    })
})
