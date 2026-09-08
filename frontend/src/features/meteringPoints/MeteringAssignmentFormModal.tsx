import { type Dispatch, type FormEvent, type SetStateAction } from 'react'
import { useTranslation } from 'react-i18next'
import { FormModal } from '../../components/FormModal'
import { FormModalFooter } from '../../components/FormModalFooter'
import { CivilDateInput } from '../../components/CivilDateInput'
import type { MeteringPointAssignmentInput, Participant } from '../../types/api'

type MeteringAssignmentFormModalProps = {
  isOpen: boolean
  title: string
  form: MeteringPointAssignmentInput
  participants: Participant[]
  isPending: boolean
  /** The meter already has an assignment with no end date, which would overlap any new one — the user needs to close it first. */
  hasOpenEndedWarning?: boolean
  onClose: () => void
  onSubmit: (event: FormEvent<HTMLFormElement>) => void
  setForm: Dispatch<SetStateAction<MeteringPointAssignmentInput>>
  submitLabel: string
}

export function MeteringAssignmentFormModal({
  isOpen,
  title,
  form,
  participants,
  isPending,
  hasOpenEndedWarning,
  onClose,
  onSubmit,
  setForm,
  submitLabel,
}: MeteringAssignmentFormModalProps) {
  const { t } = useTranslation()

  return (
    <FormModal isOpen={isOpen} title={title} onClose={onClose}>
      <form onSubmit={onSubmit} className="form-grid">
        {hasOpenEndedWarning && (
          <div className="warning-banner" role="alert" style={{ gridColumn: '1 / -1' }}>
            {t('pages.meteringPoints.assignForm.openEndedWarning')}
          </div>
        )}

        <label style={{ gridColumn: '1 / -1' }}>
          <span>{t('pages.meteringPoints.assignForm.participant')}</span>
          <select
            value={form.participant}
            onChange={(event) => {
              const value = event.target.value
              setForm((previous) => ({ ...previous, participant: value }))
            }}
            required
          >
            <option value="">{t('pages.meteringPoints.assignForm.selectParticipant')}</option>
            {participants.map((participant) => (
              <option key={participant.id} value={participant.id}>
                {participant.first_name} {participant.last_name}
              </option>
            ))}
          </select>
        </label>

        <label>
          <span>{t('pages.meteringPoints.assignForm.validFrom')}</span>
          <CivilDateInput
            value={form.valid_from || null}
            onChange={(iso) => setForm((previous) => ({ ...previous, valid_from: iso ?? '' }))}
          />
        </label>
        <label>
          <span>{t('pages.meteringPoints.assignForm.validTo')}</span>
          <CivilDateInput
            value={form.valid_to || null}
            onChange={(iso) => setForm((previous) => ({ ...previous, valid_to: iso }))}
          />
        </label>

        <p className="muted" style={{ gridColumn: '1 / -1', margin: 0, fontSize: '0.82rem' }}>
          {t('pages.meteringPoints.assignForm.validToHint')}
        </p>

        <label style={{ gridColumn: '1 / -1' }}>
          <span>{t('pages.meteringPoints.assignForm.allocationMode')}</span>
          <select
            value={form.allocation_mode}
            onChange={(event) => {
              const value = event.target.value as MeteringPointAssignmentInput['allocation_mode']
              setForm((previous) => ({
                ...previous,
                allocation_mode: value,
              }))
            }}
          >
            <option value="personal">{t('pages.meteringPoints.assignForm.allocationModePersonal')}</option>
            <option value="community">{t('pages.meteringPoints.assignForm.allocationModeCommunity')}</option>
          </select>
        </label>
        <p className="muted" style={{ gridColumn: '1 / -1', margin: 0, fontSize: '0.82rem' }}>
          {t('pages.meteringPoints.assignForm.allocationModeHint')}
        </p>

        <FormModalFooter
          onCancel={onClose}
          isPending={isPending}
          submitLabel={submitLabel}
          compact
        />
      </form>
    </FormModal>
  )
}
