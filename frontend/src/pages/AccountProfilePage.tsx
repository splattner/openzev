import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useLocation, useSearchParams } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { useAuth } from '../lib/auth'
import { useToast } from '../lib/toast'
import { changePassword, deleteSocialAccount, fetchOAuthProviders, fetchSocialAccounts, oauthLinkInitiate, updateProfile } from '../lib/api'
import { ConfirmDialog, useConfirmDialog } from '../components/ConfirmDialog'

export function AccountProfilePage() {
    const { t } = useTranslation()
    const location = useLocation()
    const [searchParams, setSearchParams] = useSearchParams()
    const { user, refreshUser } = useAuth()
    const { pushToast } = useToast()
    const queryClient = useQueryClient()
    const { dialog, confirm, handleConfirm, handleCancel, isLoading: dialogLoading } = useConfirmDialog()

    // Social accounts & OAuth providers
    const socialAccountsQuery = useQuery({
        queryKey: ['social-accounts'],
        queryFn: fetchSocialAccounts,
    })
    const oauthProvidersQuery = useQuery({
        queryKey: ['oauth-providers-public'],
        queryFn: fetchOAuthProviders,
    })

    // Handle oauth_linked / oauth_error query params
    useEffect(() => {
        const linked = searchParams.get('oauth_linked')
        const oauthError = searchParams.get('oauth_error')
        if (linked === 'true') {
            void queryClient.invalidateQueries({ queryKey: ['social-accounts'] })
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

    // Profile form state
    const [profileForm, setProfileForm] = useState({
        email: user?.email || '',
        first_name: user?.first_name || '',
        last_name: user?.last_name || '',
    })

    // Password form state
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

    // Profile update mutation
    const profileMutation = useMutation({
        mutationFn: () => updateProfile(profileForm),
        onSuccess: () => {
            queryClient.refetchQueries({ queryKey: ['me'] })
            pushToast(t('account.profileUpdatedSuccess'), 'success')
        },
        onError: (error: any) => {
            const message = error.response?.data?.detail || t('common.error')
            pushToast(message, 'error')
        },
    })

    // Password change mutation
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

    // Social account unlink mutation
    const unlinkMutation = useMutation({
        mutationFn: (id: number) => deleteSocialAccount(id),
        onSuccess: () => {
            void queryClient.invalidateQueries({ queryKey: ['social-accounts'] })
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
            window.location.href = redirect_url
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

        // Validation
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
        <div className="page">
            <h1>{t('account.title')}</h1>

            {user?.must_change_password && (
                <div className="card" style={{ marginBottom: '1.5rem', border: '1px solid #f59e0b', background: '#fffbeb', maxWidth: '1000px' }}>
                    <h2 style={{ marginTop: 0, color: '#92400e' }}>{t('account.passwordChangeRequired')}</h2>
                    <p style={{ marginBottom: 0, color: '#78350f' }}>
                        {location.state && (location.state as { forcePasswordChange?: boolean }).forcePasswordChange
                            ? t('account.passwordChangeRequiredDescription')
                            : t('account.passwordChangeRequiredDescription')}
                    </p>
                </div>
            )}

            <div className="form-grid" style={{ gap: '2rem', maxWidth: '1000px' }}>
                {/* Profile Section */}
                <div className="card">
                    <h2 style={{ marginTop: 0 }}>{t('account.profileSection')}</h2>
                    <form onSubmit={handleProfileSubmit}>
                        <div className="form-group">
                            <label>{t('account.username')}</label>
                            <input
                                type="text"
                                value={user?.username || ''}
                                disabled
                                style={{ backgroundColor: '#f3f4f6', cursor: 'not-allowed' }}
                            />
                            <small style={{ color: '#6b7280', marginTop: '0.25rem', display: 'block' }}>
                                {t('account.usernameReadOnly')}
                            </small>
                        </div>

                        <div className="form-group">
                            <label>{t('account.firstName')}</label>
                            <input
                                type="text"
                                name="first_name"
                                value={profileForm.first_name}
                                onChange={handleProfileChange}
                            />
                        </div>

                        <div className="form-group">
                            <label>{t('account.lastName')}</label>
                            <input
                                type="text"
                                name="last_name"
                                value={profileForm.last_name}
                                onChange={handleProfileChange}
                            />
                        </div>

                        <div className="form-group">
                            <label>{t('account.email')}</label>
                            <input
                                type="email"
                                name="email"
                                value={profileForm.email}
                                onChange={handleProfileChange}
                                required
                            />
                        </div>

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

                {/* Password Section */}
                <div className="card">
                    <h2 style={{ marginTop: 0 }}>{t('account.passwordSection')}</h2>
                    <form onSubmit={handlePasswordSubmit}>
                        <div className="form-group">
                            <label>{t('account.oldPassword')}</label>
                            <input
                                type="password"
                                name="oldPassword"
                                value={passwordForm.oldPassword}
                                onChange={handlePasswordChange}
                                placeholder={t('account.enterCurrentPassword')}
                                required
                            />
                        </div>

                        <div className="form-group">
                            <label>{t('account.newPassword')}</label>
                            <input
                                type="password"
                                name="newPassword"
                                value={passwordForm.newPassword}
                                onChange={handlePasswordChange}
                                placeholder={t('account.enterNewPassword')}
                                required
                            />
                            <small style={{ color: '#6b7280', marginTop: '0.25rem', display: 'block' }}>
                                {t('account.passwordMinLength')}
                            </small>
                        </div>

                        <div className="form-group">
                            <label>{t('account.confirmPassword')}</label>
                            <input
                                type="password"
                                name="confirmPassword"
                                value={passwordForm.confirmPassword}
                                onChange={handlePasswordChange}
                                placeholder={t('account.reenterNewPassword')}
                                required
                            />
                        </div>

                        <button
                            type="submit"
                            className="button button-primary"
                            disabled={passwordMutation.isPending}
                            style={{ width: '100%' }}
                        >
                            {passwordMutation.isPending ? t('common.saving') : t('account.changePassword')}
                        </button>
                    </form>
                </div>
                {/* Linked Accounts Section */}
                <div className="card">
                    <h2 style={{ marginTop: 0 }}>{t('account.linkedAccountsSection')}</h2>
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
                                        <small style={{ display: 'block', color: '#6b7280' }}>
                                            {t('account.linkedSince', {
                                                date: new Date(linked.created_at).toLocaleDateString(),
                                            })}
                                        </small>
                                    )}
                                </div>
                                {linked ? (
                                    <button
                                        type="button"
                                        className="button button-sm button-danger"
                                        disabled={unlinkMutation.isPending}
                                        onClick={() => void handleUnlink(linked.id, provider.display_name)}
                                    >
                                        {t('account.unlinkAccount')}
                                    </button>
                                ) : (
                                    <button
                                        type="button"
                                        className="button button-sm button-secondary"
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
