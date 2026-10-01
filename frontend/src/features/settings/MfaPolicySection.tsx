import { useEffect, useState, type FormEvent } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { fetchSystemHealth, updateAppSettings } from '../../lib/api/auth'
import { formatApiError } from '../../lib/api/errors'
import { queryKeys } from '../../lib/api/queryKeys'
import { useAppSettings } from '../../lib/appSettings'
import { useToast } from '../../lib/toast'

/**
 * Whether every account must hold a second factor, and for how long it may be
 * put off. One switch since #761 (roles became per ZEV). Spec
 * 2026-09-two-factor-authentication.md §7.4.
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

    const [required, setRequired] = useState(settings.mfa_required)
    const [graceDays, setGraceDays] = useState(String(settings.mfa_grace_period_days))

    useEffect(() => {
        setRequired(settings.mfa_required)
        setGraceDays(String(settings.mfa_grace_period_days))
    }, [settings.mfa_required, settings.mfa_grace_period_days])

    const saveMutation = useMutation({
        mutationFn: updateAppSettings,
        onSuccess: (data) => {
            queryClient.setQueryData(queryKeys.auth.appSettings(), data)
            void queryClient.invalidateQueries({ queryKey: queryKeys.auth.mfa() })
            pushToast(t('adminSystemSettings.mfaPolicy.saved'), 'success')
        },
        onError: (error) => pushToast(formatApiError(error, t('adminSystemSettings.mfaPolicy.saveFailed')), 'error'),
    })

    function handleSubmit(event: FormEvent<HTMLFormElement>) {
        event.preventDefault()
        saveMutation.mutate({
            mfa_required: required,
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
                    <label style={{ display: 'flex', gap: '0.5rem', alignItems: 'center' }}>
                        <input
                            type="checkbox"
                            checked={required}
                            onChange={(event) => setRequired(event.target.checked)}
                        />
                        <span>{t('adminSystemSettings.mfaPolicy.requiredLabel')}</span>
                    </label>
                    <p className="muted">{t('adminSystemSettings.mfaPolicy.requiredHint')}</p>
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
