import { useEffect, useRef } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { usePageNavigation } from '../lib/usePageNavigation'
import { AppTabs } from '../components/AppTabs'
import { useTranslation } from 'react-i18next'
import { useAuth } from '../lib/auth'
import { useToast } from '../lib/toast'
import { queryKeys } from '../lib/api/queryKeys'
import { ConfirmDialog, useConfirmDialog } from '../components/ConfirmDialog'
import { ACCOUNT_TABS, resolveAccountTab, type AccountTab } from '../features/account/accountTabs'
import { TokensSection } from '../features/account/TokensSection'
import { LinkedAccountsCard } from '../features/account/LinkedAccountsCard'
import { PasswordCard } from '../features/account/PasswordCard'
import { ProfileCard } from '../features/account/ProfileCard'
import { SessionsCard } from '../features/account/SessionsCard'
import { TwoFactorSection } from '../features/account/TwoFactorSection'
import { PageHeader } from '../components/PageHeader'
import { Notice } from '../components/Notice'

/**
 * The signed-in user's own account, in three tabs: Profile (who you are),
 * Security (how you sign in: password, two-factor, linked providers) and
 * Tokens & keys (API keys, analytics tokens, energy data tokens). The tab lives in `?tab=` so a link — the enrolment
 * gate's, an OAuth return — can land on the right one.
 */
export function AccountProfilePage() {
    const { t } = useTranslation()
    const { searchParams, updateParams } = usePageNavigation()
    const { user, isImpersonating } = useAuth()
    const { pushToast } = useToast()
    const queryClient = useQueryClient()
    const oauthHandled = useRef(false)
    const { dialog, confirm, handleConfirm, handleCancel, isLoading: dialogLoading } = useConfirmDialog()

    const activeTab = resolveAccountTab(searchParams, { mustChangePassword: Boolean(user?.must_change_password) })

    // Handle oauth_linked / oauth_error query params (the OAuth link callback
    // redirects here). resolveAccountTab has already opened Security for them.
    useEffect(() => {
        if (oauthHandled.current) return
        oauthHandled.current = true
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
            pushToast(oauthError === 'email_not_verified'
                ? t('account.linkEmailNotVerified')
                : t('auth.oauth.errors.generic', { code: oauthError }), 'error')
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
            {isImpersonating && <Notice tone="warning">{t('account.impersonationRestrictions')}</Notice>}

            {user?.must_change_password && (
                <div className="warning-banner" role="alert" style={{ display: 'grid', gap: '0.35rem', maxWidth: '1000px' }}>
                    <strong>{t('account.passwordChangeRequired')}</strong>
                    <p style={{ margin: 0 }}>{t('account.passwordChangeRequiredDescription')}</p>
                </div>
            )}

            <AppTabs
                value={activeTab}
                onChange={(value) => setActiveTab(ACCOUNT_TABS.includes(value as AccountTab) ? (value as AccountTab) : 'profile')}
                // Panels stay mounted (hidden) on purpose: recovery codes and a freshly
                // created API key are shown exactly once, in component state, and would
                // be lost the moment the user clicked another tab.
                keepMounted
            >
                <AppTabs.List aria-label={t('account.title')}>
                    <AppTabs.Tab value="profile">{t('account.tabs.profile')}</AppTabs.Tab>
                    <AppTabs.Tab value="security">{t('account.tabs.security')}</AppTabs.Tab>
                    <AppTabs.Tab value="tokens">{t('account.tabs.tokens')}</AppTabs.Tab>
                </AppTabs.List>

                <AppTabs.Panel value="profile">
                    <div style={{ maxWidth: '520px' }}>
                        <ProfileCard />
                    </div>
                </AppTabs.Panel>

                <AppTabs.Panel value="security">
                    <fieldset className="form-grid" disabled={isImpersonating} aria-label={t('account.tabs.security')} style={{ gap: '2rem', maxWidth: '1000px', alignItems: 'start' }}>
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
                    </fieldset>
                </AppTabs.Panel>

                <AppTabs.Panel value="tokens">
                    <div style={{ maxWidth: '1000px' }}>
                        <TokensSection
                            onRevoke={({ name, kind, onConfirm }) =>
                                confirm({
                                    title: t('account.tokens.revokeConfirmTitle'),
                                    message: t(`account.tokens.revokeConfirmMessage.${kind}`, { name }),
                                    confirmText: t('account.apiKeys.revoke'),
                                    isDangerous: true,
                                    onConfirm,
                                })
                            }
                            onRotate={({ name, onConfirm }) =>
                                confirm({
                                    title: t('account.tokens.rotateConfirmTitle'),
                                    message: t('account.tokens.rotateConfirmMessage', { name }),
                                    confirmText: t('account.tokens.rotate'),
                                    isDangerous: false,
                                    onConfirm,
                                })
                            }
                        />
                    </div>
                </AppTabs.Panel>
            </AppTabs>

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
