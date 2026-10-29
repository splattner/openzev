import { zodResolver } from '@hookform/resolvers/zod'
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome'
import { faCheck, faPlus, faXmark } from '@fortawesome/free-solid-svg-icons'
import { useQuery } from '@tanstack/react-query'
import { Controller, useForm, useWatch } from 'react-hook-form'
import { useEffect, useId, useMemo, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { FormModalFooter } from '../../components/FormModalFooter'
import { CivilDateInput } from '../../components/CivilDateInput'
import type { ItemFieldErrors } from '../../lib/api/errors'
import { fetchDynamicTariffSources } from '../../lib/api/tariffs'
import { queryKeys } from '../../lib/api/queryKeys'
import type { Tariff, TariffBillingMode, TariffInput, TariffPeriod } from '../../types/api'
import { dynamicSourceOptions, impliedEnergyType } from './dynamicSources'
import { DynamicSourceForm } from './DynamicSourceFormModal'
import { Notice } from '../../components/Notice'
import { useFocusFirstField } from './useFocusFirstField'
import { TariffDraftBands } from './TariffDraftBands'
import {
  defaultTariffFormValues,
  mapTariffFormValuesToInput,
  mapTariffToFormValues,
  tariffFormSchema,
  type TariffFormValues,
} from './useTariffForms'

/** Label for the fixed-price field, per billing mode that has one. */
const FIXED_PRICE_LABELS: Partial<Record<TariffBillingMode, string>> = {
  monthly_fee: 'pages.tariffs.form.monthlyFee',
  yearly_fee: 'pages.tariffs.form.yearlyFee',
  per_metering_point_monthly_fee: 'pages.tariffs.form.mpMonthlyFee',
  per_metering_point_yearly_fee: 'pages.tariffs.form.mpYearlyFee',
  shared_monthly_fee: 'pages.tariffs.form.sharedMonthlyFee',
  shared_yearly_fee: 'pages.tariffs.form.sharedYearlyFee',
}

const SHARED_FEE_MODES: TariffBillingMode[] = ['shared_monthly_fee', 'shared_yearly_fee']

type TariffFormProps = {
  // Every caller actually passes a `TariffVersion` (the flattened `Tariff[]`
  // lists upstream just don't say so) — `periods` is read to decide whether
  // switching this version to a dynamic source is currently possible.
  initialTariff?: Tariff & { periods?: TariffPeriod[] }
  selectedZevId: string
  isPending?: boolean
  /** A failure that belongs to no field: shown in the form, not only as a toast. */
  error?: string | null
  /** What the server rejected on the bands sent with this new tariff, by position. */
  bandErrors?: ItemFieldErrors[] | null
  onSubmit: (payload: TariffInput) => void
  onCancel: () => void
  /** Whether anything was changed, for the pane's unsaved-input guard. */
  onDirtyChange: (dirty: boolean) => void
}

/**
 * Create a tariff, or edit one version of it, in the detail pane. Creating a
 * dynamic source happens in a section of this form, not a dialog over it.
 */
export function TariffForm({
  initialTariff,
  selectedZevId,
  isPending = false,
  error = null,
  bandErrors = null,
  onSubmit,
  onCancel,
  onDirtyChange,
}: TariffFormProps) {
  const { t } = useTranslation()
  const formId = useId()
  const [showSourceSection, setShowSourceSection] = useState(false)
  const [sourceDirty, setSourceDirty] = useState(false)
  // A band open in the editor is not part of the tariff until it is kept.
  const [bandEditorOpen, setBandEditorOpen] = useState(false)
  const [bandEditorBlocked, setBandEditorBlocked] = useState(false)
  const formRef = useRef<HTMLFormElement>(null)
  useFocusFirstField(formRef)

  const form = useForm<TariffFormValues>({
    resolver: zodResolver(tariffFormSchema),
    // Seeded once, when the form opens: a refetch of the list behind it must
    // not overwrite what is being typed.
    defaultValues: initialTariff ? mapTariffToFormValues(initialTariff) : defaultTariffFormValues,
  })

  const billingMode = useWatch({
    control: form.control,
    name: 'billing_mode',
  })
  const isSharedFee = SHARED_FEE_MODES.includes(billingMode)
  const splitKey = useWatch({
    control: form.control,
    name: 'split_key',
  })
  const dynamicSourceId = useWatch({
    control: form.control,
    name: 'dynamic_source',
  })
  const energyType = useWatch({
    control: form.control,
    name: 'energy_type',
  })
  const draftBands = useWatch({ control: form.control, name: 'initial_periods' })
  const validFrom = useWatch({ control: form.control, name: 'valid_from' })
  const validTo = useWatch({ control: form.control, name: 'valid_to' })
  // An existing tariff is one version of a series; its identity fields are
  // fixed. Creating a new tariff still sets them freely.
  const isVersion = Boolean(initialTariff)
  // The backend refuses to link a dynamic source onto a version that already
  // has price bands (and, symmetrically, to add a band to an already-dynamic
  // version) — switching between the two happens by creating a new version
  // instead. Disabling the picker here surfaces that up front rather than
  // letting the pick fail at submit with a raw field-name toast.
  const hasExistingPeriods = isVersion && (initialTariff?.periods?.length ?? 0) > 0

  // Fetched once per modal session, not gated on billing_mode: the picker
  // only *renders* for an energy tariff, but the list has to be ready by
  // then rather than triggering a fetch (and a loading flash) on every
  // billing-mode change.
  const sourcesQuery = useQuery({
    queryKey: queryKeys.tariffs.dynamicSources(),
    queryFn: fetchDynamicTariffSources,
    staleTime: 5 * 60 * 1000,
  })
  const sourcesData = sourcesQuery.data
  const availableSources = dynamicSourceOptions(sourcesData ?? [], isVersion ? initialTariff?.energy_type : undefined)
  const selectedSourceAggregatedTypes = useMemo(() => {
    const source = sourcesData?.find((candidate) => candidate.id === dynamicSourceId)
    return source?.aggregated_tariff_types ?? []
  }, [sourcesData, dynamicSourceId])

  const isDirty = form.formState.isDirty || (showSourceSection && sourceDirty)
  useEffect(() => { onDirtyChange(isDirty) }, [isDirty, onDirtyChange])

  // A field's problem is told by the field. The schema's own messages are
  // English and generic; the form says it in the user's language.
  const errors = form.formState.errors
  const fieldError = (field: keyof TariffFormValues) => {
    if (!errors[field]) return null
    const value = form.getValues(field)
    return (
      <small className="field-error" role="alert">
        {t(typeof value === 'string' && value.trim() ? 'pages.tariffs.form.errorNumber' : 'pages.tariffs.form.errorRequired')}
      </small>
    )
  }

  // Picking a source is what decides the energy type for a brand-new tariff
  // (there is nothing else to derive it from); an existing version's energy
  // type is already locked, so the picker above already only offers sources
  // that agree with it, and nothing here needs to change it.
  useEffect(() => {
    if (isVersion || !dynamicSourceId || !sourcesData) return
    const source = sourcesData.find((candidate) => candidate.id === dynamicSourceId)
    if (source) {
      const energyType = impliedEnergyType(source)
      if (energyType) form.setValue('energy_type', energyType, { shouldValidate: true })
    }
  }, [dynamicSourceId, isVersion, sourcesData, form])

  // A new static energy tariff can start with its bands; a fetched series
  // prices a dynamic one, and every other mode has none.
  const takesInitialBands = !isVersion && billingMode === 'energy' && !dynamicSourceId

  function submit(values: TariffFormValues) {
    if (takesInitialBands && bandEditorOpen) {
      setBandEditorBlocked(true)
      return
    }
    onSubmit(mapTariffFormValuesToInput(values, selectedZevId))
  }

  return (
    <div className="tariff-pane-form">
      {error && <Notice tone="error">{error}</Notice>}
      {bandEditorBlocked && bandEditorOpen && <Notice tone="error">{t('pages.tariffs.form.finishBandFirst')}</Notice>}
      {isVersion && <p className="muted m-0">{t('pages.tariffs.form.correctionHint')}</p>}
      <form ref={formRef} id={formId} onSubmit={form.handleSubmit(submit)} className="form-grid" aria-busy={isPending || undefined}>
       <fieldset className="tariff-pane-fieldset" disabled={isPending}>
        {/* Editing an existing tariff means editing one *version* of it: the pane
            header already names the tariff, and the name, category, billing mode
            and energy type are shared by all versions, so none of them is shown
            as a field. They still reach the payload from the form state seeded by
            reset(); registering them as disabled inputs would blank them. */}
        {isVersion ? null : (
          <>
            <label>
              <span>{t('pages.tariffs.form.name')}</span>
              <input {...form.register('name')} required />
              {fieldError('name')}
            </label>
            <label>
              <span>{t('pages.tariffs.form.category')}</span>
              <select {...form.register('category')}>
                <option value="energy">{t('pages.tariffs.categories.energy')}</option>
                <option value="grid_fees">{t('pages.tariffs.categories.grid_fees')}</option>
                <option value="levies">{t('pages.tariffs.categories.levies')}</option>
                <option value="metering">{t('pages.tariffs.categories.metering')}</option>
              </select>
            </label>
            <label>
              <span>{t('pages.tariffs.form.billingMode')}</span>
              <select {...form.register('billing_mode')}>
                <option value="energy">{t('pages.tariffs.billingModes.energy')}</option>
                <option value="percentage_of_energy">{t('pages.tariffs.billingModes.percentage_of_energy')}</option>
                <option value="monthly_fee">{t('pages.tariffs.billingModes.monthly_fee')}</option>
                <option value="yearly_fee">{t('pages.tariffs.billingModes.yearly_fee')}</option>
                <option value="per_metering_point_monthly_fee">{t('pages.tariffs.billingModes.per_metering_point_monthly_fee')}</option>
                <option value="per_metering_point_yearly_fee">{t('pages.tariffs.billingModes.per_metering_point_yearly_fee')}</option>
                <option value="shared_monthly_fee">{t('pages.tariffs.billingModes.shared_monthly_fee')}</option>
                <option value="shared_yearly_fee">{t('pages.tariffs.billingModes.shared_yearly_fee')}</option>
              </select>
            </label>
            {(billingMode === 'energy' || billingMode === 'percentage_of_energy') && (
              <label>
                <span>{t('pages.tariffs.form.energyType')}</span>
                <select {...form.register('energy_type')}>
                  <option value="local">{t('pages.tariffs.energyTypes.local')}</option>
                  <option value="grid">{t('pages.tariffs.energyTypes.grid')}</option>
                  <option value="feed_in">{t('pages.tariffs.energyTypes.feed_in')}</option>
                </select>
              </label>
            )}
          </>
        )}

        {/* Only a plain energy tariff can be dynamic — a percentage-of-energy
            or fixed-fee tariff has nothing a fetched series could price. */}
        {billingMode === 'energy' && (
          <div style={{ gridColumn: '1 / -1', display: 'grid', gap: '0.5rem' }}>
            <label>
              <span>{t('pages.tariffs.form.dynamicSource')}</span>
              <select {...form.register('dynamic_source')} disabled={sourcesQuery.isLoading || hasExistingPeriods}>
                <option value="">{t('pages.tariffs.form.dynamicSourceNone')}</option>
                {availableSources.map((source) => (
                  <option key={source.id} value={source.id}>{source.label}</option>
                ))}
              </select>
              <small className="muted">
                {hasExistingPeriods
                  ? t('pages.tariffs.form.dynamicSourceBlockedByPeriods')
                  : dynamicSourceId
                    ? t('pages.tariffs.form.dynamicSourceHintActive')
                    : t('pages.tariffs.form.dynamicSourceHint')}
              </small>
            </label>
            <p className="muted m-0">{t('pages.tariffs.form.sharedSourceHint')}</p>
            {energyType === 'feed_in' && dynamicSourceId && (
              <label>
                <span>{t('pages.tariffs.form.minimumPrice')}</span>
                <input
                  type="number"
                  step="0.00001"
                  min="0"
                  placeholder={t('pages.tariffs.form.minimumPricePlaceholder')}
                  {...form.register('minimum_price_chf_per_kwh')}
                />
                <small className="muted">{t('pages.tariffs.form.minimumPriceHint')}</small>
                {fieldError('minimum_price_chf_per_kwh')}
              </label>
            )}
            {selectedSourceAggregatedTypes.length > 0 && (
              <div className="warning-banner">
                {t('pages.dynamicSources.form.doubleCountingWarning', {
                  components: selectedSourceAggregatedTypes
                    .map((type) => t(`pages.dynamicSources.types.${type}` as Parameters<typeof t>[0]))
                    .join(', '),
                })}
              </div>
            )}
            {!isVersion && (
              <div>
                <button
                  className="button button-secondary button-compact"
                  type="button"
                  onClick={() => setShowSourceSection(true)}
                >
                  <FontAwesomeIcon icon={faPlus} fixedWidth />
                  {t('pages.tariffs.form.createDynamicSource')}
                </button>
              </div>
            )}
          </div>
        )}

        {billingMode === 'percentage_of_energy' ? (
          // Editing a version already has bands to manage in the drawer, so
          // the field is create-only (§5.7) — it just seeds the first one.
          !isVersion && (
            <label>
              <span>{t('pages.tariffs.form.initialPercentage')}</span>
              <input type="number" step="0.01" min="0" {...form.register('initial_percentage')} required />
              <small className="muted">{t('pages.tariffs.form.initialPercentageHint')}</small>
              {fieldError('initial_percentage')}
            </label>
          )
        ) : billingMode !== 'energy' ? (
          <label>
            <span>{t(FIXED_PRICE_LABELS[billingMode] ?? 'pages.tariffs.form.monthlyFee')}</span>
            <input type="number" step="0.01" {...form.register('fixed_price_chf')} required />
            {fieldError('fixed_price_chf')}
            {isSharedFee && (
              <small className="muted">
                {t(splitKey === 'weight' ? 'pages.tariffs.form.sharedFeeHintWeight' : 'pages.tariffs.form.sharedFeeHint')}
              </small>
            )}
          </label>
        ) : null}

        {isSharedFee && (
          <label>
            <span>{t('pages.tariffs.form.splitKey')}</span>
            <select {...form.register('split_key')}>
              <option value="equal">{t('pages.tariffs.form.splitKeyEqual')}</option>
              <option value="weight">{t('pages.tariffs.form.splitKeyWeight')}</option>
            </select>
          </label>
        )}

        <label>
          <span>{t('pages.tariffs.form.validFrom')}</span>
          <Controller
            control={form.control}
            name="valid_from"
            render={({ field }) => (
              <CivilDateInput
                value={field.value || null}
                onChange={(iso) => field.onChange(iso ?? '')}
              />
            )}
          />
        </label>
        <label>
          <span>{t('pages.tariffs.form.validTo')}</span>
          <Controller
            control={form.control}
            name="valid_to"
            render={({ field }) => (
              <CivilDateInput
                value={field.value || null}
                onChange={(iso) => field.onChange(iso ?? '')}
              />
            )}
          />
        </label>
        <label className="grid-span-full">
          <span>{t('pages.tariffs.form.notes')}</span>
          <textarea rows={3} {...form.register('notes')} />
        </label>

       </fieldset>
      </form>
      {takesInitialBands && (
        <TariffDraftBands
          bands={draftBands}
          onChange={(next) => form.setValue('initial_periods', next, { shouldDirty: true })}
          validity={{ valid_from: validFrom, valid_to: validTo || null }}
          serverErrors={bandErrors}
          disabled={isPending}
          onEditingChange={(open) => {
            setBandEditorOpen(open)
            if (!open) setBandEditorBlocked(false)
          }}
        />
      )}
      {showSourceSection && (
        <section className="tariff-pane-section" aria-labelledby={`${formId}-source`}>
          <h3 id={`${formId}-source`}>{t('pages.dynamicSources.createTitle')}</h3>
          <DynamicSourceForm
            onClose={() => setShowSourceSection(false)}
            onDirtyChange={setSourceDirty}
            onSaved={(source) => {
              form.setValue('dynamic_source', source.id, { shouldValidate: true, shouldDirty: true })
              const energyType = impliedEnergyType(source)
              if (energyType) form.setValue('energy_type', energyType, { shouldValidate: true })
            }}
          />
        </section>
      )}
      <FormModalFooter
        formId={formId}
        onCancel={onCancel}
        isPending={isPending}
        submitLabel={isPending ? t('common.saving') : initialTariff ? t('pages.tariffs.saveTariff') : t('pages.tariffs.createTariff')}
        submitIcon={<FontAwesomeIcon icon={faCheck} fixedWidth />}
        cancelIcon={<FontAwesomeIcon icon={faXmark} fixedWidth />}
      />
    </div>
  )
}
