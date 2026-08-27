import { Switch } from '@mantine/core'
import { type Dispatch, type FormEvent, type SetStateAction } from 'react'
import { useTranslation } from 'react-i18next'
import { FormModal } from '../../components/FormModal'
import { METER_TYPE_OPTIONS } from '../../lib/options'
import type { MeteringPointInput } from '../../types/api'

type MeteringPointFormModalProps = {
  isOpen: boolean
  title: string
  submitLabel: string
  form: MeteringPointInput
  isPending: boolean
  onClose: () => void
  onSubmit: (event: FormEvent<HTMLFormElement>) => void
  setForm: Dispatch<SetStateAction<MeteringPointInput>>
}

export function MeteringPointFormModal({
  isOpen,
  title,
  submitLabel,
  form,
  isPending,
  onClose,
  onSubmit,
  setForm,
}: MeteringPointFormModalProps) {
  const { t } = useTranslation()

  return (
    <FormModal isOpen={isOpen} title={title} onClose={onClose}>
      <form onSubmit={onSubmit} className="form-grid">
        <label>
          <span>{t('pages.meteringPoints.form.meterId')}</span>
          <input
            value={form.meter_id}
            onChange={(event) => setForm((previous) => ({ ...previous, meter_id: event.target.value }))}
            required
          />
        </label>

        <label>
          <span>{t('pages.meteringPoints.form.meterType')}</span>
          <select
            value={form.meter_type}
            onChange={(event) =>
              setForm((previous) => ({ ...previous, meter_type: event.target.value as MeteringPointInput['meter_type'] }))
            }
          >
            {METER_TYPE_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>
                {t(option.labelKey)}
              </option>
            ))}
          </select>
        </label>

        <div style={{ gridColumn: '1 / -1' }}>
          <Switch
            checked={form.is_active}
            onChange={(event) => setForm((previous) => ({ ...previous, is_active: event.currentTarget.checked }))}
            label={t('pages.meteringPoints.form.active')}
          />
        </div>

        <label style={{ gridColumn: '1 / -1' }}>
          <span>{t('pages.meteringPoints.form.location')}</span>
          <input
            value={form.location_description ?? ''}
            onChange={(event) => setForm((previous) => ({ ...previous, location_description: event.target.value }))}
          />
        </label>

        <div
          style={{
            gridColumn: '1 / -1',
            display: 'flex',
            gap: '1rem',
            justifyContent: 'flex-end',
            marginTop: '1rem',
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
