import { useTranslation } from 'react-i18next'
import { AppTabs } from '../components/AppTabs'
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

            <AppTabs
                value={tab}
                keepMounted={false}
                onChange={handleTabChange}
            >
                <AppTabs.List aria-label={t('pages.adminAccounts.title')}>
                    <AppTabs.Tab value="users">{t('pages.adminAccounts.tabs.users')}</AppTabs.Tab>
                    <AppTabs.Tab value="tokens">{t('pages.adminAccounts.tabs.tokens')}</AppTabs.Tab>
                </AppTabs.List>

                <AppTabs.Panel value="users">
                    <AdminAccountsPage embedded />
                </AppTabs.Panel>
                <AppTabs.Panel value="tokens">
                    <AdminCredentialsPage embedded />
                </AppTabs.Panel>
            </AppTabs>
        </div>
    )
}
