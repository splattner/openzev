import { useEffect, useState, type FormEvent } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { fetchSystemHealth, updateAppSettings } from '../../lib/api/auth'
import { formatApiError } from '../../lib/api/errors'
import { queryKeys } from '../../lib/api/queryKeys'
import { useAppSettings } from '../../lib/appSettings'
import { useToast } from '../../lib/toast'
import type { UserRole } from '../../types/api'

const ROLES: UserRole[] = ['admin', 'zev_owner', 'participant', 'guest']

/**
 * Which roles must hold a second factor, and for how long they may put it
 * off. Spec 2026-09-two-factor-authentication.md §7.4.
 *
 * Disabled — with the reason stated — while the instance has no
 * `MFA_ENCRYPTION_KEYS`: a requirement the server cannot honour must not be
 * settable (the API refuses it too).
 */
export function MfaPolicySection() {
    const { t } = useTranslation()
    const { pushToast } = useToast()
    const queryClient = useQueryClient()
    const { settings } = useAppSettings()

    const healthQuery = useQuery({ queryKey: queryKeys.auth.systemHealth(), queryFn: fetchSystemHealth })
    // Only a positive "not configured" disables the form; while loading or on
    // a failed probe the API's own validation remains the backstop.
    const keyMissing = healthQuery.data ? !healthQuery.data.mfa.encryption_key_configured : false

    const [roles, setRoles] = useState<UserRole[]>(settings.mfa_required_roles)
    const [graceDays, setGraceDays] = useState(String(settings.mfa_grace_period_days))

    useEffect(() => {
        setRoles(settings.mfa_required_roles)
        setGraceDays(String(settings.mfa_grace_period_days))
    }, [settings.mfa_required_roles, settings.mfa_grace_period_days])

    const saveMutation = useMutation({
        mutationFn: updateAppSettings,
        onSuccess: (data) => {
            queryClient.setQueryData(queryKeys.auth.appSettings(), data)
            void queryClient.invalidateQueries({ queryKey: queryKeys.auth.mfa() })
            pushToast(t('adminSystemSettings.mfaPolicy.saved'), 'success')
        },
        onError: (error) => pushToast(formatApiError(error, t('adminSystemSettings.mfaPolicy.saveFailed')), 'error'),
    })

    function toggleRole(role: UserRole, checked: boolean) {
        setRoles((previous) => (checked ? [...previous, role] : previous.filter((value) => value !== role)))
    }

    function handleSubmit(event: FormEvent<HTMLFormElement>) {
        event.preventDefault()
        saveMutation.mutate({
            mfa_required_roles: ROLES.filter((role) => roles.includes(role)),
            mfa_grace_period_days: Math.max(0, Math.floor(Number(graceDays) || 0)),
        })
    }

    return (
        <section className="card">
            <div style={{ marginBottom: '1rem' }}>
                <h3 style={{ marginTop: 0, marginBottom: '0.35rem' }}>{t('adminSystemSettings.mfaPolicy.title')}</h3>
                <p className="muted" style={{ margin: 0 }}>{t('adminSystemSettings.mfaPolicy.description')}</p>
            </div>

            {keyMissing && <div className="warning-banner" role="status">{t('adminSystemSettings.mfaPolicy.keyMissing')}</div>}

            <form className="form-grid" onSubmit={handleSubmit}>
                <fieldset disabled={keyMissing} style={{ border: 0, padding: 0, margin: 0 }}>
                    <legend>{t('adminSystemSettings.mfaPolicy.rolesLabel')}</legend>
                    {ROLES.map((role) => (
                        <label key={role} style={{ display: 'flex', gap: '0.5rem', alignItems: 'center' }}>
                            <input
                                type="checkbox"
                                checked={roles.includes(role)}
                                onChange={(event) => toggleRole(role, event.target.checked)}
                            />
                            <span>{t(`pages.accounts.roles.${role}`)}</span>
                        </label>
                    ))}
                    <p className="muted">{t('adminSystemSettings.mfaPolicy.rolesHint')}</p>
                </fieldset>

                <label>
                    <span>{t('adminSystemSettings.mfaPolicy.graceLabel')}</span>
                    <input
                        type="number"
                        min={0}
                        max={365}
                        disabled={keyMissing}
                        value={graceDays}
                        onChange={(event) => setGraceDays(event.target.value)}
                    />
                    <small className="muted">{t('adminSystemSettings.mfaPolicy.graceHint')}</small>
                </label>

                <div className="actions-row actions-row-end actions-row-wrap">
                    <button className="button button-primary" type="submit" disabled={keyMissing || saveMutation.isPending}>
                        {t('adminSystemSettings.regional.save')}
                    </button>
                </div>
            </form>
        </section>
    )
}
