import { useTranslation } from 'react-i18next'
import { AppTabs } from '../components/AppTabs'
import { usePageNavigation } from '../lib/usePageNavigation'
import { AdminDashboardPage } from './AdminDashboardPage'
import { ZevListPage } from './ZevListPage'
import { AdminInvoicesContent } from './AdminInvoicesPage'
import { AuditLogsPage } from './AdminAuditLogsPage'
import { AdminSystemHealthPanel } from './AdminSystemHealthPanel'
import { AdminDynamicSourcesPanel } from './AdminDynamicSourcesPanel'
import { PageHeader } from '../components/PageHeader'

/**
 * Admin Overview hub (nav-regroup phase 3, spec §6): the former admin landing
 * page plus the cross-tenant admin views that used to be separate nav items —
 * ZEVs, all invoices, the platform audit log, and a new System health tab —
 * gathered into tabs. Tab = route (deep-linkable), legacy /admin/* URLs stay
 * as aliases.
 */

export type AdminOverviewTab = 'overview' | 'zevs' | 'invoices' | 'dynamic-sources' | 'audit' | 'health'

export function AdminOverviewHubPage({ tab = 'overview' }: { tab?: AdminOverviewTab }) {
    const { t } = useTranslation()
    const { navigateTab } = usePageNavigation()

    function handleTabChange(value: string | null) {
        navigateTab(`/admin/${value ?? 'overview'}`)
    }

    return (
        <div className="page-stack">
            <PageHeader
                eyebrow={t('nav.platformScope')}
                title={t('nav.adminOverview')}
                description={t(`pages.adminOverview.descriptions.${tab}`)}
            />

            <AppTabs
                value={tab}
                keepMounted={false}
                onChange={handleTabChange}
            >
                <AppTabs.List aria-label={t('nav.adminOverview')}>
                    <AppTabs.Tab value="overview">{t('pages.adminOverview.tabs.overview')}</AppTabs.Tab>
                    <AppTabs.Tab value="zevs">{t('nav.zevs')}</AppTabs.Tab>
                    <AppTabs.Tab value="invoices">{t('nav.adminInvoices')}</AppTabs.Tab>
                    <AppTabs.Tab value="dynamic-sources">{t('pages.dynamicSources.tab')}</AppTabs.Tab>
                    <AppTabs.Tab value="audit">{t('nav.adminAuditLogs')}</AppTabs.Tab>
                    <AppTabs.Tab value="health">{t('pages.adminOverview.tabs.health')}</AppTabs.Tab>
                </AppTabs.List>

                <AppTabs.Panel value="overview">
                    <AdminDashboardPage embedded />
                </AppTabs.Panel>
                <AppTabs.Panel value="zevs">
                    <ZevListPage embedded />
                </AppTabs.Panel>
                <AppTabs.Panel value="invoices">
                    <AdminInvoicesContent />
                </AppTabs.Panel>
                <AppTabs.Panel value="dynamic-sources">
                    <AdminDynamicSourcesPanel />
                </AppTabs.Panel>
                <AppTabs.Panel value="audit">
                    {/* Platform-wide audit log — the scope is locked to 'admin'
                        inside the component and never merges with ZEV logs. */}
                    <AuditLogsPage scope="admin" embedded />
                </AppTabs.Panel>
                <AppTabs.Panel value="health">
                    <AdminSystemHealthPanel />
                </AppTabs.Panel>
            </AppTabs>
        </div>
    )
}
