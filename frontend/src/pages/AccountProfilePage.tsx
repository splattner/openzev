import { useEffect } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { useSearchParams } from 'react-router-dom'
import { Tabs } from '@mantine/core'
import { useTranslation } from 'react-i18next'
import { useAuth } from '../lib/auth'
import { useToast } from '../lib/toast'
import { queryKeys } from '../lib/api/queryKeys'
import { ConfirmDialog, useConfirmDialog } from '../components/ConfirmDialog'
import { ACCOUNT_TABS, resolveAccountTab, type AccountTab } from '../features/account/accountTabs'
import { ApiKeysSection } from '../features/account/ApiKeysSection'
import { LinkedAccountsCard } from '../features/account/LinkedAccountsCard'
import { PasswordCard } from '../features/account/PasswordCard'
import { ProfileCard } from '../features/account/ProfileCard'
import { TwoFactorSection } from '../features/account/TwoFactorSection'

/**
 * The signed-in user's own account, in three tabs: Profile (who you are),
 * Security (how you sign in: password, two-factor, linked providers) and API
 * keys (scripted access). The tab lives in `?tab=` so a link — the enrolment
 * gate's, an OAuth return — can land on the right one.
 */
export function AccountProfilePage() {
    const { t } = useTranslation()
    const [searchParams, setSearchParams] = useSearchParams()
    const { user } = useAuth()
    const { pushToast } = useToast()
    const queryClient = useQueryClient()
    const { dialog, confirm, handleConfirm, handleCancel, isLoading: dialogLoading } = useConfirmDialog()

    const activeTab = resolveAccountTab(searchParams, { mustChangePassword: Boolean(user?.must_change_password) })

    // Handle oauth_linked / oauth_error query params (the OAuth link callback
    // redirects here). resolveAccountTab has already opened Security for them.
    useEffect(() => {
        const linked = searchParams.get('oauth_linked')
        const oauthError = searchParams.get('oauth_error')
        if (linked === 'true') {
            void queryClient.invalidateQueries({ queryKey: queryKeys.auth.socialAccounts() })
            pushToast(t('account.linkSuccess'), 'success')
            const next = new URLSearchParams(searchParams)
            next.delete('oauth_linked')
            next.set('tab', 'security')
            setSearchParams(next, { replace: true })
        } else if (oauthError) {
            pushToast(t('auth.oauth.errors.generic', { code: oauthError }), 'error')
            const next = new URLSearchParams(searchParams)
            next.delete('oauth_error')
            next.set('tab', 'security')
            setSearchParams(next, { replace: true })
        }
    // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [])

    function setActiveTab(tab: AccountTab) {
        setSearchParams({ tab })
    }

    return (
        <div className="page-stack">
            <header>
                <h2>{t('account.title')}</h2>
                <p className="muted">{t('account.titleDescription')}</p>
            </header>

            {user?.must_change_password && (
                <div className="warning-banner" role="alert" style={{ display: 'grid', gap: '0.35rem', maxWidth: '1000px' }}>
                    <strong>{t('account.passwordChangeRequired')}</strong>
                    <p style={{ margin: 0 }}>{t('account.passwordChangeRequiredDescription')}</p>
                </div>
            )}

            <Tabs
                classNames={{ root: 'app-tabs', list: 'app-tabs-list', tab: 'app-tabs-tab' }}
                value={activeTab}
                onChange={(value) => setActiveTab(ACCOUNT_TABS.includes(value as AccountTab) ? (value as AccountTab) : 'profile')}
                // Panels stay mounted (hidden) on purpose: recovery codes and a freshly
                // created API key are shown exactly once, in component state, and would
                // be lost the moment the user clicked another tab.
                keepMounted
            >
                <Tabs.List>
                    <Tabs.Tab value="profile">{t('account.tabs.profile')}</Tabs.Tab>
                    <Tabs.Tab value="security">{t('account.tabs.security')}</Tabs.Tab>
                    <Tabs.Tab value="api-keys">{t('account.tabs.apiKeys')}</Tabs.Tab>
                </Tabs.List>

                <Tabs.Panel value="profile">
                    <div style={{ maxWidth: '520px' }}>
                        <ProfileCard />
                    </div>
                </Tabs.Panel>

                <Tabs.Panel value="security">
                    <div className="form-grid" style={{ gap: '2rem', maxWidth: '1000px', alignItems: 'start' }}>
                        <div style={{ display: 'grid', gap: '2rem' }}>
                            <PasswordCard />
                            <LinkedAccountsCard
                                onUnlink={({ provider, onConfirm }) =>
                                    confirm({
                                        title: t('account.unlinkConfirmTitle'),
                                        message: t('account.unlinkConfirmMessage', { provider }),
                                        confirmText: t('account.unlinkAccount'),
                                        isDangerous: true,
                                        onConfirm,
                                    })
                                }
                            />
                        </div>
                        <TwoFactorSection
                            onRemoveTotp={(onConfirm) =>
                                confirm({
                                    title: t('account.mfa.removeConfirmTitle'),
                                    message: t('account.mfa.removeConfirmMessage'),
                                    confirmText: t('account.mfa.remove'),
                                    isDangerous: true,
                                    onConfirm,
                                })
                            }
                            onRemovePasskey={(passkey, onConfirm) =>
                                confirm({
                                    title: t('account.passkeys.removeConfirmTitle'),
                                    message: t('account.passkeys.removeConfirmMessage', { name: passkey.name }),
                                    confirmText: t('account.mfa.remove'),
                                    isDangerous: true,
                                    onConfirm,
                                })
                            }
                        />
                    </div>
                </Tabs.Panel>

                <Tabs.Panel value="api-keys">
                    <div style={{ maxWidth: '1000px' }}>
                        <ApiKeysSection
                            onRevoke={({ name, onConfirm }) =>
                                confirm({
                                    title: t('account.apiKeys.revokeConfirmTitle'),
                                    message: t('account.apiKeys.revokeConfirmMessage', { name }),
                                    confirmText: t('account.apiKeys.revoke'),
                                    isDangerous: true,
                                    onConfirm,
                                })
                            }
                        />
                    </div>
                </Tabs.Panel>
            </Tabs>

            {dialog && (
                <ConfirmDialog
                    {...dialog}
                    isLoading={dialogLoading}
                    onConfirm={handleConfirm}
                    onCancel={handleCancel}
                />
            )}
        </div>
    )
}
