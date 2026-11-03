import { useQuery } from '@tanstack/react-query'
import axios from 'axios'
import { useId } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { CivilDateInput } from '../components/CivilDateInput'
import { EmptyState } from '../components/EmptyState'
import { Notice } from '../components/Notice'
import { PageHeader } from '../components/PageHeader'
import { PageSkeleton } from '../components/PageSkeleton'
import { ScopeGuard } from '../components/ScopeGuard'
import { TariffProgressionView } from '../features/tariffs/progression/TariffProgressionView'
import { clampDay, hasGross, lineOn, type PriceBasis } from '../features/tariffs/progression/progression'
import { formatApiError } from '../lib/api/errors'
import { queryKeys } from '../lib/api/queryKeys'
import { fetchTariffProgression } from '../lib/api/tariffs'
import { useScopeNote } from '../lib/communityAccess'
import { todayBusinessIso } from '../lib/dates'
import { useManagedZev } from '../lib/managedZev'
import type { TariffProgressionEnergyType, TariffProgressionVatMode } from '../types/api'

const ENERGY_TYPES: TariffProgressionEnergyType[] = ['grid', 'local', 'feed_in']
const PARAMS = { energy: 'energy', from: 'from', to: 'to', basis: 'basis', date: 'date', line: 'line' } as const

/**
 * The combined per-kWh price of one energy type over time
 * (docs/specs/2026-11-tariff-progression.md). Read-only for everyone who can
 * open the tariffs; the view lives in the URL so it can be linked and survives
 * a reload.
 */
export function TariffProgressionPage() {
    const { t } = useTranslation()
    const scopeNote = useScopeNote()
    const { selectedZevId, selectedZev } = useManagedZev()
    const [params, setParams] = useSearchParams()
    const fieldId = useId()

    const energyParam = params.get(PARAMS.energy)
    const energyType = ENERGY_TYPES.find((type) => type === energyParam) ?? 'grid'
    const from = params.get(PARAMS.from) || undefined
    const to = params.get(PARAMS.to) || undefined

    function update(patch: Partial<Record<keyof typeof PARAMS, string | null>>) {
        const next = new URLSearchParams(params)
        Object.entries(patch).forEach(([key, value]) => {
            if (value) next.set(PARAMS[key as keyof typeof PARAMS], value)
            else next.delete(PARAMS[key as keyof typeof PARAMS])
        })
        setParams(next, { replace: true })
    }

    const query = useQuery({
        queryKey: queryKeys.tariffs.progression(selectedZevId, energyType, from, to),
        queryFn: () => fetchTariffProgression({ zevId: selectedZevId, energyType, from, to }),
        enabled: !!selectedZevId && selectedZev?.id === selectedZevId,
    })

    const progression = query.data
    const vatMode: TariffProgressionVatMode = progression?.vat_mode ?? selectedZev?.vat_mode ?? 'not_registered'
    const basis: PriceBasis = hasGross(vatMode) && params.get(PARAMS.basis) === 'gross' ? 'gross' : 'net'
    const day = progression
        ? clampDay(params.get(PARAMS.date) || todayBusinessIso(), progression.from, progression.to)
        : todayBusinessIso()
    const lineKey = progression ? lineOn(progression, day, params.get(PARAMS.line)) : null
    const tooManyBands = axios.isAxiosError(query.error) && query.error.response?.data?.code === 'too_many_bands'

    return (
        <div className="page-stack">
            <PageHeader
                eyebrow={selectedZev?.name}
                communitySwitch
                scopeNote={scopeNote}
                title={t('pages.tariffs.progression.title')}
                description={t('pages.tariffs.progression.description')}
                actions={<Link className="button button-secondary" to="/tariffs">{t('pages.tariffs.progression.back')}</Link>}
            />
            <ScopeGuard skeleton="table">
                <div className="card tariff-progression-controls">
                    <label>
                        <span>{t('pages.tariffs.progression.controls.energyType')}</span>
                        <select value={energyType} onChange={(event) => update({ energy: event.target.value, line: null })}>
                            {ENERGY_TYPES.map((type) => (
                                <option key={type} value={type}>{t(`pages.tariffs.energyTypes.${type}`)}</option>
                            ))}
                        </select>
                    </label>
                    <div>
                        <span>{t('pages.tariffs.progression.controls.from')}</span>
                        <CivilDateInput
                            value={from ?? null}
                            onChange={(iso) => update({ from: iso })}
                            maxDate={to}
                            ariaLabel={t('pages.tariffs.progression.controls.from')}
                            placeholder={t('pages.tariffs.progression.controls.wholeHistory')}
                        />
                    </div>
                    <div>
                        <span>{t('pages.tariffs.progression.controls.to')}</span>
                        <CivilDateInput
                            value={to ?? null}
                            onChange={(iso) => update({ to: iso })}
                            minDate={from}
                            ariaLabel={t('pages.tariffs.progression.controls.to')}
                            placeholder={t('pages.tariffs.progression.controls.wholeHistory')}
                        />
                    </div>
                    {hasGross(vatMode) && (
                        <fieldset>
                            <legend>{t('pages.tariffs.progression.basis.label')}</legend>
                            <div className="tariff-progression-basis">
                                {(['net', 'gross'] as const).map((option) => (
                                    <label key={option}>
                                        <input
                                            type="radio"
                                            name={`${fieldId}-basis`}
                                            checked={basis === option}
                                            onChange={() => update({ basis: option === 'gross' ? 'gross' : null })}
                                        />
                                        {t(`pages.tariffs.progression.basis.${vatMode}.${option}`)}
                                    </label>
                                ))}
                            </div>
                        </fieldset>
                    )}
                </div>

                {vatMode === 'not_registered' && (
                    <p className="muted">{t('pages.tariffs.progression.basis.not_registered.note')}</p>
                )}

                {query.isLoading ? <PageSkeleton variant="table" /> : query.isError ? (
                    <Notice tone="error" onRetry={tooManyBands ? undefined : () => void query.refetch()} isRetrying={query.isFetching}>
                        {tooManyBands
                            ? t('pages.tariffs.progression.errors.tooManyBands')
                            : formatApiError(query.error, t('common.error'))}
                    </Notice>
                ) : progression && progression.intervals.length === 0 && progression.fixed_fees.length === 0 ? (
                    <EmptyState
                        titleKey="pages.tariffs.progression.empty.title"
                        descriptionKey="pages.tariffs.progression.empty.description"
                        actions={[{ labelKey: 'pages.tariffs.progression.back', to: '/tariffs', variant: 'secondary' }]}
                    />
                ) : progression ? (
                    <TariffProgressionView
                        progression={progression}
                        basis={basis}
                        day={day}
                        lineKey={lineKey}
                        onPickDay={(picked) => update({ date: picked })}
                        onPickLine={(picked) => update({ line: picked })}
                    />
                ) : null}
            </ScopeGuard>
        </div>
    )
}
