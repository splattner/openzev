import { useEffect, useMemo, useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { FormModal } from '../../components/FormModal'
import {
  createDynamicTariffSource,
  discoverDynamicTariffSource,
  updateDynamicTariffSource,
} from '../../lib/api/tariffs'
import { formatApiError } from '../../lib/api/errors'
import { queryKeys } from '../../lib/api/queryKeys'
import { useToast } from '../../lib/toast'
import type {
  BfeRmpTechnology,
  DynamicApiVersion,
  DynamicSourceDiscovery,
  DynamicTariffSource,
} from '../../types/api'

type VersionChoice = 'auto' | DynamicApiVersion

type SourceKind = 'vse' | 'bfe_rmp'

/** BFE's two published series — see docs/adr/0018-dynamic-tariff-price-series.md. */
const BFE_RMP_URLS: Record<'quarterly' | 'monthly', string> = {
  quarterly: 'https://www.bfe-ogd.ch/ogd60_rmp_quartalspreise.csv',
  monthly: 'https://www.bfe-ogd.ch/ogd60_rmp_monatspreise.csv',
}

const BFE_RMP_TECHNOLOGIES: BfeRmpTechnology[] = ['pv', 'wasserkraft', 'windenergie', 'biomasse']

type Props = {
  isOpen: boolean
  onClose: () => void
  onSaved?: (source: DynamicTariffSource) => void
  source?: DynamicTariffSource | null
}

function componentKey(component: DynamicSourceDiscovery['components'][number]): string {
  return `${component.tariff_type}\u0000${component.tariff_name}`
}

export function DynamicSourceFormModal({ isOpen, onClose, onSaved, source }: Props) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const { pushToast } = useToast()
  const [step, setStep] = useState<1 | 2>(1)
  const [label, setLabel] = useState('')
  const [url, setUrl] = useState('')
  const [versionChoice, setVersionChoice] = useState<VersionChoice>('auto')
  const [discovery, setDiscovery] = useState<DynamicSourceDiscovery | null>(null)
  const [selection, setSelection] = useState('')
  const [tariffName, setTariffName] = useState('')
  const [enabled, setEnabled] = useState(true)
  const [sourceKind, setSourceKind] = useState<SourceKind>('vse')
  const [bfeSeries, setBfeSeries] = useState<'quarterly' | 'monthly'>('quarterly')
  const [bfeTechnology, setBfeTechnology] = useState<BfeRmpTechnology>('pv')

  useEffect(() => {
    setStep(1)
    setLabel(source?.label ?? '')
    setUrl(source?.url ?? '')
    setVersionChoice(source?.api_version ?? 'auto')
    setDiscovery(null)
    setSelection('')
    setTariffName(source?.tariff_name ?? '')
    setEnabled(source?.enabled ?? true)
    setSourceKind(source?.api_version === 'bfe_rmp' ? 'bfe_rmp' : 'vse')
    setBfeSeries(
      source?.url === BFE_RMP_URLS.monthly ? 'monthly' : 'quarterly',
    )
    setBfeTechnology((source?.tariff_name as BfeRmpTechnology) || 'pv')
  }, [source, isOpen])

  const discoverMutation = useMutation({
    mutationFn: () => discoverDynamicTariffSource(
      url,
      versionChoice === 'auto' ? undefined : versionChoice,
    ),
    onSuccess: (result) => {
      setDiscovery(result)
      const first = result.components[0]
      setSelection(componentKey(first))
      setTariffName(first.tariff_name)
      setStep(2)
    },
    onError: (error) => pushToast(
      formatApiError(error, t('pages.dynamicSources.discovery.error')),
      'error',
    ),
  })

  const selected = useMemo(
    () => discovery?.components.find((component) => componentKey(component) === selection),
    [discovery, selection],
  )
  const aggregatedTypes = useMemo(
    () => selected?.aggregated_tariff_types ?? [],
    [selected],
  )

  const saveMutation = useMutation({
    mutationFn: (): Promise<DynamicTariffSource & { warnings?: string[] }> => {
      if (source) return updateDynamicTariffSource(source.id, { label, enabled })
      if (sourceKind === 'bfe_rmp') {
        return createDynamicTariffSource({
          label,
          url: BFE_RMP_URLS[bfeSeries],
          api_version: 'bfe_rmp',
          tariff_type: 'feed_in',
          tariff_name: bfeTechnology,
        })
      }
      return createDynamicTariffSource({
        label,
        url,
        api_version: discovery!.api_version,
        tariff_type: selected!.tariff_type,
        tariff_name: selected!.tariff_name || tariffName,
      })
    },
    onSuccess: async (saved) => {
      await queryClient.invalidateQueries({ queryKey: queryKeys.tariffs.dynamicSources() })
      pushToast(t(source ? 'pages.dynamicSources.updated' : 'pages.dynamicSources.created'), 'success')
      // Units the endpoint publishes but this source cannot bill — surfaced
      // right when the source is configured, not only in the audit trail.
      for (const warning of saved.warnings ?? []) {
        pushToast(warning, 'info')
      }
      onSaved?.(saved)
      onClose()
    },
    onError: (error) => pushToast(
      formatApiError(error, t('pages.dynamicSources.saveError')),
      'error',
    ),
  })

  function submit(event: React.FormEvent) {
    event.preventDefault()
    if (source) saveMutation.mutate()
    else if (sourceKind === 'bfe_rmp') saveMutation.mutate()
    else if (step === 1) discoverMutation.mutate()
    else if (selected) saveMutation.mutate()
  }

  const pending = discoverMutation.isPending || saveMutation.isPending

  return (
    <FormModal
      isOpen={isOpen}
      title={t(source ? 'pages.dynamicSources.editTitle' : 'pages.dynamicSources.createTitle')}
      onClose={onClose}
    >
      <form className="form-grid" onSubmit={submit}>
        {!source && sourceKind === 'vse' && (
          <div className="muted" style={{ gridColumn: '1 / -1' }}>
            {t('pages.dynamicSources.discovery.step', { current: step, total: 2 })}
          </div>
        )}

        {!source && (
          <label style={{ gridColumn: '1 / -1' }}>
            <span>{t('pages.dynamicSources.form.kind')}</span>
            <select value={sourceKind} onChange={(event) => setSourceKind(event.target.value as SourceKind)}>
              <option value="vse">{t('pages.dynamicSources.form.kindVse')}</option>
              <option value="bfe_rmp">{t('pages.dynamicSources.form.kindBfeRmp')}</option>
            </select>
          </label>
        )}

        <label style={{ gridColumn: '1 / -1' }}>
          <span>{t('pages.dynamicSources.form.label')}</span>
          <input value={label} onChange={(event) => setLabel(event.target.value)} required />
        </label>

        {!source && sourceKind === 'bfe_rmp' ? (
          <>
            <label style={{ gridColumn: '1 / -1' }}>
              <span>{t('pages.dynamicSources.form.bfeSeries')}</span>
              <select value={bfeSeries} onChange={(event) => setBfeSeries(event.target.value as 'quarterly' | 'monthly')}>
                <option value="quarterly">{t('pages.dynamicSources.form.bfeSeriesQuarterly')}</option>
                <option value="monthly">{t('pages.dynamicSources.form.bfeSeriesMonthly')}</option>
              </select>
              <small className="muted">{t('pages.dynamicSources.form.bfeSeriesHint')}</small>
            </label>
            <label style={{ gridColumn: '1 / -1' }}>
              <span>{t('pages.dynamicSources.form.bfeTechnology')}</span>
              <select value={bfeTechnology} onChange={(event) => setBfeTechnology(event.target.value as BfeRmpTechnology)}>
                {BFE_RMP_TECHNOLOGIES.map((technology) => (
                  <option key={technology} value={technology}>
                    {t(`pages.dynamicSources.bfeTechnologies.${technology}` as Parameters<typeof t>[0])}
                  </option>
                ))}
              </select>
            </label>
          </>
        ) : source ? (
          <>
            <div className="info-banner" style={{ gridColumn: '1 / -1' }}>
              <strong>{source.url}</strong>
              <div>
                {t(`pages.dynamicSources.versions.${source.api_version}` as Parameters<typeof t>[0])}
                {' · '}
                {t(`pages.dynamicSources.types.${source.tariff_type}` as Parameters<typeof t>[0])}
                {source.tariff_name ? ` · ${source.tariff_name}` : ''}
              </div>
              <small>{t('pages.dynamicSources.form.identityReplacement')}</small>
            </div>
            <label className="checkbox-label" style={{ gridColumn: '1 / -1' }}>
              <input
                type="checkbox"
                checked={enabled}
                onChange={(event) => setEnabled(event.target.checked)}
              />
              <span>{t('pages.dynamicSources.form.enabled')}</span>
            </label>
            <small className="muted" style={{ gridColumn: '1 / -1' }}>
              {t('pages.dynamicSources.form.enabledHint')}
            </small>
          </>
        ) : step === 1 ? (
          <>
            <label style={{ gridColumn: '1 / -1' }}>
              <span>{t('pages.dynamicSources.form.url')}</span>
              <input type="url" value={url} onChange={(event) => setUrl(event.target.value)} required />
              <small className="muted">{t('pages.dynamicSources.form.urlHint')}</small>
            </label>
            <label style={{ gridColumn: '1 / -1' }}>
              <span>{t('pages.dynamicSources.form.apiVersion')}</span>
              <select value={versionChoice} onChange={(event) => setVersionChoice(event.target.value as VersionChoice)}>
                <option value="auto">{t('pages.dynamicSources.versions.auto')}</option>
                <option value="v1_0_5">{t('pages.dynamicSources.versions.v1_0_5')}</option>
                <option value="v2_0_0">{t('pages.dynamicSources.versions.v2_0_0')}</option>
              </select>
              <small className="muted">{t('pages.dynamicSources.form.apiVersionHint')}</small>
            </label>
          </>
        ) : (
          <>
            <div className="info-banner" style={{ gridColumn: '1 / -1' }}>
              {t(
                discovery!.components_discovered
                  ? 'pages.dynamicSources.discovery.detected'
                  : 'pages.dynamicSources.discovery.emptyFallback',
                { version: t(`pages.dynamicSources.versions.${discovery!.api_version}` as Parameters<typeof t>[0]) },
              )}
            </div>
            <label style={{ gridColumn: '1 / -1' }}>
              <span>{t('pages.dynamicSources.form.tariffType')}</span>
              <select
                value={selection}
                onChange={(event) => {
                  const value = event.target.value
                  setSelection(value)
                  const component = discovery!.components.find((item) => componentKey(item) === value)
                  setTariffName(component?.tariff_name ?? '')
                }}
              >
                {discovery!.components.map((component) => (
                  <option key={componentKey(component)} value={componentKey(component)}>
                    {t(`pages.dynamicSources.types.${component.tariff_type}` as Parameters<typeof t>[0])}
                    {component.tariff_name ? ` — ${component.tariff_name}` : ''}
                  </option>
                ))}
              </select>
            </label>
            {(discovery!.api_version === 'v1_0_5' || !selected?.tariff_name) && (
              <label style={{ gridColumn: '1 / -1' }}>
                <span>{t('pages.dynamicSources.form.tariffName')}</span>
                <input value={tariffName} onChange={(event) => setTariffName(event.target.value)} required={discovery!.api_version === 'v2_0_0'} />
                <small className="muted">{t(discovery!.api_version === 'v2_0_0'
                  ? 'pages.dynamicSources.form.v2TariffNameHint'
                  : 'pages.dynamicSources.form.v1TariffNameHint')}</small>
              </label>
            )}
            {aggregatedTypes.length > 0 && (
              <div className="warning-banner" style={{ gridColumn: '1 / -1' }}>
                {t('pages.dynamicSources.form.doubleCountingWarning', {
                  components: aggregatedTypes
                    .map((type) => t(`pages.dynamicSources.types.${type}` as Parameters<typeof t>[0]))
                    .join(', '),
                })}
              </div>
            )}
            <div className="info-banner" style={{ gridColumn: '1 / -1' }}>
              {t('pages.dynamicSources.form.probeNotice')}
            </div>
          </>
        )}

        <div style={{ gridColumn: '1 / -1', display: 'flex', gap: '1rem', justifyContent: 'flex-end', marginTop: '1rem' }}>
          {!source && sourceKind === 'vse' && step === 2 && (
            <button className="button button-secondary" type="button" onClick={() => setStep(1)} disabled={pending}>
              {t('pages.dynamicSources.discovery.back')}
            </button>
          )}
          <button className="button button-secondary" type="button" onClick={onClose} disabled={pending}>
            {t('common.cancel')}
          </button>
          <button
            className="button button-primary"
            type="submit"
            disabled={pending || (!source && sourceKind === 'vse' && step === 2 && !selected)}
          >
            {source || sourceKind === 'bfe_rmp'
              ? t(source ? 'common.save' : 'pages.dynamicSources.createAction')
              : step === 1
                ? t('pages.dynamicSources.discovery.continue')
                : t('pages.dynamicSources.createAction')}
          </button>
        </div>
      </form>
    </FormModal>
  )
}
