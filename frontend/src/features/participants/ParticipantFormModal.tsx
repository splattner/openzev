import { zodResolver } from '@hookform/resolvers/zod'
import { useEffect } from 'react'
import { useForm } from 'react-hook-form'
import { useTranslation } from 'react-i18next'
import { FormModal } from '../../components/FormModal'
import type { Participant, ParticipantInput } from '../../types/api'
import {
  defaultParticipantFormValues,
  mapParticipantFormValuesToInput,
  mapParticipantToFormValues,
  participantFormSchema,
  type ParticipantFormValues,
} from './useParticipantForm'

type ParticipantFormModalProps = {
  isOpen: boolean
  title: string
  onClose: () => void
  onSubmit: (payload: ParticipantInput) => void
  initialParticipant?: Participant
  selectedZevId: string
  isPending?: boolean
}

export function ParticipantFormModal({
  isOpen,
  title,
  onClose,
  onSubmit,
  initialParticipant,
  selectedZevId,
  isPending = false,
}: ParticipantFormModalProps) {
  const { t } = useTranslation()
  const form = useForm<ParticipantFormValues>({
    resolver: zodResolver(participantFormSchema),
    defaultValues: defaultParticipantFormValues,
  })

  useEffect(() => {
    form.reset(initialParticipant ? mapParticipantToFormValues(initialParticipant) : defaultParticipantFormValues)
  }, [initialParticipant, form, isOpen])

  function submit(values: ParticipantFormValues) {
    onSubmit(mapParticipantFormValuesToInput(values, selectedZevId))
  }

  const titleOptions = [
    { value: '' as const, label: t('pages.zevs.titles.none') },
    { value: 'mr' as const, label: t('pages.zevs.titles.mr') },
    { value: 'mrs' as const, label: t('pages.zevs.titles.mrs') },
    { value: 'ms' as const, label: t('pages.zevs.titles.ms') },
    { value: 'dr' as const, label: t('pages.zevs.titles.dr') },
    { value: 'prof' as const, label: t('pages.zevs.titles.prof') },
  ]

  return (
    <FormModal isOpen={isOpen} title={title} onClose={onClose} maxWidth="960px">
      <form onSubmit={form.handleSubmit(submit)} className="form-grid">
        <label>
          <span>{t('pages.participants.form.title')}</span>
          <select {...form.register('title')}>
            {titleOptions.map((option) => (
              <option key={option.value || 'none'} value={option.value}>{option.label}</option>
            ))}
          </select>
        </label>
        <label>
          <span>{t('pages.participants.form.firstName')}</span>
          <input {...form.register('first_name')} required />
        </label>
        <label>
          <span>{t('pages.participants.form.lastName')}</span>
          <input {...form.register('last_name')} required />
        </label>
        <label>
          <span>{t('pages.participants.form.email')}</span>
          <input type="email" {...form.register('email')} required />
        </label>
        <label>
          <span>{t('pages.participants.form.phone')}</span>
          <input {...form.register('phone')} />
        </label>
        <label style={{ gridColumn: '1 / -1' }}>
          <span>{t('pages.participants.form.addressLine1')}</span>
          <input {...form.register('address_line1')} />
        </label>
        <label style={{ gridColumn: '1 / -1' }}>
          <span>{t('pages.participants.form.addressLine2')}</span>
          <input {...form.register('address_line2')} />
        </label>
        <label>
          <span>{t('pages.participants.form.postalCode')}</span>
          <input {...form.register('postal_code')} />
        </label>
        <label>
          <span>{t('pages.participants.form.city')}</span>
          <input {...form.register('city')} />
        </label>
        <label>
          <span>{t('pages.participants.form.validFrom')}</span>
          <input type="date" {...form.register('valid_from')} required />
        </label>
        <label>
          <span>{t('pages.participants.form.validTo')}</span>
          <input type="date" {...form.register('valid_to')} />
        </label>
        <label>
          <span>{t('pages.participants.form.allocationWeight')}</span>
          <input type="number" step="any" min="0" placeholder="1" {...form.register('allocation_weight')} />
        </label>
        <p className="muted" style={{ gridColumn: '1 / -1', margin: 0, fontSize: '0.82rem' }}>
          {t('pages.participants.form.allocationWeightHint')}
        </p>
        <label style={{ gridColumn: '1 / -1' }}>
          <span>{t('pages.participants.form.notes')}</span>
          <textarea {...form.register('notes')} rows={3} />
        </label>

        {Object.keys(form.formState.errors).length > 0 && (
          <div className="error-banner" style={{ gridColumn: '1 / -1' }}>
            {form.formState.errors.first_name?.message
              || form.formState.errors.last_name?.message
              || form.formState.errors.email?.message
              || form.formState.errors.valid_from?.message
              || form.formState.errors.allocation_weight?.message
              || t('common.error')}
          </div>
        )}

        <div style={{ gridColumn: '1 / -1', display: 'flex', gap: '1rem', justifyContent: 'flex-end', marginTop: '1rem' }}>
          <button className="button button-secondary" type="button" onClick={onClose}>
            {t('common.cancel')}
          </button>
          <button className="button button-primary" type="submit" disabled={isPending}>
            {initialParticipant ? t('pages.participants.saveParticipant') : t('common.create')}
          </button>
        </div>
      </form>
    </FormModal>
  )
}
