import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { fetchFeatureFlags, formatApiError, updateFeatureFlag } from '../lib/api'
import { useToast } from '../lib/toast'

export function AdminFeaturesPage() {
    const { t } = useTranslation()
    const queryClient = useQueryClient()
    const { pushToast } = useToast()

    const flagsQuery = useQuery({
        queryKey: ['feature-flags'],
        queryFn: fetchFeatureFlags,
    })

    const toggleMutation = useMutation({
        mutationFn: ({ id, enabled }: { id: number; enabled: boolean }) =>
            updateFeatureFlag(id, { enabled }),
        onSuccess: () => {
            void queryClient.invalidateQueries({ queryKey: ['feature-flags'] })
            pushToast(t('features.updated'), 'success')
        },
        onError: (error) => pushToast(formatApiError(error), 'error'),
    })

    const flags = flagsQuery.data ?? []

    return (
        <div className="page-stack">
            <header>
                <p className="eyebrow">{t('features.eyebrow')}</p>
                <h2>{t('features.title')}</h2>
                <p className="muted">{t('features.description')}</p>
            </header>

            <section className="card" style={{ maxWidth: 720 }}>
                {flagsQuery.isLoading && <p>{t('features.loading')}</p>}
                {flagsQuery.isError && <p className="text-error">{t('features.loadError')}</p>}
                {!flagsQuery.isLoading && flags.length === 0 && (
                    <p className="muted">{t('features.empty')}</p>
                )}
                {flags.length > 0 && (
                    <table className="data-table">
                        <thead>
                            <tr>
                                <th>{t('features.name')}</th>
                                <th>{t('features.descriptionCol')}</th>
                                <th style={{ width: 80, textAlign: 'center' }}>{t('features.enabled')}</th>
                            </tr>
                        </thead>
                        <tbody>
                            {flags.map((flag) => (
                                <tr key={flag.id}>
                                    <td><code>{flag.name}</code></td>
                                    <td>{flag.description || <span className="muted">—</span>}</td>
                                    <td className="feature-toggle-cell">
                                        <div className="feature-toggle-wrap">
                                            <button
                                                type="button"
                                                className={`feature-toggle${flag.enabled ? ' is-on' : ''}`}
                                                role="switch"
                                                aria-checked={flag.enabled}
                                                aria-label={`${flag.name}: ${flag.enabled ? t('features.on') : t('features.off')}`}
                                                disabled={toggleMutation.isPending}
                                                onClick={() =>
                                                    toggleMutation.mutate({
                                                        id: flag.id,
                                                        enabled: !flag.enabled,
                                                    })
                                                }
                                            >
                                                <span className="feature-toggle-track" aria-hidden="true">
                                                    <span className="feature-toggle-thumb" />
                                                </span>
                                            </button>
                                            <span className={`feature-toggle-state ${flag.enabled ? 'is-on' : 'is-off'}`}>
                                                {flag.enabled ? t('features.on') : t('features.off')}
                                            </span>
                                        </div>
                                    </td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                )}
            </section>
        </div>
    )
}
