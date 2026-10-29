import { zodResolver } from '@hookform/resolvers/zod'
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome'
import { faCheck, faPen, faPlus, faTrash, faXmark } from '@fortawesome/free-solid-svg-icons'
import { useState, type KeyboardEvent } from 'react'
import { useForm } from 'react-hook-form'
import { useTranslation } from 'react-i18next'
import type { ItemFieldErrors } from '../../lib/api/errors'
import { bandName } from './bands'
import { MONTH_KEYS, WEEKDAY_KEYS } from './recurrence'
import { formatBandSchedule, kwhPrice } from './rateLines'
import { TariffBandCoverage } from './TariffBandCoverage'
import { TariffBandFields, toCoverageBand, useWatchedBand } from './TariffBandFields'
import {
  defaultTariffPeriodFormValues,
  tariffBandDraftSchema,
  type TariffPeriodFormValues,
} from './useTariffForms'

/** The request field a server message names, as the label the form shows it under. */
const FIELD_LABELS: Record<string, string> = {
  period_type: 'pages.tariffs.form.periodType',
  label: 'pages.tariffs.form.bandLabel',
  price_chf_per_kwh: 'pages.tariffs.form.pricePerKwh',
  percentage: 'pages.tariffs.form.percentage',
  time_from: 'pages.tariffs.form.timeFrom',
  time_to: 'pages.tariffs.form.timeTo',
  weekdays: 'pages.tariffs.form.weekdays',
  months: 'pages.tariffs.form.months',
}

type TariffDraftBandsProps = {
  bands: TariffPeriodFormValues[]
  onChange: (next: TariffPeriodFormValues[]) => void
  /** The tariff's validity as typed so far: the coverage preview only looks at the weeks it can meet. */
  validity: { valid_from?: string, valid_to?: string | null }
  /** What the server rejected, by position in `bands` as they were sent; replaced by every new response. */
  serverErrors?: ItemFieldErrors[] | null
  disabled?: boolean
  /** A band is open in the editor: its input is not part of the tariff until it is kept. */
  onEditingChange: (editing: boolean) => void
}

/**
 * The bands a new static energy tariff starts with, added, changed and
 * removed before the tariff exists. They are written with it, all or nothing.
 */
