import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useSearchParams } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { useAuth } from '../lib/auth'
import { useToast } from '../lib/toast'
import { changePassword, deleteSocialAccount, fetchOAuthProviders, fetchSocialAccounts, oauthLinkInitiate, updateProfile } from '../lib/api/auth'
import { queryKeys } from '../lib/api/queryKeys'
import { ConfirmDialog, useConfirmDialog } from '../components/ConfirmDialog'
import { ApiKeysSection } from '../features/account/ApiKeysSection'

export function AccountProfilePage() {
    const { t } = useTranslation()
    const [searchParams, setSearchParams] = useSearchParams()
    const { user, refreshUser } = useAuth()
    const { pushToast } = useToast()
    const queryClient = useQueryClient()
    const { dialog, confirm, handleConfirm, handleCancel, isLoading: dialogLoading } = useConfirmDialog()

    const socialAccountsQuery = useQuery({
        queryKey: queryKeys.auth.socialAccounts(),
        queryFn: fetchSocialAccounts,
    })
    const oauthProvidersQuery = useQuery({
        queryKey: queryKeys.auth.oauthProviders(),
        queryFn: fetchOAuthProviders,
    })

    // Handle oauth_linked / oauth_error query params
    useEffect(() => {
        const linked = searchParams.get('oauth_linked')
        const oauthError = searchParams.get('oauth_error')
        if (linked === 'true') {
            void queryClient.invalidateQueries({ queryKey: queryKeys.auth.socialAccounts() })
            pushToast(t('account.linkSuccess'), 'success')
            const next = new URLSearchParams(searchParams)
            next.delete('oauth_linked')
            setSearchParams(next, { replace: true })
        } else if (oauthError) {
            pushToast(t('auth.oauth.errors.generic', { code: oauthError }), 'error')
            const next = new URLSearchParams(searchParams)
            next.delete('oauth_error')
            setSearchParams(next, { replace: true })
        }
    // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [])

    const [profileForm, setProfileForm] = useState({
        email: user?.email || '',
        first_name: user?.first_name || '',
        last_name: user?.last_name || '',
    })

    const [passwordForm, setPasswordForm] = useState({
        oldPassword: '',
        newPassword: '',
        confirmPassword: '',
    })

    const [linkingProvider, setLinkingProvider] = useState<string | null>(null)

    useEffect(() => {
        setProfileForm({
            email: user?.email || '',
            first_name: user?.first_name || '',
            last_name: user?.last_name || '',
        })
    }, [user])

    const profileMutation = useMutation({
        mutationFn: () => updateProfile(profileForm),
        onSuccess: () => {
            queryClient.refetchQueries({ queryKey: queryKeys.auth.me() })
            pushToast(t('account.profileUpdatedSuccess'), 'success')
        },
        onError: (error: any) => {
            const message = error.response?.data?.detail || t('common.error')
            pushToast(message, 'error')
        },
    })

    const passwordMutation = useMutation({
        mutationFn: () => changePassword(passwordForm.oldPassword, passwordForm.newPassword),
        onSuccess: async () => {
            setPasswordForm({ oldPassword: '', newPassword: '', confirmPassword: '' })
            await refreshUser()
            pushToast(t('account.passwordChangedSuccess'), 'success')
        },
        onError: (error: any) => {
            const message = error.response?.data?.detail || error.response?.data?.old_password?.[0] || t('common.error')
            pushToast(message, 'error')
        },
    })

    const unlinkMutation = useMutation({
        mutationFn: (id: number) => deleteSocialAccount(id),
        onSuccess: () => {
            void queryClient.invalidateQueries({ queryKey: queryKeys.auth.socialAccounts() })
            pushToast(t('account.unlinkSuccess'), 'success')
        },
        onError: () => {
            pushToast(t('common.error'), 'error')
        },
    })

    async function handleUnlink(id: number, displayName: string) {
        confirm({
            title: t('account.unlinkConfirmTitle'),
            message: t('account.unlinkConfirmMessage', { provider: displayName }),
            confirmText: t('account.unlinkAccount'),
            isDangerous: true,
            onConfirm: () => unlinkMutation.mutate(id),
        })
    }

    async function handleLink(providerSlug: string) {
        setLinkingProvider(providerSlug)
        try {
            const { redirect_url } = await oauthLinkInitiate(providerSlug)
            window.location.assign(redirect_url)
        } catch {
            pushToast(t('auth.oauth.errors.initFailed'), 'error')
            setLinkingProvider(null)
        }
    }

    const handleProfileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
        const { name, value } = e.target
        setProfileForm((prev) => ({ ...prev, [name]: value }))
    }

    const handlePasswordChange = (e: React.ChangeEvent<HTMLInputElement>) => {
        const { name, value } = e.target
        setPasswordForm((prev) => ({ ...prev, [name]: value }))
    }

    const handleProfileSubmit = (e: React.FormEvent) => {
        e.preventDefault()
        profileMutation.mutate()
    }

    const handlePasswordSubmit = (e: React.FormEvent) => {
        e.preventDefault()

        if (!passwordForm.oldPassword.trim()) {
            pushToast(t('account.oldPasswordRequired'), 'error')
            return
        }
        if (!passwordForm.newPassword.trim()) {
            pushToast(t('account.newPasswordRequired'), 'error')
            return
        }
        if (passwordForm.newPassword !== passwordForm.confirmPassword) {
            pushToast(t('account.passwordsDoNotMatch'), 'error')
            return
        }
        if (passwordForm.newPassword.length < 8) {
            pushToast(t('account.passwordTooShort'), 'error')
            return
        }

        passwordMutation.mutate()
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

            <div className="form-grid" style={{ gap: '2rem', maxWidth: '1000px' }}>
                <div className="card">
                    <h2>{t('account.profileSection')}</h2>
                    <form onSubmit={handleProfileSubmit}>
                        <label>
                            <span>{t('account.username')}</span>
                            <input
                                type="text"
                                value={user?.username || ''}
                                disabled
                                style={{ backgroundColor: 'var(--surface)', cursor: 'not-allowed' }}
                            />
                            <small className="muted">
                                {t('account.usernameReadOnly')}
                            </small>
                        </label>

                        <label>
                            <span>{t('account.firstName')}</span>
                            <input
                                type="text"
                                name="first_name"
                                value={profileForm.first_name}
                                onChange={handleProfileChange}
                            />
                        </label>

                        <label>
                            <span>{t('account.lastName')}</span>
                            <input
                                type="text"
                                name="last_name"
                                value={profileForm.last_name}
                                onChange={handleProfileChange}
                            />
                        </label>

                        <label>
                            <span>{t('account.email')}</span>
                            <input
                                type="email"
                                name="email"
                                value={profileForm.email}
                                onChange={handleProfileChange}
                                required
                            />
                        </label>

                        <button
                            type="submit"
                            className="button button-primary"
                            disabled={profileMutation.isPending}
                            style={{ width: '100%' }}
                        >
                            {profileMutation.isPending ? t('common.saving') : t('account.updateProfile')}
                        </button>
                    </form>
                </div>

                <div className="card">
                    <h2>{t('account.passwordSection')}</h2>
                    <form onSubmit={handlePasswordSubmit}>
                        <label>
                            <span>{t('account.oldPassword')}</span>
                            <input
                                type="password"
                                name="oldPassword"
                                value={passwordForm.oldPassword}
                                onChange={handlePasswordChange}
                                placeholder={t('account.enterCurrentPassword')}
                                required
                            />
                        </label>

                        <label>
                            <span>{t('account.newPassword')}</span>
                            <input
                                type="password"
                                name="newPassword"
                                value={passwordForm.newPassword}
                                onChange={handlePasswordChange}
                                placeholder={t('account.enterNewPassword')}
                                required
                            />
                            <small className="muted">
                                {t('account.passwordMinLength')}
                            </small>
                        </label>

                        <label>
                            <span>{t('account.confirmPassword')}</span>
                            <input
                                type="password"
                                name="confirmPassword"
                                value={passwordForm.confirmPassword}
                                onChange={handlePasswordChange}
                                placeholder={t('account.reenterNewPassword')}
                                required
                            />
                        </label>

                        <button
                            type="submit"
                            className="button button-primary"
                            disabled={passwordMutation.isPending}
                            style={{ width: '100%' }}
                        >
                            {passwordMutation.isPending ? t('common.saving') : t('account.changePassword')}
                        </button>
                    </form>
                    <small className="muted" style={{ marginTop: '1rem', display: 'block' }}>
                        {t('account.apiKeys.passwordChangeNote')}
                    </small>
                </div>
                <div className="card">
                    <h2>{t('account.linkedAccountsSection')}</h2>
                    <p className="muted" style={{ marginBottom: '1.5rem' }}>{t('account.linkedAccountsDescription')}</p>

                    {oauthProvidersQuery.isLoading && <p className="muted">{t('common.loading')}</p>}

                    {!oauthProvidersQuery.isLoading && (oauthProvidersQuery.data ?? []).length === 0 && (
                        <p className="muted">{t('account.noProviders')}</p>
                    )}

                    {(oauthProvidersQuery.data ?? []).map((provider) => {
                        const linked = (socialAccountsQuery.data ?? []).find(
                            (sa) => sa.provider_name === provider.name,
                        )
                        return (
                            <div
                                key={provider.name}
                                style={{
                                    display: 'flex',
                                    alignItems: 'center',
                                    justifyContent: 'space-between',
                                    padding: '0.75rem 0',
                                    borderBottom: '1px solid var(--border)',
                                }}
                            >
                                <div>
                                    <strong>{provider.display_name}</strong>
                                    {linked && (
                                        <small className="muted" style={{ display: 'block' }}>
                                            {t('account.linkedSince', {
                                                date: new Date(linked.created_at).toLocaleDateString(),
                                            })}
                                        </small>
                                    )}
                                </div>
                                {linked ? (
                                    <button
                                        type="button"
                                        className="button button-danger button-compact"
                                        disabled={unlinkMutation.isPending}
                                        onClick={() => void handleUnlink(linked.id, provider.display_name)}
                                    >
                                        {t('account.unlinkAccount')}
                                    </button>
                                ) : (
                                    <button
                                        type="button"
                                        className="button button-secondary button-compact"
                                        disabled={linkingProvider !== null}
                                        onClick={() => void handleLink(provider.name)}
                                    >
                                        {linkingProvider === provider.name
                                            ? t('common.loading')
                                            : t('account.linkAccount', { provider: provider.display_name })}
                                    </button>
                                )}
                            </div>
                        )
                    })}
                </div>

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
