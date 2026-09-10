import { useTranslation } from 'react-i18next'
import { Tabs } from '@mantine/core'
import { useNavigate } from 'react-router-dom'
import { AdminDashboardPage } from './AdminDashboardPage'
import { ZevListPage } from './ZevListPage'
import { AdminInvoicesPage } from './AdminInvoicesPage'
import { AuditLogsPage } from './AdminAuditLogsPage'
import { AdminSystemHealthPanel } from './AdminSystemHealthPanel'

/**
 * Admin Overview hub (nav-regroup phase 3, spec §6): the former admin landing
 * page plus the cross-tenant admin views that used to be separate nav items —
 * ZEVs, all invoices, the platform audit log, and a new System health tab —
 * gathered into tabs. Tab = route (deep-linkable), legacy /admin/* URLs stay
 * as aliases.
 */

export type AdminOverviewTab = 'overview' | 'zevs' | 'invoices' | 'audit' | 'health'



export function AdminOverviewHubPage({ tab = 'overview' }: { tab?: AdminOverviewTab }) {
    const { t } = useTranslation()
    const navigate = useNavigate()

    function handleTabChange(value: string | null) {
        navigate(`/admin/${value ?? 'overview'}`, { replace: true })
    }

    return (
        <div className="page-stack">
            <header>
                <p className="eyebrow">{t('nav.platformScope')}</p>
                <h2>{t('nav.adminOverview')}</h2>
                <p className="muted">{t('pages.adminOverview.description')}</p>
            </header>

            <Tabs
                classNames={{ root: 'app-tabs', list: 'app-tabs-list', tab: 'app-tabs-tab' }}
                value={tab}
                keepMounted={false}
                onChange={handleTabChange}
            >
                <Tabs.List aria-label={t('nav.adminOverview')}>
                    <Tabs.Tab value="overview">{t('pages.adminOverview.tabs.overview')}</Tabs.Tab>
                    <Tabs.Tab value="zevs">{t('nav.zevs')}</Tabs.Tab>
                    <Tabs.Tab value="invoices">{t('nav.adminInvoices')}</Tabs.Tab>
                    <Tabs.Tab value="audit">{t('nav.adminAuditLogs')}</Tabs.Tab>
                    <Tabs.Tab value="health">{t('pages.adminOverview.tabs.health')}</Tabs.Tab>
                </Tabs.List>

                <Tabs.Panel value="overview">
                    <AdminDashboardPage embedded />
                </Tabs.Panel>
                <Tabs.Panel value="zevs">
                    <ZevListPage embedded />
                </Tabs.Panel>
                <Tabs.Panel value="invoices">
                    <AdminInvoicesPage embedded />
                </Tabs.Panel>
                <Tabs.Panel value="audit">
                    {/* Platform-wide audit log — the scope is locked to 'admin'
                        inside the component and never merges with ZEV logs. */}
                    <AuditLogsPage scope="admin" embedded />
                </Tabs.Panel>
                <Tabs.Panel value="health">
                    <AdminSystemHealthPanel />
                </Tabs.Panel>
            </Tabs>
        </div>
    )
}
