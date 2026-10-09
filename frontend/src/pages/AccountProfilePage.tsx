import { useEffect } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { usePageNavigation } from '../lib/usePageNavigation'
import { Tabs } from '@mantine/core'
import { useTranslation } from 'react-i18next'
import { useAuth } from '../lib/auth'
import { useEnergyDataEligibility } from '../lib/supplementary'
import { useToast } from '../lib/toast'
import { queryKeys } from '../lib/api/queryKeys'
import { ConfirmDialog, useConfirmDialog } from '../components/ConfirmDialog'
import { ACCOUNT_TABS, resolveAccountTab, type AccountTab } from '../features/account/accountTabs'
import { ApiKeysSection } from '../features/account/ApiKeysSection'
import { EnergyDataSection } from '../features/account/EnergyDataSection'
import { LinkedAccountsCard } from '../features/account/LinkedAccountsCard'
import { PasswordCard } from '../features/account/PasswordCard'
import { ProfileCard } from '../features/account/ProfileCard'
import { SessionsCard } from '../features/account/SessionsCard'
import { TwoFactorSection } from '../features/account/TwoFactorSection'
import { PageHeader } from '../components/PageHeader'

/**
 * The signed-in user's own account, in three tabs: Profile (who you are),
 * Security (how you sign in: password, two-factor, linked providers) and API
 * keys (scripted access). A fourth, Energy data, appears for a participant who
 * holds a metering point with generation behind it while the feature is on. The tab lives in `?tab=` so a link — the enrolment
 * gate's, an OAuth return — can land on the right one.
 */
export function AccountProfilePage() {
    const { t } = useTranslation()
    const { searchParams, updateParams } = usePageNavigation()
    const { user } = useAuth()
    const { pushToast } = useToast()
    const queryClient = useQueryClient()
    const { dialog, confirm, handleConfirm, handleCancel, isLoading: dialogLoading } = useConfirmDialog()

    const energyData = useEnergyDataEligibility()
    // The tab is derived from the URL on every render, so a link to Energy data shows Profile while the
    // check runs and switches over as soon as the tab exists.
    const activeTab = resolveAccountTab(searchParams, {
        mustChangePassword: Boolean(user?.must_change_password),
        energyDataAvailable: energyData.tabAvailable,
    })

    // Handle oauth_linked / oauth_error query params (the OAuth link callback
    // redirects here). resolveAccountTab has already opened Security for them.
    useEffect(() => {
        const linked = searchParams.get('oauth_linked')
        const oauthError = searchParams.get('oauth_error')
        if (linked === 'true') {
            void queryClient.invalidateQueries({ queryKey: queryKeys.auth.socialAccounts() })
            pushToast(t('account.linkSuccess'), 'success')
            updateParams(params => {
                params.delete('oauth_linked')
                params.set('tab', 'security')
            })
        } else if (oauthError) {
            pushToast(t('auth.oauth.errors.generic', { code: oauthError }), 'error')
            updateParams(params => {
                params.delete('oauth_error')
                params.set('tab', 'security')
            })
        }
    // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [])

    function setActiveTab(tab: AccountTab) {
        updateParams(params => params.set('tab', tab), { replace: false })
    }

    return (
        <div className="page-stack">
            <PageHeader title={t('account.title')} description={t('account.titleDescription')} />

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
                <Tabs.List aria-label={t('account.title')}>
                    <Tabs.Tab value="profile">{t('account.tabs.profile')}</Tabs.Tab>
                    <Tabs.Tab value="security">{t('account.tabs.security')}</Tabs.Tab>
                    <Tabs.Tab value="api-keys">{t('account.tabs.apiKeys')}</Tabs.Tab>
                    {energyData.tabAvailable && <Tabs.Tab value="energy-data">{t('account.tabs.energyData')}</Tabs.Tab>}
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
                            <SessionsCard
                                onRevoke={(onConfirm) =>
                                    confirm({
                                        title: t('account.sessions.confirmTitle'),
                                        message: t('account.sessions.confirmMessage'),
                                        confirmText: t('account.sessions.signOutOthers'),
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

                {energyData.tabAvailable && (
                    <Tabs.Panel value="energy-data">
                        <div style={{ maxWidth: '1000px' }}>
                            <EnergyDataSection />
                        </div>
                    </Tabs.Panel>
                )}
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
