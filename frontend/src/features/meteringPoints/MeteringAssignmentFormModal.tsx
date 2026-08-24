import dayjs from 'dayjs'
import { DatePicker } from '@mui/x-date-pickers/DatePicker'
import { type Dispatch, type FormEvent, type SetStateAction } from 'react'
import { useTranslation } from 'react-i18next'
import { FormModal } from '../../components/FormModal'
import { toDayJsDateFormat } from '../../lib/appSettings'
import type { AppSettings, MeteringPointAssignmentInput, Participant } from '../../types/api'

type MeteringAssignmentFormModalProps = {
  isOpen: boolean
  title: string
  form: MeteringPointAssignmentInput
  participants: Participant[]
  settings: AppSettings
  isPending: boolean
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
  settings,
  isPending,
  onClose,
  onSubmit,
  setForm,
  submitLabel,
}: MeteringAssignmentFormModalProps) {
  const { t } = useTranslation()

  return (
    <FormModal isOpen={isOpen} title={title} onClose={onClose}>
      <form onSubmit={onSubmit} className="form-grid">
        <label style={{ gridColumn: '1 / -1' }}>
          <span>{t('pages.meteringPoints.assignForm.participant')}</span>
          <select
            value={form.participant}
            onChange={(event) => setForm((previous) => ({ ...previous, participant: event.target.value }))}
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
          <DatePicker
            format={toDayJsDateFormat(settings.date_format_short)}
            value={form.valid_from ? dayjs(form.valid_from) : null}
            onChange={(value) => setForm((previous) => ({ ...previous, valid_from: value ? value.format('YYYY-MM-DD') : '' }))}
            slotProps={{ textField: { required: true, size: 'small' } }}
          />
        </label>
        <label>
          <span>{t('pages.meteringPoints.assignForm.validTo')}</span>
          <DatePicker
            format={toDayJsDateFormat(settings.date_format_short)}
            value={form.valid_to ? dayjs(form.valid_to) : null}
            onChange={(value) => setForm((previous) => ({ ...previous, valid_to: value ? value.format('YYYY-MM-DD') : null }))}
            slotProps={{ textField: { size: 'small' } }}
          />
        </label>

        <p className="muted" style={{ gridColumn: '1 / -1', margin: 0, fontSize: '0.82rem' }}>
          {t('pages.meteringPoints.assignForm.validToHint')}
        </p>

        <label style={{ gridColumn: '1 / -1' }}>
          <span>{t('pages.meteringPoints.assignForm.allocationMode')}</span>
          <select
            value={form.allocation_mode}
            onChange={(event) =>
              setForm((previous) => ({
                ...previous,
                allocation_mode: event.target.value as MeteringPointAssignmentInput['allocation_mode'],
              }))
            }
          >
            <option value="personal">{t('pages.meteringPoints.assignForm.allocationModePersonal')}</option>
            <option value="community">{t('pages.meteringPoints.assignForm.allocationModeCommunity')}</option>
          </select>
        </label>
        <p className="muted" style={{ gridColumn: '1 / -1', margin: 0, fontSize: '0.82rem' }}>
          {t('pages.meteringPoints.assignForm.allocationModeHint')}
        </p>

        <div
          style={{
            gridColumn: '1 / -1',
            display: 'flex',
            gap: '1rem',
            justifyContent: 'flex-end',
            marginTop: '0.5rem',
          }}
        >
          <button className="button button-secondary" type="button" onClick={onClose}>
            {t('common.cancel')}
          </button>
          <button className="button button-primary" type="submit" disabled={isPending}>
            {submitLabel}
          </button>
        </div>
      </form>
    </FormModal>
  )
}
