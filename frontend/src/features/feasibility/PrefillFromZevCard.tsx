import { useMutation, useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { fetchFeasibilityPrefill } from '../../lib/api/feasibility'
import { formatApiError } from '../../lib/api/errors'
import { fetchZevs } from '../../lib/api/zev'
import { queryKeys } from '../../lib/api/queryKeys'
import { useToast } from '../../lib/toast'
import type { FeasibilityPrefill } from '../../types/api'

type Props = {
    onPrefillLoaded: (prefill: FeasibilityPrefill) => void
}

export function PrefillFromZevCard({ onPrefillLoaded }: Props) {
    const { t } = useTranslation()
    const { pushToast } = useToast()
    const [selectedZevId, setSelectedZevId] = useState('')

    const zevsQuery = useQuery({ queryKey: queryKeys.zev.list(), queryFn: fetchZevs })
    const zevs = zevsQuery.data?.results ?? []

    const prefillMutation = useMutation({
        mutationFn: fetchFeasibilityPrefill,
        onSuccess: (data) => {
            onPrefillLoaded(data)
            const missingData = data.participants.filter((p) => !p.has_metering_data).length
            pushToast(
                missingData > 0
                    ? t('pages.feasibility.prefill.successWithEstimates', { count: data.participants.length, missing: missingData })
                    : t('pages.feasibility.prefill.success', { count: data.participants.length }),
                'success',
            )
            // The self-consumption rate is the single biggest driver, so call it
            // out explicitly when it came from real data rather than a guess.
            if (data.self_consumption_rate !== null) {
                const pct = Number((Number(data.self_consumption_rate) * 100).toFixed(1))
                pushToast(t('pages.feasibility.prefill.selfConsumptionMeasured', { rate: pct }), 'info')
            }
        },
        onError: (error) => {
            pushToast(formatApiError(error, t('pages.feasibility.prefill.error')), 'error')
        },
    })

    return (
        <section className="card">
            <h3 style={{ marginTop: 0 }}>{t('pages.feasibility.prefill.title')}</h3>
            <p className="muted" style={{ fontSize: '0.85rem', marginTop: 0 }}>{t('pages.feasibility.prefill.description')}</p>
            <div style={{ display: 'flex', gap: '0.6rem', alignItems: 'center', flexWrap: 'wrap' }}>
                <select
                    value={selectedZevId}
                    onChange={(event) => setSelectedZevId(event.target.value)}
                    style={{ flex: 1, minWidth: 200 }}
                >
                    <option value="">{t('pages.feasibility.prefill.selectZev')}</option>
                    {zevs.map((zev) => (
                        <option key={zev.id} value={zev.id}>{zev.name}</option>
                    ))}
                </select>
                {/* Hidden until a ZEV is chosen; disabled only while loading. */}
                {selectedZevId !== '' && (
                    <button
                        type="button"
                        className="button button-secondary"
                        disabled={prefillMutation.isPending}
                        onClick={() => prefillMutation.mutate(selectedZevId)}
                    >
                        {prefillMutation.isPending ? t('common.loading') : t('pages.feasibility.prefill.load')}
                    </button>
                )}
            </div>
        </section>
    )
}
