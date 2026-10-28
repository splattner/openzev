import { zodResolver } from '@hookform/resolvers/zod'
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome'
import { faCheck, faTrash, faXmark } from '@fortawesome/free-solid-svg-icons'
import { useEffect, useId, useRef } from 'react'
import { useForm } from 'react-hook-form'
import { useTranslation } from 'react-i18next'
import { Notice } from '../../components/Notice'
import { useFocusFirstField } from './useFocusFirstField'
import { TariffBandFields, useWatchedBand } from './TariffBandFields'
import { TariffBandCoverage } from './TariffBandCoverage'
import { FormModalFooter } from '../../components/FormModalFooter'
import type { Tariff, TariffPeriod, TariffPeriodInput } from '../../types/api'
import {
  defaultTariffPeriodFormValues,
  mapTariffPeriodFormValuesToInput,
  mapTariffPeriodToFormValues,
  tariffPeriodFormSchema,
  type TariffPeriodFormValues,
} from './useTariffForms'

type TariffPeriodFormProps = {
  onSubmit: (payload: TariffPeriodInput) => void
  onCancel: () => void
  /** Whether anything was changed, for the pane's unsaved-input guard. */
  onDirtyChange: (dirty: boolean) => void
  initialPeriod?: TariffPeriod
  /** The version the band belongs to: the one the pane shows. */
  defaultTariffId?: string
  /** Energy and percentage-of-energy tariffs: the only two modes that take bands. */
  tariffs: Tariff[]
  /** Every band of every version: the owner's other bands are what this one is checked against. */
  periods: TariffPeriod[]
  isPending?: boolean
  /** A failure that belongs to no field: shown in the form, not only as a toast. */
  error?: string | null
  /** Delete the band being edited (asks first); absent while adding one. */
  onDelete?: () => void
}

/** Add or change a price band of the shown version, in the detail pane. */
export function TariffPeriodForm({
  onSubmit,
  onCancel,
  onDirtyChange,
  initialPeriod,
  defaultTariffId,
  tariffs,
  periods,
  isPending = false,
  error = null,
  onDelete,
}: TariffPeriodFormProps) {
  const { t } = useTranslation()
  const formId = useId()
  const formRef = useRef<HTMLFormElement>(null)
  useFocusFirstField(formRef)

  const owner = tariffs.find((tariff) => tariff.id === (initialPeriod?.tariff ?? defaultTariffId))
  const form = useForm<TariffPeriodFormValues>({
    resolver: zodResolver(tariffPeriodFormSchema),
    // Seeded once, when the form opens: a refetch of the list behind it must
    // not overwrite what is being typed.
    defaultValues: initialPeriod
      ? mapTariffPeriodToFormValues(initialPeriod, owner?.billing_mode ?? 'energy')
      : {
        ...defaultTariffPeriodFormValues,
        tariff: defaultTariffId ?? defaultTariffPeriodFormValues.tariff,
        billing_mode: owner?.billing_mode ?? 'energy',
      },
  })

  const isDirty = form.formState.isDirty
  useEffect(() => { onDirtyChange(isDirty) }, [isDirty, onDirtyChange])

  function submit(values: TariffPeriodFormValues) {
    onSubmit(mapTariffPeriodFormValuesToInput(values))
  }

  // The version's bands as they would be if this one were saved now.
  const { band, complete: draftComplete } = useWatchedBand(form.control)
  const siblings = periods.filter((period) => period.tariff === owner?.id && period.id !== initialPeriod?.id)
  const versionBands = [...siblings, { ...band, id: initialPeriod?.id }]

  return (
    <div className="tariff-pane-form">
      {error && <Notice tone="error">{error}</Notice>}
      <form ref={formRef} id={formId} onSubmit={form.handleSubmit(submit)} className="form-grid" aria-busy={isPending || undefined}>
       <fieldset className="tariff-pane-fieldset" disabled={isPending}>
        <TariffBandFields form={form} />
        {draftComplete && <TariffBandCoverage bands={versionBands} validity={owner} showCovered />}
       </fieldset>
      </form>
      {onDelete && (
        <div className="tariff-pane-delete">
          <button type="button" className="button button-danger button-compact" onClick={onDelete} disabled={isPending}>
            <FontAwesomeIcon icon={faTrash} fixedWidth />
            {t('common.delete')}
          </button>
        </div>
      )}
      <FormModalFooter
        formId={formId}
        onCancel={onCancel}
        isPending={isPending}
        submitLabel={isPending ? t('common.saving') : initialPeriod ? t('pages.tariffs.savePeriod') : t('pages.tariffs.createPeriod')}
        submitIcon={<FontAwesomeIcon icon={faCheck} fixedWidth />}
        cancelIcon={<FontAwesomeIcon icon={faXmark} fixedWidth />}
      />
    </div>
  )
}
