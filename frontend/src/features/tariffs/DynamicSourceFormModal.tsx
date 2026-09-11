import { useEffect, useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { FormModal } from '../../components/FormModal'
import { FormModalFooter } from '../../components/FormModalFooter'
import { createDynamicTariffSource, updateDynamicTariffSource } from '../../lib/api/tariffs'
import { formatApiError } from '../../lib/api/errors'
import { queryKeys } from '../../lib/api/queryKeys'
import { useToast } from '../../lib/toast'
import type { DynamicTariffSource, DynamicTariffSourceInput, DynamicTariffType } from '../../types/api'

const EMPTY_SOURCE: DynamicTariffSourceInput = {
  label: '',
  url: '',
  adapter: 'vse_v1',
  tariff_type: 'grid',
  tariff_name: '',
}

const TARIFF_TYPES: DynamicTariffType[] = [
  'electricity', 'grid', 'integrated', 'regional_fees', 'feed_in',
]

type Props = {
  isOpen: boolean
  onClose: () => void
  onSaved?: (source: DynamicTariffSource) => void
  source?: DynamicTariffSource | null
}

export function DynamicSourceFormModal({ isOpen, onClose, onSaved, source }: Props) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const { pushToast } = useToast()
  const [values, setValues] = useState<DynamicTariffSourceInput>(EMPTY_SOURCE)

  useEffect(() => {
    setValues(source ? {
      label: source.label,
      url: source.url,
      adapter: source.adapter,
      tariff_type: source.tariff_type,
      tariff_name: source.tariff_name,
    } : EMPTY_SOURCE)
  }, [source, isOpen])

  const mutation = useMutation({
    mutationFn: (payload: DynamicTariffSourceInput) => source
      ? updateDynamicTariffSource(source.id, payload)
      : createDynamicTariffSource(payload),
    onSuccess: async (saved) => {
      await queryClient.invalidateQueries({ queryKey: queryKeys.tariffs.dynamicSources() })
      pushToast(t(source ? 'pages.dynamicSources.updated' : 'pages.dynamicSources.created'), 'success')
      onSaved?.(saved)
      onClose()
    },
    onError: (error) => pushToast(
      formatApiError(error, t('pages.dynamicSources.saveError')),
      'error',
    ),
  })

  function set<K extends keyof DynamicTariffSourceInput>(key: K, value: DynamicTariffSourceInput[K]) {
    setValues((current) => ({ ...current, [key]: value }))
  }

  function submit(event: React.FormEvent) {
    event.preventDefault()
    mutation.mutate(values)
  }

  return (
    <FormModal
      isOpen={isOpen}
      title={t(source ? 'pages.dynamicSources.editTitle' : 'pages.dynamicSources.createTitle')}
      onClose={onClose}
    >
      <form className="form-grid" onSubmit={submit}>
        <label style={{ gridColumn: '1 / -1' }}>
          <span>{t('pages.dynamicSources.form.label')}</span>
          <input value={values.label} onChange={(event) => set('label', event.target.value)} required />
        </label>
        <label style={{ gridColumn: '1 / -1' }}>
          <span>{t('pages.dynamicSources.form.url')}</span>
          <input type="url" value={values.url} onChange={(event) => set('url', event.target.value)} required disabled={Boolean(source?.point_count)} />
          <small className="muted">{t('pages.dynamicSources.form.urlHint')}</small>
        </label>
        <label>
          <span>{t('pages.dynamicSources.form.adapter')}</span>
          <select
            value={values.adapter}
            disabled={Boolean(source?.point_count)}
            onChange={(event) => {
              const adapter = event.target.value as DynamicTariffSource['adapter']
              setValues((current) => ({
                ...current,
                adapter,
                tariff_type: adapter === 'bkw' ? 'feed_in' : current.tariff_type,
                tariff_name: adapter === 'bkw' ? '' : current.tariff_name,
              }))
            }}
          >
            <option value="vse_v1">{t('pages.dynamicSources.adapters.vse_v1')}</option>
            <option value="groupe_e">{t('pages.dynamicSources.adapters.groupe_e')}</option>
            <option value="bkw">{t('pages.dynamicSources.adapters.bkw')}</option>
          </select>
        </label>
        <label>
          <span>{t('pages.dynamicSources.form.tariffType')}</span>
          <select
            value={values.tariff_type}
            disabled={Boolean(source?.point_count || values.adapter === 'bkw')}
            onChange={(event) => set('tariff_type', event.target.value as DynamicTariffType)}
          >
            {TARIFF_TYPES.map((type) => (
              <option key={type} value={type}>
                {t(`pages.dynamicSources.types.${type}` as Parameters<typeof t>[0])}
              </option>
            ))}
          </select>
        </label>
        {values.adapter !== 'bkw' && (
          <label style={{ gridColumn: '1 / -1' }}>
            <span>{t('pages.dynamicSources.form.tariffName')}</span>
            <input
              value={values.tariff_name ?? ''}
              onChange={(event) => set('tariff_name', event.target.value)}
              required={values.adapter === 'groupe_e'}
              disabled={Boolean(source?.point_count)}
            />
            <small className="muted">
              {values.adapter === 'groupe_e'
                ? t('pages.dynamicSources.form.tariffNameRequired')
                : t('pages.dynamicSources.form.tariffNameHint')}
            </small>
          </label>
        )}
        {source?.point_count ? (
          <div className="info-banner" style={{ gridColumn: '1 / -1' }}>
            {t('pages.dynamicSources.form.identityLocked')}
          </div>
        ) : null}
        {!source && (
          <div className="info-banner" style={{ gridColumn: '1 / -1' }}>
            {t('pages.dynamicSources.form.probeNotice')}
          </div>
        )}
        <FormModalFooter
          onCancel={onClose}
          isPending={mutation.isPending}
          submitLabel={t(source ? 'common.save' : 'pages.dynamicSources.createAction')}
        />
      </form>
    </FormModal>
  )
}
