import { useManagedZev } from '../lib/managedZev'
import { Tabs } from '@mantine/core'
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

            <Tabs
                classNames={{ root: 'app-tabs', list: 'app-tabs-list', tab: 'app-tabs-tab' }}
                value={tab}
                keepMounted={false}
                onChange={handleTabChange}
            >
                <Tabs.List aria-label={t('nav.billing')}>
                    <Tabs.Tab value="invoices">{t('pages.billingHub.tabs.invoices')}</Tabs.Tab>
                    <Tabs.Tab value="emails">{t('pages.billingHub.tabs.emails')}</Tabs.Tab>
                </Tabs.List>

                <Tabs.Panel value="invoices">
                    <InvoicesContent />
                </Tabs.Panel>
                <Tabs.Panel value="emails">
                    <BillingEmailsPage />
                </Tabs.Panel>
            </Tabs>
        </div>
    )
}
