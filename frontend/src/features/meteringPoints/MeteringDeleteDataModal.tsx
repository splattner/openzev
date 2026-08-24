import { DatePickerInput } from '@mantine/dates'
import { useTranslation } from 'react-i18next'
import { FormModal } from '../../components/FormModal'
import { quickRangeToDates } from '../../lib/dateRangePresets'
import { toDayJsDateFormat } from '../../lib/appSettings'
import type { AppSettings } from '../../types/api'

type MeteringDeleteDataModalProps = {
  isOpen: boolean
  meterId?: string
  mode: 'all' | 'range'
  dateFrom: string
  dateTo: string
  settings: AppSettings
  isPending: boolean
  onClose: () => void
  onConfirm: () => void
  onChangeMode: (mode: 'all' | 'range') => void
  onChangeRange: (dateFrom: string, dateTo: string) => void
}

export function MeteringDeleteDataModal({
  isOpen,
  meterId,
  mode,
  dateFrom,
  dateTo,
  settings,
  isPending,
  onClose,
  onConfirm,
  onChangeMode,
  onChangeRange,
}: MeteringDeleteDataModalProps) {
  const { t } = useTranslation()

  return (
    <FormModal isOpen={isOpen} title={t('pages.meteringPoints.deleteData.title')} onClose={onClose}>
      <div className="page-stack" style={{ gap: '1rem' }}>
        <p className="muted" style={{ margin: 0, lineHeight: 1.45 }}>
          {t('pages.meteringPoints.deleteData.description', { meterId: meterId ?? '' })}
        </p>

        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: '0.75rem' }}>
          <label
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '0.6rem',
              border: mode === 'all' ? '2px solid var(--brand-mid)' : '1px solid var(--border-default)',
              borderRadius: '0.6rem',
              padding: '0.75rem 0.85rem',
              background: mode === 'all' ? 'var(--brand-pale)' : 'var(--surface-card)',
              cursor: 'pointer',
            }}
          >
            <input
              type="radio"
              name="deleteDataMode"
              checked={mode === 'all'}
              onChange={() => onChangeMode('all')}
            />
            <span style={{ fontWeight: 600 }}>{t('pages.meteringPoints.deleteData.modeAll')}</span>
          </label>

          <label
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '0.6rem',
              border: mode === 'range' ? '2px solid var(--brand-mid)' : '1px solid var(--border-default)',
              borderRadius: '0.6rem',
              padding: '0.75rem 0.85rem',
              background: mode === 'range' ? 'var(--brand-pale)' : 'var(--surface-card)',
              cursor: 'pointer',
            }}
          >
            <input
              type="radio"
              name="deleteDataMode"
              checked={mode === 'range'}
              onChange={() => onChangeMode('range')}
            />
            <span style={{ fontWeight: 600 }}>{t('pages.meteringPoints.deleteData.modeRange')}</span>
          </label>
        </div>

        {mode === 'range' && (
          <label style={{ display: 'grid', gap: '0.4rem' }}>
            <span style={{ fontWeight: 600 }}>{t('pages.meteringPoints.deleteData.rangeLabel')}</span>
            <DatePickerInput
              type="range"
              value={[dateFrom || null, dateTo || null]}
              onChange={([nextFrom, nextTo]) => {
                onChangeRange(nextFrom ?? '', nextTo ?? '')
              }}
              presets={[
                {
                  value: (() => {
                    const range = quickRangeToDates('this_month')
                    return [range.from, range.to] as [string, string]
                  })(),
                  label: t('common.periodSelector.thisMonth'),
                },
                {
                  value: (() => {
                    const range = quickRangeToDates('last_month')
                    return [range.from, range.to] as [string, string]
                  })(),
                  label: t('common.periodSelector.lastMonth'),
                },
                {
                  value: (() => {
                    const range = quickRangeToDates('this_quarter')
                    return [range.from, range.to] as [string, string]
                  })(),
                  label: t('common.periodSelector.thisQuarter'),
                },
                {
                  value: (() => {
                    const range = quickRangeToDates('last_quarter')
                    return [range.from, range.to] as [string, string]
                  })(),
                  label: t('common.periodSelector.lastQuarter'),
                },
                {
                  value: (() => {
                    const range = quickRangeToDates('this_year')
                    return [range.from, range.to] as [string, string]
                  })(),
                  label: t('common.periodSelector.thisYear'),
                },
                {
                  value: (() => {
                    const range = quickRangeToDates('last_year')
                    return [range.from, range.to] as [string, string]
                  })(),
                  label: t('common.periodSelector.lastYear'),
                },
              ]}
              valueFormat={toDayJsDateFormat(settings.date_format_short)}
              clearable={false}
              popoverProps={{ withinPortal: true, zIndex: 1400 }}
            />
          </label>
        )}

        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '0.75rem', marginTop: '0.25rem' }}>
          <button className="button button-secondary" type="button" onClick={onClose}>
            {t('common.cancel')}
          </button>
          <button className="button button-danger" type="button" onClick={onConfirm} disabled={isPending}>
            {t('pages.meteringPoints.deleteData.confirm')}
          </button>
        </div>
      </div>
    </FormModal>
  )
}
