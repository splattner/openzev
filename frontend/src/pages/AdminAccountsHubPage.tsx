import { useTranslation } from 'react-i18next'
import { Tabs } from '@mantine/core'
import { useNavigate } from 'react-router-dom'
import { AdminAccountsPage } from './AdminAccountsPage'
import { AdminApiKeysPage } from './AdminApiKeysPage'

/**
 * Admin Accounts hub (nav-regroup phase 3, spec §6): users, roles and
 * impersonation plus the admin API-key management that used to be a separate
 * nav item, gathered into tabs. Tab = route; /admin/accounts and
 * /admin/api-keys stay as aliases.
 */

export type AdminAccountsTab = 'users' | 'api-keys'



export function AdminAccountsHubPage({ tab = 'users' }: { tab?: AdminAccountsTab }) {
    const { t } = useTranslation()
    const navigate = useNavigate()

    function handleTabChange(value: string | null) {
        navigate(`/admin/accounts/${value ?? 'users'}`, { replace: true })
    }

    return (
        <div className="page-stack">
            <header>
                <p className="eyebrow">{t('nav.platformScope')}</p>
                <h2>{t('pages.adminAccounts.title')}</h2>
                <p className="muted">{t('pages.adminAccounts.description')}</p>
            </header>

            <Tabs
                classNames={{ root: 'app-tabs', list: 'app-tabs-list', tab: 'app-tabs-tab' }}
                value={tab}
                keepMounted={false}
                onChange={handleTabChange}
            >
                <Tabs.List aria-label={t('pages.adminAccounts.title')}>
                    <Tabs.Tab value="users">{t('pages.adminAccounts.tabs.users')}</Tabs.Tab>
                    <Tabs.Tab value="api-keys">{t('pages.adminAccounts.tabs.apiKeys')}</Tabs.Tab>
                </Tabs.List>

                <Tabs.Panel value="users">
                    <AdminAccountsPage embedded />
                </Tabs.Panel>
                <Tabs.Panel value="api-keys">
                    <AdminApiKeysPage embedded />
                </Tabs.Panel>
            </Tabs>
        </div>
    )
}
