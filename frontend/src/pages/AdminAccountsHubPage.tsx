import { useTranslation } from 'react-i18next'
import { Tabs } from '@mantine/core'
import { usePageNavigation } from '../lib/usePageNavigation'
import { AdminAccountsPage } from './AdminAccountsPage'
import { AdminCredentialsPage } from './AdminCredentialsPage'
import { PageHeader } from '../components/PageHeader'

/**
 * Admin Accounts hub (nav-regroup phase 3, spec §6): users, roles and
 * impersonation plus Tokens & keys (API keys, analytics tokens, energy data
 * tokens) that used to be a separate nav item, gathered into tabs. Tab = route;
 * /admin/accounts, /admin/accounts/api-keys and /admin/api-keys stay as aliases.
 */

export type AdminAccountsTab = 'users' | 'tokens'



export function AdminAccountsHubPage({ tab = 'users' }: { tab?: AdminAccountsTab }) {
    const { t } = useTranslation()
    const { navigateTab } = usePageNavigation()

    function handleTabChange(value: string | null) {
        navigateTab(`/admin/accounts/${value === 'tokens' ? 'tokens' : 'users'}`)
    }

    return (
        <div className="page-stack">
            <PageHeader
                eyebrow={t('nav.platformScope')}
                title={t('pages.adminAccounts.title')}
                description={t('pages.adminAccounts.description')}
            />

            <Tabs
                classNames={{ root: 'app-tabs', list: 'app-tabs-list', tab: 'app-tabs-tab' }}
                value={tab}
                keepMounted={false}
                onChange={handleTabChange}
            >
                <Tabs.List aria-label={t('pages.adminAccounts.title')}>
                    <Tabs.Tab value="users">{t('pages.adminAccounts.tabs.users')}</Tabs.Tab>
                    <Tabs.Tab value="tokens">{t('pages.adminAccounts.tabs.tokens')}</Tabs.Tab>
                </Tabs.List>

                <Tabs.Panel value="users">
                    <AdminAccountsPage embedded />
                </Tabs.Panel>
                <Tabs.Panel value="tokens">
                    <AdminCredentialsPage embedded />
                </Tabs.Panel>
            </Tabs>
        </div>
    )
}
