import { useEffect, useState, type FormEvent } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { Notice } from '../../components/Notice'
import { fetchSystemHealth, updateAppSettings } from '../../lib/api/auth'
import { formatApiError } from '../../lib/api/errors'
import { queryKeys } from '../../lib/api/queryKeys'
import { useAppSettings } from '../../lib/appSettings'
import { useToast } from '../../lib/toast'

/**
 * Configures the account-wide MFA requirement and grace period.
 * Disabled until policy fields load or when the encryption key is missing. See
 * 2026-09-two-factor-authentication.md §7.4.
 */
export function MfaPolicySection() {
    const { t } = useTranslation()
    const { pushToast } = useToast()
    const queryClient = useQueryClient()
    const { settings, isError } = useAppSettings()
    const [isRetrying, setIsRetrying] = useState(false)

    const healthQuery = useQuery({ queryKey: queryKeys.auth.systemHealth(), queryFn: fetchSystemHealth })
    // Only a positive "not configured" disables the form; while loading or on
    // a failed probe the API's own validation remains the backstop.
    const keyMissing = healthQuery.data ? !healthQuery.data.mfa.encryption_key_configured : false
    const policyLoaded = settings.mfa_required !== undefined && settings.mfa_grace_period_days !== undefined
    const disabled = keyMissing || !policyLoaded

    const [required, setRequired] = useState(settings.mfa_required ?? false)
    const [graceDays, setGraceDays] = useState(String(settings.mfa_grace_period_days ?? ''))

    useEffect(() => {
        setRequired(settings.mfa_required ?? false)
        setGraceDays(String(settings.mfa_grace_period_days ?? ''))
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

    async function retrySettings() {
        setIsRetrying(true)
        try {
            await queryClient.refetchQueries({ queryKey: queryKeys.auth.appSettings() })
        } finally {
            setIsRetrying(false)
        }
    }

    function handleSubmit(event: FormEvent<HTMLFormElement>) {
        event.preventDefault()
        saveMutation.mutate({
            mfa_required: required,
            mfa_grace_period_days: Math.max(0, Math.floor(Number(graceDays) || 0)),
        })
    }

    return (
        <section className="card">
            <div className="mb-1">
                <h3 style={{ marginTop: 0, marginBottom: '0.35rem' }}>{t('adminSystemSettings.mfaPolicy.title')}</h3>
                <p className="muted m-0">{t('adminSystemSettings.mfaPolicy.description')}</p>
            </div>

            {keyMissing && <Notice tone="warning">{t('adminSystemSettings.mfaPolicy.keyMissing')}</Notice>}
            {(isError || isRetrying) && !policyLoaded && (
                <Notice
                    tone="error"
                    onRetry={() => void retrySettings()}
                    isRetrying={isRetrying}
                >
                    {t('adminSystemSettings.mfaPolicy.loadError')}
                </Notice>
            )}

            <form onSubmit={handleSubmit}>
                <fieldset className="form-grid" disabled={disabled}>
                    <div>
                        <label className="actions-row">
                            <input
                                type="checkbox"
                                checked={required}
                                onChange={(event) => setRequired(event.target.checked)}
                            />
                            <span>{t('adminSystemSettings.mfaPolicy.requiredLabel')}</span>
                        </label>
                        <p className="muted">{t('adminSystemSettings.mfaPolicy.requiredHint')}</p>
                    </div>

                    <label>
                        <span>{t('adminSystemSettings.mfaPolicy.graceLabel')}</span>
                        <input
                            type="number"
                            min={0}
                            max={365}
                            value={graceDays}
                            onChange={(event) => setGraceDays(event.target.value)}
                        />
                        <small className="muted">{t('adminSystemSettings.mfaPolicy.graceHint')}</small>
                    </label>

                    <div className="actions-row actions-row-end actions-row-wrap">
                        <button className="button button-primary" type="submit" disabled={saveMutation.isPending}>
                            {t('common.save')}
                        </button>
                    </div>
                </fieldset>
            </form>
        </section>
    )
}
