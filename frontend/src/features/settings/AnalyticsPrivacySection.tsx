import { useEffect, useState, type FormEvent } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { updateAppSettings } from '../../lib/api/auth'
import { formatApiError } from '../../lib/api/errors'
import { queryKeys } from '../../lib/api/queryKeys'
import { useAppSettings } from '../../lib/appSettings'
import { useToast } from '../../lib/toast'

/**
 * The smallest community whose ZEV-wide analytics totals a participant may see
 * (SPEC-2026-analytics-dataset-api §6). Empty follows the platform default; the
 * server refuses anything below its floor, which is shown as the input's minimum.
 */
export function AnalyticsPrivacySection() {
    const { t } = useTranslation()
    const { pushToast } = useToast()
    const queryClient = useQueryClient()
    const { settings } = useAppSettings()

    const loaded = settings.analytics_min_participants_default !== undefined
    const floor = settings.analytics_min_participants_floor ?? 3
    const platformDefault = settings.analytics_min_participants_default
    const stored = settings.analytics_min_participants_for_aggregate

    const [value, setValue] = useState(stored == null ? '' : String(stored))
    useEffect(() => setValue(stored == null ? '' : String(stored)), [stored])

    const trimmed = value.trim()
    const parsed = trimmed === '' ? null : Number(trimmed)
    const invalid = parsed !== null && (!Number.isInteger(parsed) || parsed < floor || parsed > 100)

    const save = useMutation({
        mutationFn: () => updateAppSettings({ analytics_min_participants_for_aggregate: parsed }),
        onSuccess: (data) => {
            queryClient.setQueryData(queryKeys.auth.appSettings(), data)
            pushToast(t('adminSystemSettings.analyticsPrivacy.saved'), 'success')
        },
        onError: (error) => pushToast(formatApiError(error, t('adminSystemSettings.analyticsPrivacy.saveFailed')), 'error'),
    })

    function handleSubmit(event: FormEvent<HTMLFormElement>) {
        event.preventDefault()
        if (!invalid) save.mutate()
    }

    return (
        <section className="card">
            <div className="mb-1">
                <h3 style={{ marginTop: 0, marginBottom: '0.35rem' }}>{t('adminSystemSettings.analyticsPrivacy.title')}</h3>
                <p className="muted m-0">{t('adminSystemSettings.analyticsPrivacy.description')}</p>
            </div>

            <form onSubmit={handleSubmit}>
                <fieldset className="form-grid" disabled={!loaded}>
                    <label>
                        <span>{t('adminSystemSettings.analyticsPrivacy.label')}</span>
                        <input
                            type="number"
                            min={floor}
                            max={100}
                            step={1}
                            value={value}
                            placeholder={platformDefault === undefined ? '' : String(platformDefault)}
                            aria-invalid={invalid}
                            onChange={(event) => setValue(event.target.value)}
                        />
                        <small className="muted">
                            {t('adminSystemSettings.analyticsPrivacy.hint', { default: platformDefault ?? '', floor })}
                        </small>
                        {invalid && (
                            <small role="alert" style={{ color: 'var(--danger-700)' }}>
                                {t('adminSystemSettings.analyticsPrivacy.invalid', { floor })}
                            </small>
                        )}
                    </label>

                    <div className="actions-row actions-row-end actions-row-wrap">
                        <button className="button button-primary" type="submit" disabled={save.isPending || invalid}>
                            {t('common.save')}
                        </button>
                    </div>
                </fieldset>
            </form>
        </section>
    )
}
