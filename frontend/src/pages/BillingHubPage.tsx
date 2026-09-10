import { useManagedZev } from '../lib/managedZev'
import { Tabs } from '@mantine/core'
import { useTranslation } from 'react-i18next'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { InvoicesPage } from './InvoicesPage'
import { BillingEmailsPage } from './BillingEmailsPage'
import { BillingStatementsPage } from './BillingStatementsPage'

/**
 * Billing hub: tabs are routes — Invoices · Email delivery · Annual
 * statements — each with its own guard. Period work lives on Overview.
 * The shell renders the hub header and the shared tab strip; tab bodies are
 * the existing components (InvoicesPage) or new tab pages riding the
 * phase-2 readiness/email-status payloads.
 */

export type BillingTab = 'invoices' | 'emails' | 'statements'

export function BillingHubPage({ tab }: { tab: BillingTab }) {
    const { t } = useTranslation()
    const navigate = useNavigate()
    const { selectedZev } = useManagedZev()
    const [searchParams] = useSearchParams()

    // Tab switches navigate to the tab's route, preserving the query (e.g.
    // period_start/period_end deep links); replace keeps same-hub tab
    // switches out of back-button history.
    function handleTabChange(value: string | null) {
        const qs = searchParams.toString()
        navigate(`/billing/${value ?? 'invoices'}${qs ? `?${qs}` : ''}`, { replace: true })
    }

    return (
        <div className="page-stack">
            <header>
                {selectedZev?.name ? <p className="eyebrow">{selectedZev.name}</p> : null}
                <h2>{t('nav.billing')}</h2>
                <p className="muted">{t('pages.billingHub.description')}</p>
            </header>

            <Tabs
                classNames={{ root: 'app-tabs', list: 'app-tabs-list', tab: 'app-tabs-tab' }}
                value={tab}
                keepMounted={false}
                onChange={handleTabChange}
            >
                <Tabs.List aria-label={t('nav.billing')}>
                    <Tabs.Tab value="invoices">{t('pages.billingHub.tabs.invoices')}</Tabs.Tab>
                    <Tabs.Tab value="emails">{t('pages.billingHub.tabs.emails')}</Tabs.Tab>
                    <Tabs.Tab value="statements">{t('pages.billingHub.tabs.statements')}</Tabs.Tab>
                </Tabs.List>

                <Tabs.Panel value="invoices">
                    <InvoicesPage embedded />
                </Tabs.Panel>
                <Tabs.Panel value="emails">
                    <BillingEmailsPage />
                </Tabs.Panel>
                <Tabs.Panel value="statements">
                    <BillingStatementsPage />
                </Tabs.Panel>
            </Tabs>
        </div>
    )
}
