import { zodResolver } from '@hookform/resolvers/zod'
import { useQuery } from '@tanstack/react-query'
import { useEffect, useRef } from 'react'
import { Controller, useForm, useWatch } from 'react-hook-form'
import { useTranslation } from 'react-i18next'
import { CivilDateInput } from '../../components/CivilDateInput'
import { FormModal } from '../../components/FormModal'
import { FormModalFooter } from '../../components/FormModalFooter'
import { fetchParties } from '../../lib/api/zev'
import { queryKeys } from '../../lib/api/queryKeys'
import { TITLE_KEYS } from '../../lib/participantTitle'
import type { Participant, ParticipantInput, Party } from '../../types/api'
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
  /** Deep-link contract (`?focus=<id>&field=valid_to`): focus this field after the modal opens. */
  focusField?: 'valid_to' | null
}

export function ParticipantFormModal({
  isOpen,
  title,
  onClose,
  onSubmit,
  initialParticipant,
  selectedZevId,
  isPending = false,
  focusField = null,
}: ParticipantFormModalProps) {
  const { t } = useTranslation()
  const form = useForm<ParticipantFormValues>({
    resolver: zodResolver(participantFormSchema),
    defaultValues: defaultParticipantFormValues,
  })
  const validToRef = useRef<HTMLButtonElement | null>(null)
  const isCreate = !initialParticipant
  // "Same person as …": a new participation of an existing party (ADR 0028).
  const partiesQuery = useQuery({
    queryKey: queryKeys.zev.parties(selectedZevId),
    queryFn: () => fetchParties(selectedZevId),
    enabled: isOpen && isCreate && Boolean(selectedZevId),
  })
  const kind = useWatch({ control: form.control, name: 'kind' })
  const partyId = useWatch({ control: form.control, name: 'party' })
  const shared = Boolean(partyId)

  useEffect(() => {
    form.reset(initialParticipant ? mapParticipantToFormValues(initialParticipant) : defaultParticipantFormValues)
  }, [initialParticipant, form, isOpen])

  useEffect(() => {
    if (!isOpen || focusField !== 'valid_to') return
    const timer = window.setTimeout(() => validToRef.current?.focus(), 60)
    return () => window.clearTimeout(timer)
  }, [isOpen, focusField])

  function pickParty(id: string) {
    form.setValue('party', id)
    const party: Party | undefined = (partiesQuery.data ?? []).find((candidate) => candidate.id === id)
    if (!party) return
    for (const field of [
      'kind', 'title', 'first_name', 'last_name', 'organisation_name', 'name_addition',
      'email', 'phone', 'address_line1', 'address_line2', 'postal_code', 'city',
    ] as const) {
      form.setValue(field, (party[field] ?? '') as never)
    }
  }

  function submit(values: ParticipantFormValues) {
    onSubmit(mapParticipantFormValuesToInput(values, selectedZevId))
  }

  const titleOptions = [
    { value: '' as const, label: t('pages.zevs.titles.none') },
    ...TITLE_KEYS.map((k) => ({ value: k, label: t(`pages.zevs.titles.${k}` as Parameters<typeof t>[0]) })),
  ]

  return (
    <FormModal isOpen={isOpen} title={title} onClose={onClose} maxWidth="960px">
      <form onSubmit={form.handleSubmit(submit)} className="form-grid">
        {isCreate && (partiesQuery.data ?? []).length > 0 && (
          <label style={{ gridColumn: '1 / -1' }}>
            <span>{t('pages.participants.form.sameParty')}</span>
            <select value={partyId} onChange={(event) => (event.target.value ? pickParty(event.target.value) : form.setValue('party', ''))}>
              <option value="">{t('pages.participants.form.newParty')}</option>
              {(partiesQuery.data ?? []).map((party) => (
                <option key={party.id} value={party.id}>{party.display_name}</option>
              ))}
            </select>
            <small className="muted">{t('pages.participants.form.samePartyHint')}</small>
          </label>
        )}
        {shared && (
          <p className="muted" style={{ gridColumn: '1 / -1', margin: 0 }}>
            {t('pages.participants.form.samePartyKept', {
              name: (partiesQuery.data ?? []).find((party) => party.id === partyId)?.display_name ?? '',
            })}
          </p>
        )}
        {!isCreate && (
          <p className="muted" style={{ gridColumn: '1 / -1', margin: 0, fontSize: '0.82rem' }}>{t('pages.participants.form.sharedPartyHint')}</p>
        )}
        {!shared && (<>
        <label>
          <span>{t('pages.participants.form.kind')}</span>
          <select {...form.register('kind')}>
            <option value="person">{t('pages.participants.kind.person')}</option>
            <option value="organisation">{t('pages.participants.kind.organisation')}</option>
          </select>
        </label>
        {kind === 'organisation' && (
          <label>
            <span>{t('pages.participants.form.organisationName')}</span>
            <input {...form.register('organisation_name')} required />
          </label>
        )}
        <label>
          <span>{t('pages.participants.form.title')}</span>
          <select {...form.register('title')}>
            {titleOptions.map((option) => (
              <option key={option.value || 'none'} value={option.value}>{option.label}</option>
            ))}
          </select>
        </label>
        <label>
          <span>{t(kind === 'organisation' ? 'pages.participants.form.contactFirstName' : 'pages.participants.form.firstName')}</span>
          <input {...form.register('first_name')} required={kind === 'person'} />
        </label>
        <label>
          <span>{t(kind === 'organisation' ? 'pages.participants.form.contactLastName' : 'pages.participants.form.lastName')}</span>
          <input {...form.register('last_name')} required={kind === 'person'} />
        </label>
        <label style={{ gridColumn: '1 / -1' }}>
          <span>{t('pages.participants.form.nameAddition')}</span>
          <input {...form.register('name_addition')} />
          <small className="muted">{t('pages.participants.form.nameAdditionHint')}</small>
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
        </>)}
        <label>
          <span>{t('pages.participants.form.validFrom')}</span>
          <Controller
            control={form.control}
            name="valid_from"
            render={({ field }) => (
              <CivilDateInput
                value={field.value || null}
                onChange={(iso) => field.onChange(iso ?? '')}
                clearable={false}
              />
            )}
          />
        </label>
        <label>
          <span>{t('pages.participants.form.validTo')}</span>
          <Controller
            control={form.control}
            name="valid_to"
            render={({ field }) => (
              <CivilDateInput
                value={field.value || null}
                onChange={(iso) => field.onChange(iso ?? '')}
                inputRef={validToRef}
              />
            )}
          />
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
            {form.formState.errors.organisation_name?.message
              || form.formState.errors.first_name?.message
              || form.formState.errors.last_name?.message
              || form.formState.errors.email?.message
              || form.formState.errors.valid_from?.message
              || form.formState.errors.allocation_weight?.message
              || t('common.error')}
          </div>
        )}

        <FormModalFooter
          onCancel={onClose}
          isPending={isPending}
          submitLabel={initialParticipant ? t('pages.participants.saveParticipant') : t('common.create')}
        />
      </form>
    </FormModal>
  )
}
