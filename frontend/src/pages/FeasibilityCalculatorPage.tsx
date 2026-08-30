import { zodResolver } from '@hookform/resolvers/zod'
import { useMutation } from '@tanstack/react-query'
import { useEffect } from 'react'
import { useForm, useWatch } from 'react-hook-form'
import { useTranslation } from 'react-i18next'
import { EnergyFlowChart } from '../components/EnergyFlowChart'
import { StatCard } from '../components/StatCard'
import { FeasibilityCashflowChart } from '../features/feasibility/FeasibilityCashflowChart'
import { FeasibilityPriceSensitivityChart } from '../features/feasibility/FeasibilityPriceSensitivityChart'
import { FeasibilitySensitivityChart } from '../features/feasibility/FeasibilitySensitivityChart'
import { ParticipantResultsTable } from '../features/feasibility/ParticipantResultsTable'
import { ParticipantRowsEditor } from '../features/feasibility/ParticipantRowsEditor'
import { PrefillFromZevCard } from '../features/feasibility/PrefillFromZevCard'
import {
    applyPrefillToFormValues,
    convertedInternalPriceForMode,
    defaultFeasibilityFormValues,
    feasibilityFormSchema,
    mapFormValuesToPayload,
    resolveAnnualProductionKwh,
    resolveInternalEnergyPriceChf,
    resolveParticipantTotals,
    type FeasibilityFormValues,
    type InternalEnergyPriceMode,
} from '../features/feasibility/useFeasibilityForm'
import { calculateFeasibility } from '../lib/api/feasibility'
import { formatApiError } from '../lib/api/errors'
import { formatChf, formatKwh } from '../lib/numbers'

const DEBOUNCE_MS = 400

