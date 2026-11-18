import { describe, it, expect } from 'vitest'
import { readFileSync, readdirSync } from 'node:fs'
import { join, resolve } from 'node:path'

/** Source conventions; rendered heading counts and scope behavior have browser tests. */
const SRC = resolve(__dirname, '../src')
const PAGES = join(SRC, 'pages')

/** Embedded bodies whose parent owns the page header. */
const EMBEDDED_PAGES = [
    'AdminDynamicSourcesPanel.tsx',
    'AdminInvoicesPage.tsx',
    'AdminSystemHealthPanel.tsx',
    'BillingEmailsPage.tsx',
    'BillingPeriodsPage.tsx',
    'TariffsPage.tsx',
    'TariffProgressionPage.tsx',
]

/** Single empty-state card for accounts without access; no page header of its own. */
const HEADERLESS_PAGES = ['GuestHomePage.tsx']

/** Standalone pages outside the app shell; they may declare their own document heading. */
const PUBLIC_PAGES = [
    'ConfirmEmailChangePage.tsx', 'LoginPage.tsx', 'MagicSignInPage.tsx', 'NotFoundPage.tsx',
    'OAuthCallbackPage.tsx', 'ParticipantOnboardingPage.tsx', 'PublicInvoicePage.tsx', 'VerifyEmailPage.tsx',
]

function sourceFiles(dir: string): string[] {
    return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
        const path = join(dir, entry.name)
        if (entry.isDirectory()) return sourceFiles(path)
        return /\.tsx?$/.test(entry.name) ? [path] : []
    })
}

function rel(path: string): string {
    return path.slice(SRC.length + 1)
}

describe('page anatomy', () => {
    it('uses PageHeader in standalone page-stack sources', () => {
        const offenders = readdirSync(PAGES)
            .filter((name) => name.endsWith('.tsx') && !EMBEDDED_PAGES.includes(name) && !HEADERLESS_PAGES.includes(name))
            .filter((name) => {
                const contents = readFileSync(join(PAGES, name), 'utf8')
                return /className="[^"]*\bpage-stack\b/.test(contents) && !/<PageHeader[\s>]/.test(contents)
            })
        expect(offenders).toEqual([])
    })

    it('titles the browser tab on every routed page', () => {
        // HomePage only dispatches to a titled page by relation.
        const offenders = readdirSync(PAGES)
            .filter((name) => name.endsWith('.tsx') && !EMBEDDED_PAGES.includes(name) && name !== 'HomePage.tsx')
            .filter((name) => {
                const contents = readFileSync(join(PAGES, name), 'utf8')
                return !/<PageHeader[\s>]/.test(contents) && !/\buseDocumentTitle\(/.test(contents)
            })
        expect(offenders).toEqual([])
    })

    it('declares level-one headings only in PageHeader outside the public pages', () => {
        const offenders = sourceFiles(SRC)
            .filter((file) => !PUBLIC_PAGES.includes(rel(file).split('/').pop() ?? ''))
            .filter((file) => rel(file) !== 'components/PageHeader.tsx')
            .filter((file) => /<h1[\s>]/.test(readFileSync(file, 'utf8')))
            .map(rel)
        expect(offenders).toEqual([])
    })

    it('uses ScopeGuard in the migrated scope-gated pages', () => {
        const SCOPE_PAGES = [
            'BillingEmailsPage.tsx',
            'DashboardPage.tsx',
            'InvoicesPage.tsx',
            'OverviewPage.tsx',
            'ReportsPage.tsx',
            'ZevSettingsPage.tsx',
        ]
        const missing = SCOPE_PAGES.filter(
            (name) => !/<ScopeGuard[\s>]/.test(readFileSync(join(PAGES, name), 'utf8')),
        )
        expect(missing).toEqual([])
    })
})
