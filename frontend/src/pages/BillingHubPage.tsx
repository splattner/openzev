import { useManagedZev } from '../lib/managedZev'
import { AppTabs } from '../components/AppTabs'
import { useTranslation } from 'react-i18next'
import { usePageNavigation } from '../lib/usePageNavigation'
import { InvoicesContent } from './InvoicesPage'
import { BillingEmailsPage } from './BillingEmailsPage'
import { PageHeader } from '../components/PageHeader'
import { useScopeNote } from '../lib/communityAccess'

/**
 * Billing hub: tabs are routes — Invoices · Email delivery — each with its
 * own guard. The hub owns the header and tabs; each body owns its queries and guards.
 */

export type BillingTab = 'invoices' | 'emails'

export function BillingHubPage({ tab }: { tab: BillingTab }) {
    const { t } = useTranslation()
    const scopeNote = useScopeNote()
    const { navigateTab } = usePageNavigation()
    const { selectedZev } = useManagedZev()

    // Tab switches navigate to the tab's route, preserving the query (e.g.
    // period_start/period_end deep links); replace keeps same-hub tab
    // switches out of back-button history.
    function handleTabChange(value: string | null) {
        navigateTab(`/billing/${value === 'emails' ? 'emails' : 'invoices'}`)
    }

    return (
        <div className="page-stack">
            <PageHeader
                eyebrow={selectedZev?.name}
                communitySwitch
                scopeNote={scopeNote}
                title={t('nav.billing')}
                description={t('pages.billingHub.description')}
            />

            <AppTabs
                value={tab}
                keepMounted={false}
                onChange={handleTabChange}
            >
                <AppTabs.List aria-label={t('nav.billing')}>
                    <AppTabs.Tab value="invoices">{t('pages.billingHub.tabs.invoices')}</AppTabs.Tab>
                    <AppTabs.Tab value="emails">{t('pages.billingHub.tabs.emails')}</AppTabs.Tab>
                </AppTabs.List>

                <AppTabs.Panel value="invoices">
                    <InvoicesContent />
                </AppTabs.Panel>
                <AppTabs.Panel value="emails">
                    <BillingEmailsPage />
                </AppTabs.Panel>
            </AppTabs>
        </div>
    )
}