export function FeasibilityCalculatorPage() {
    const { t } = useTranslation()
    const form = useForm<FeasibilityFormValues>({
        resolver: zodResolver(feasibilityFormSchema),
        defaultValues: defaultFeasibilityFormValues,
        mode: 'onChange',
    })

    const mutation = useMutation({ mutationFn: calculateFeasibility })
    // Destructure the stable `mutate` callback: the `useMutation` result object
    // is recreated on every render and mutation-state change, so depending on it
    // would re-arm the debounce timer and re-submit forever.
    const { mutate } = mutation

    // useWatch with no `name` is typed as a deep-partial value, but every field is
    // always present at runtime because defaultValues populates them all, so casting
    // to the full form type (matching the previous `form.watch()` return type) is safe.
    const watchedValues = useWatch<FeasibilityFormValues>({ control: form.control }) as FeasibilityFormValues

    useEffect(() => {
        const timer = window.setTimeout(async () => {
            const isValid = await form.trigger()
            if (isValid) {
                mutate(mapFormValuesToPayload(form.getValues()))
            }
        }, DEBOUNCE_MS)
        return () => window.clearTimeout(timer)
    }, [watchedValues, form, mutate])

    const result = mutation.data
    const currentRatePct = Number(watchedValues.self_consumption_rate_pct) || 0
    const participantTotals = resolveParticipantTotals(watchedValues)

    return (
        <div className="page-stack">
            <header>
                <p className="eyebrow">{t('pages.feasibility.eyebrow')}</p>
                <h2>{t('pages.feasibility.title')}</h2>
                <p className="muted">{t('pages.feasibility.description')}</p>
            </header>

            <PrefillFromZevCard
                onPrefillLoaded={(prefill) => form.reset(applyPrefillToFormValues(prefill, form.getValues()))}
            />

            <div
                style={{
                    display: 'grid',
                    gridTemplateColumns:
                        watchedValues.energy_input_mode === 'participants' ? 'minmax(320px, 540px) 1fr' : 'minmax(320px, 420px) 1fr',
                    gap: '1.5rem',
                    alignItems: 'start',
                }}
            >
                <form className="card page-stack" onSubmit={(event) => event.preventDefault()}>
                    <h3 style={{ marginTop: 0, display: 'flex', justifyContent: 'space-between', alignItems: 'baseline' }}>
                        {t('pages.feasibility.form.systemTitle')}
                        <select
                            {...form.register('energy_input_mode')}
                            style={{ width: 'auto', fontSize: '0.78rem', padding: '0.1rem 0.3rem' }}
                        >
                            <option value="aggregate">{t('pages.feasibility.form.energyInputModeAggregate')}</option>
                            <option value="participants">{t('pages.feasibility.form.energyInputModeParticipants')}</option>
                        </select>
                    </h3>

                    {watchedValues.energy_input_mode === 'participants' ? (
                        <div>
                            <p className="muted" style={{ fontSize: '0.78rem', marginTop: 0 }}>{t('pages.feasibility.form.participantsHint')}</p>
                            <ParticipantRowsEditor form={form} />
                            <p className="muted" style={{ fontSize: '0.82rem', marginTop: '0.5rem' }}>
                                {t('pages.feasibility.form.participantsTotal', {
                                    production: participantTotals.production.toFixed(0),
                                    consumption: participantTotals.consumption.toFixed(0),
                                })}
                            </p>
                        </div>
                    ) : (
                        <div>
                            <span style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline' }}>
                                {t('pages.feasibility.form.annualProduction')}
                                <select
                                    {...form.register('annual_production_mode')}
                                    style={{ width: 'auto', fontSize: '0.78rem', padding: '0.1rem 0.3rem' }}
                                >
                                    <option value="absolute">{t('pages.feasibility.form.annualProductionModeAbsolute')}</option>
                                    <option value="from_kwp">{t('pages.feasibility.form.annualProductionModeFromKwp')}</option>
                                </select>
                            </span>
                            {watchedValues.annual_production_mode === 'from_kwp' ? (
                                <>
                                    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.6rem', marginTop: '0.3rem' }}>
                                        <label>
                                            <span className="muted" style={{ fontSize: '0.78rem' }}>{t('pages.feasibility.form.pvKwp')}</span>
                                            <input type="number" step="any" min="0" {...form.register('pv_kwp')} />
                                        </label>
                                        <label>
                                            <span className="muted" style={{ fontSize: '0.78rem' }}>{t('pages.feasibility.form.specificYield')}</span>
                                            <input type="number" step="any" min="0" {...form.register('specific_yield_kwh_per_kwp')} />
                                        </label>
                                    </div>
                                    <span className="muted" style={{ fontSize: '0.78rem' }}>
                                        {t('pages.feasibility.form.annualProductionComputed', {
                                            value: resolveAnnualProductionKwh(watchedValues).toFixed(0),
                                        })}
                                    </span>
                                </>
                            ) : (
                                <label>
                                    <input type="number" step="any" min="0" {...form.register('annual_production_kwh')} />
                                </label>
                            )}
                            <p className="muted" style={{ fontSize: '0.78rem', margin: '0.2rem 0 0' }}>{t('pages.feasibility.form.specificYieldHint')}</p>
                            <label>
                                <span>{t('pages.feasibility.form.annualConsumption')}</span>
                                <input type="number" step="any" min="0" {...form.register('annual_consumption_kwh')} />
                            </label>
                        </div>
                    )}

                    <label>
                        <span>{t('pages.feasibility.form.selfConsumptionRate')}</span>
                        <input type="number" step="any" min="0" max="100" {...form.register('self_consumption_rate_pct')} />
                        <span className="muted" style={{ fontSize: '0.78rem' }}>{t('pages.feasibility.form.selfConsumptionHint')}</span>
                    </label>

                    <h3>{t('pages.feasibility.form.tariffsTitle')}</h3>
                    <label>
                        <span>{t('pages.feasibility.form.retailPrice')}</span>
                        <input type="number" step="any" min="0" {...form.register('retail_price_chf_per_kwh')} />
                    </label>
                    <label>
                        <span>{t('pages.feasibility.form.feedInPrice')}</span>
                        <input type="number" step="any" min="0" {...form.register('feed_in_price_chf_per_kwh')} />
                    </label>
                    <label>
                        <span style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline' }}>
                            {t('pages.feasibility.form.internalEnergyPrice')}
                            <select
                                {...form.register('internal_energy_price_mode')}
                                onChange={(event) => {
                                    // Convert the value so the effective price is preserved across the
                                    // switch, instead of revealing the other field's stale value.
                                    const newMode = event.target.value as InternalEnergyPriceMode
                                    const converted = convertedInternalPriceForMode(form.getValues(), newMode)
                                    if (converted) form.setValue(converted.field, converted.value)
                                    void form.register('internal_energy_price_mode').onChange(event)
                                }}
                                style={{ width: 'auto', fontSize: '0.78rem', padding: '0.1rem 0.3rem' }}
                            >
                                <option value="absolute">{t('pages.feasibility.form.internalEnergyPriceModeAbsolute')}</option>
                                <option value="percentage_of_retail">{t('pages.feasibility.form.internalEnergyPriceModePercentage')}</option>
                            </select>
                        </span>
                        {watchedValues.internal_energy_price_mode === 'percentage_of_retail' ? (
                            <>
                                <input type="number" step="any" min="0" {...form.register('internal_energy_price_pct_of_retail')} />
                                <span className="muted" style={{ fontSize: '0.78rem' }}>
                                    {t('pages.feasibility.form.internalEnergyPriceComputed', {
                                        value: resolveInternalEnergyPriceChf(watchedValues).toFixed(3),
                                    })}
                                </span>
                            </>
                        ) : (
                            <input type="number" step="any" min="0" {...form.register('internal_energy_price_chf_per_kwh')} />
                        )}
                        <span className="muted" style={{ fontSize: '0.78rem' }}>{t('pages.feasibility.form.internalEnergyPriceHint')}</span>
                    </label>

                    <h3>{t('pages.feasibility.form.costsTitle')}</h3>
                    <label>
                        <span>{t('pages.feasibility.form.annualOpex')}</span>
                        <input type="number" step="any" min="0" {...form.register('annual_opex_chf')} />
                    </label>
                    <label>
                        <span>{t('pages.feasibility.form.capex')}</span>
                        <input type="number" step="any" min="0" {...form.register('capex_chf')} />
                    </label>
                    <label>
                        <span>{t('pages.feasibility.form.horizonYears')}</span>
                        <input type="number" step="1" min="1" max="50" {...form.register('horizon_years')} />
                    </label>
                    <label>
                        <span>{t('pages.feasibility.form.discountRate')}</span>
                        <input type="number" step="any" min="0" max="100" {...form.register('discount_rate_pct')} />
                    </label>
                </form>

                <div className="page-stack">
                    {mutation.isError && (
                        <div className="error-banner">{formatApiError(mutation.error, t('pages.feasibility.results.error'))}</div>
                    )}

                    {!result && !mutation.isError && (
                        <p className="muted">{t('pages.feasibility.results.calculating')}</p>
                    )}

                    {result && (
                        <>
                            <section
                                style={{
                                    display: 'grid',
                                    gap: '1rem',
                                    gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))',
                                    opacity: mutation.isPending ? 0.6 : 1,
                                    transition: 'opacity 0.15s',
                                }}
                            >
                                <StatCard label={t('pages.feasibility.results.annualNetBenefit')} value={formatChf(Number(result.annual_net_benefit_chf))} />
                                <StatCard
                                    label={t('pages.feasibility.results.payback')}
                                    value={result.payback_years !== null ? t('pages.feasibility.results.years', { count: Number(result.payback_years).toFixed(1) }) : t('pages.feasibility.results.never')}
                                />
                                <StatCard
                                    label={t('pages.feasibility.results.roi')}
                                    value={result.roi !== null ? `${(Number(result.roi) * 100).toFixed(1)}%` : '—'}
                                />
                                <StatCard label={t('pages.feasibility.results.npv')} value={formatChf(Number(result.npv_chf))} hint={t('pages.feasibility.results.npvHint')} />
                                <StatCard label={t('pages.feasibility.results.selfConsumed')} value={`${formatKwh(Number(result.self_consumed_kwh), { maxDecimals: 0 })} kWh`} />
                                <StatCard label={t('pages.feasibility.results.autarky')} value={`${(Number(result.autarky_rate) * 100).toFixed(0)}%`} />
                            </section>

                            <section className="card page-stack">
                                <h3 style={{ marginTop: 0 }}>{t('pages.feasibility.results.splitTitle')}</h3>
                                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1rem' }}>
                                    <div>
                                        <p className="eyebrow">{t('pages.feasibility.results.consumers')}</p>
                                        <p style={{ margin: 0 }}>{t('pages.feasibility.results.baselineCost')}: {formatChf(Number(result.baseline_consumer_cost_chf))}</p>
                                        <p style={{ margin: 0 }}>{t('pages.feasibility.results.vzevCost')}: {formatChf(Number(result.vzev_consumer_cost_chf))}</p>
                                        <p style={{ margin: '0.3rem 0 0', fontWeight: 600 }}>{t('pages.feasibility.results.savings')}: {formatChf(Number(result.consumer_savings_chf))}</p>
                                    </div>
                                    <div>
                                        <p className="eyebrow">{t('pages.feasibility.results.producer')}</p>
                                        <p style={{ margin: 0 }}>{t('pages.feasibility.results.baselineRevenue')}: {formatChf(Number(result.baseline_producer_revenue_chf))}</p>
                                        <p style={{ margin: 0 }}>{t('pages.feasibility.results.vzevRevenue')}: {formatChf(Number(result.vzev_producer_revenue_chf))}</p>
                                        <p style={{ margin: '0.3rem 0 0', fontWeight: 600 }}>{t('pages.feasibility.results.gain')}: {formatChf(Number(result.producer_gain_chf))}</p>
                                    </div>
                                </div>
                            </section>

                            {result.participants.length > 0 && (
                                <section className="card page-stack">
                                    <h3 style={{ marginTop: 0 }}>{t('pages.feasibility.results.participantsTitle')}</h3>
                                    <ParticipantResultsTable participants={result.participants} />
                                </section>
                            )}

                            {result.participants.length > 0 && (
                                <section className="card">
                                    <h3 style={{ marginTop: 0 }}>{t('pages.feasibility.results.topologyTitle')}</h3>
                                    <EnergyFlowChart
                                        totals={{
                                            produced_kwh: result.participants.reduce((sum, p) => sum + Number(p.annual_production_kwh), 0),
                                            consumed_kwh: result.participants.reduce((sum, p) => sum + Number(p.annual_consumption_kwh), 0),
                                            imported_kwh: Number(result.grid_import_kwh),
                                            exported_kwh: Number(result.grid_export_kwh),
                                        }}
                                        participantStats={result.participants.map((p) => ({
                                            participant_id: p.name,
                                            participant_name: p.name,
                                            total_consumed_kwh: Number(p.annual_consumption_kwh),
                                            total_produced_kwh: Number(p.annual_production_kwh),
                                            from_zev_kwh: Number(p.from_local_pool_kwh),
                                            from_grid_kwh: Number(p.from_grid_kwh),
                                        }))}
                                    />
                                </section>
                            )}

                            <section className="card">
                                <FeasibilitySensitivityChart
                                    sensitivity={result.sensitivity}
                                    currentRatePct={currentRatePct}
                                    currentNetBenefitChf={Number(result.annual_net_benefit_chf)}
                                    breakEvenRatePct={result.break_even_self_consumption_rate !== null ? Number(result.break_even_self_consumption_rate) * 100 : null}
                                />
                            </section>

                            <section className="card">
                                <FeasibilityPriceSensitivityChart
                                    priceSensitivity={result.price_sensitivity}
                                    retailPriceChfPerKwh={Number(watchedValues.retail_price_chf_per_kwh)}
                                    equalSplitPriceChfPerKwh={result.equal_split_price_chf_per_kwh !== null ? Number(result.equal_split_price_chf_per_kwh) : null}
                                    fairPriceRange={result.fair_price_range}
                                />
                            </section>

                            <section className="card">
                                <FeasibilityCashflowChart
                                    cashflowByYear={result.cashflow_by_year}
                                    paybackYears={result.payback_years !== null ? Number(result.payback_years) : null}
                                />
                            </section>
                        </>
                    )}
                </div>
            </div>
        </div>
    )
}
