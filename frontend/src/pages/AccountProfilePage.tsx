import { useEffect, useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useLocation } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { useAuth } from '../lib/auth'
import { useToast } from '../lib/toast'
import { changePassword, updateProfile } from '../lib/api'

export function AccountProfilePage() {
    const { t } = useTranslation()
    const location = useLocation()
    const { user, refreshUser } = useAuth()
    const { pushToast } = useToast()
    const queryClient = useQueryClient()

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
            </div>
        </div>
    )
}
