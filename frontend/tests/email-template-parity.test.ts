import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { join, resolve } from 'node:path'
import { EMAIL_TEMPLATE_KEYS } from '../src/lib/emailTemplateFields'
import { en } from '../src/i18n/locales/en'

/** Keep frontend email routes aligned with backend templates and translations. */

const ROOT = resolve(__dirname, '..', '..')
const MODELS = join(ROOT, 'backend', 'invoices', 'models.py')
const FIELD_CATALOG_DATA = join(ROOT, 'backend', 'invoices', 'field_catalog_data.py')

/** The keys of `EMAIL_TEMPLATE_DEFAULTS`, read out of the backend source. */
function backendTemplateKeys(): string[] {
    const source = readFileSync(MODELS, 'utf8')
    const start = source.indexOf('EMAIL_TEMPLATE_DEFAULTS = {')
    expect(start, `EMAIL_TEMPLATE_DEFAULTS not found in ${MODELS}`).toBeGreaterThan(-1)

    // The top-level closing brace ends the dictionary.
    const end = source.indexOf('\n}', start)
    const block = source.slice(start, end)

    return [...block.matchAll(/^\s{4}"([a-z_]+)":/gm)].map((match) => match[1])
}

/** Read description keys from the backend field catalogs. */
function backendTemplateFieldDescriptionKeys(): string[] {
    const source = readFileSync(FIELD_CATALOG_DATA, 'utf8')
    return [...source.matchAll(/"description_key":\s*"(admin\.(?:fields|emailTemplates\.fields)\.[A-Za-z0-9_]+)"/g)]
        .map((match) => match[1])
}

describe('admin email templates', () => {
    const keys = backendTemplateKeys()

    it('finds the backend templates at all', () => {
        // Fail if the backend constant changes shape and yields no keys.
        expect(keys.length).toBeGreaterThanOrEqual(4)
        expect(keys).toContain('invoice_email')
    })

    it('offers a route for every backend template', () => {
        expect([...EMAIL_TEMPLATE_KEYS].sort()).toEqual([...keys].sort())
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

    it('translates every email field description the backend can return', () => {
        const fields = en.admin.emailTemplates.fields as Record<string, string>
        const descriptionKeys = backendTemplateFieldDescriptionKeys()
            .filter((key) => key.startsWith('admin.emailTemplates.fields.'))
        expect(descriptionKeys.length).toBeGreaterThan(0)
        for (const descriptionKey of descriptionKeys) {
            const name = descriptionKey.replace('admin.emailTemplates.fields.', '')
            expect(fields[name], `missing ${descriptionKey}`).toBeTruthy()
        }
    })

    it('translates every PDF field description the backend can return', () => {
        const fields = en.admin.fields as Record<string, string>
        const descriptionKeys = backendTemplateFieldDescriptionKeys()
            .filter((key) => key.startsWith('admin.fields.'))
        expect(descriptionKeys.length).toBeGreaterThan(0)
        for (const descriptionKey of descriptionKeys) {
            const name = descriptionKey.replace('admin.fields.', '')
            expect(fields[name], `missing ${descriptionKey}`).toBeTruthy()
        }
    })
})