export function TariffDraftBands({
  bands,
  onChange,
  validity,
  serverErrors = null,
  disabled = false,
  onEditingChange,
}: TariffDraftBandsProps) {
  const { t } = useTranslation()
  // A band index, 'new' for a band being added, or nothing open.
  const [editing, setEditing] = useState<number | 'new' | null>(null)
  // The server's verdict is about the bands as sent; it follows them while they
  // are edited here, and a new verdict replaces it.
  const [errors, setErrors] = useState(serverErrors)
  const [seenErrors, setSeenErrors] = useState(serverErrors)
  if (serverErrors !== seenErrors) {
    setSeenErrors(serverErrors)
    setErrors(serverErrors)
  }

  const monthNames = MONTH_KEYS.map((key) => t(`pages.tariffs.monthsShort.${key}` as Parameters<typeof t>[0]))
  const dayNames = WEEKDAY_KEYS.map((key) => t(`pages.tariffs.weekdaysShort.${key}` as Parameters<typeof t>[0]))

  function open(next: number | 'new' | null) {
    setEditing(next)
    onEditingChange(next !== null)
  }

  function keep(values: TariffPeriodFormValues) {
    if (editing === 'new') {
      onChange([...bands, values])
    } else if (editing !== null) {
      onChange(bands.map((band, index) => (index === editing ? values : band)))
      setErrors(errors && errors.map((entry, index) => (index === editing ? {} : entry)))
    }
    open(null)
  }

  function remove(index: number) {
    onChange(bands.filter((_, position) => position !== index))
    setErrors(errors && errors.filter((_, position) => position !== index))
    open(null)
  }

  function describe(band: TariffPeriodFormValues) {
    return formatBandSchedule({ ...band, time_from: band.time_from || null, time_to: band.time_to || null }, t, dayNames, monthNames)
  }

  function rowErrors(index: number) {
    return Object.entries(errors?.[index] ?? {}).map(([field, messages]) => (
      FIELD_LABELS[field] ? `${t(FIELD_LABELS[field] as Parameters<typeof t>[0])}: ` : ''
    ) + messages.join(' '))
  }

  const editor = (initial: TariffPeriodFormValues, index: number | 'new') => (
    <DraftBandEditor
      key={index}
      initial={initial}
      others={bands.filter((_, position) => position !== index).map(toCoverageBand)}
      validity={validity}
      serverErrors={index === 'new' ? undefined : errors?.[index]}
      onKeep={keep}
      onCancel={() => open(null)}
    />
  )

  return (
    <section className="tariff-pane-section tariff-draft-bands" aria-label={t('pages.tariffs.form.bandsTitle')}>
      <h3>{t('pages.tariffs.form.bandsTitle')}</h3>
      <p className="muted tariff-period-empty">{t('pages.tariffs.form.bandsHint')}</p>
      <fieldset className="tariff-pane-fieldset" disabled={disabled}>
        {bands.length > 0 && (
          <div className="tariff-period-list">
            {bands.map((band, index) => {
              if (editing === index) return editor(band, index)
              const messages = rowErrors(index)
              const name = bandName(band, t(`pages.tariffs.periodTypes.${band.period_type}` as Parameters<typeof t>[0]))
              return (
                <div key={index} className={`tariff-period-row${messages.length > 0 ? ' has-error' : ''}`}>
                  <div className="tariff-period-main">
                    <div className="tariff-period-line">
                      <span className="badge badge-neutral">{name}</span>
                      <strong>CHF {kwhPrice.format(Number(band.price_chf_per_kwh))}/kWh</strong>
                    </div>
                    <div className="muted tariff-period-meta">{describe(band)}</div>
                    {messages.map((message) => (
                      <small key={message} className="field-error" role="alert">{message}</small>
                    ))}
                  </div>
                  <div className="tariff-period-actions">
                    <button
                      className="button button-secondary button-compact"
                      type="button"
                      onClick={() => open(index)}
                      title={t('common.edit')}
                      aria-label={`${t('common.edit')}: ${name}`}
                    >
                      <FontAwesomeIcon icon={faPen} fixedWidth />
                    </button>
                    <button
                      className="button button-danger button-compact"
                      type="button"
                      onClick={() => remove(index)}
                      title={t('common.delete')}
                      aria-label={`${t('common.delete')}: ${name}`}
                    >
                      <FontAwesomeIcon icon={faTrash} fixedWidth />
                    </button>
                  </div>
                </div>
              )
            })}
          </div>
        )}
        {editing === 'new' && editor({ ...defaultTariffPeriodFormValues, billing_mode: 'energy' }, 'new')}
        {editing === null && (
          <button className="button button-ghost button-compact tariff-add-band" type="button" onClick={() => open('new')}>
            <FontAwesomeIcon icon={faPlus} fixedWidth />
            {t('pages.tariffs.form.addBand')}
          </button>
        )}
        {editing === null && bands.length > 0 && (
          <TariffBandCoverage bands={bands.map(toCoverageBand)} validity={validity} showCovered />
        )}
      </fieldset>
    </section>
  )
}

type DraftBandEditorProps = {
  initial: TariffPeriodFormValues
  others: ReturnType<typeof toCoverageBand>[]
  validity: TariffDraftBandsProps['validity']
  serverErrors?: ItemFieldErrors
  onKeep: (values: TariffPeriodFormValues) => void
  onCancel: () => void
}

/**
 * One band in the create form. It is not a `<form>` of its own because it
 * sits beside the tariff's: Enter keeps the band instead of submitting the
 * tariff.
 */
function DraftBandEditor({ initial, others, validity, serverErrors, onKeep, onCancel }: DraftBandEditorProps) {
  const { t } = useTranslation()
  const form = useForm<TariffPeriodFormValues>({
    resolver: zodResolver(tariffBandDraftSchema),
    defaultValues: initial,
  })
  const { band, complete } = useWatchedBand(form.control)
  const keep = form.handleSubmit(onKeep)

  function onKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    if (event.key === 'Enter' && event.target instanceof HTMLInputElement) {
      event.preventDefault()
      void keep()
    }
  }

  return (
    <div className="tariff-draft-band-editor" onKeyDown={onKeyDown}>
      <div className="form-grid">
        <TariffBandFields form={form} serverErrors={serverErrors} />
        {complete && <TariffBandCoverage bands={[...others, band]} validity={validity} showCovered />}
      </div>
      <div className="tariff-draft-band-actions">
        <button className="button button-primary button-compact" type="button" onClick={() => void keep()}>
          <FontAwesomeIcon icon={faCheck} fixedWidth />
          {t('pages.tariffs.form.keepBand')}
        </button>
        <button className="button button-secondary button-compact" type="button" onClick={onCancel}>
          <FontAwesomeIcon icon={faXmark} fixedWidth />
          {t('common.cancel')}
        </button>
      </div>
    </div>
  )
}
