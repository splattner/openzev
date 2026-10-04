import { Switch } from '@mantine/core'
import { type Dispatch, type FormEvent, type SetStateAction } from 'react'
import { useTranslation } from 'react-i18next'
import { FormModal } from '../../components/FormModal'
import { FormModalFooter } from '../../components/FormModalFooter'
import { METER_TYPE_OPTIONS } from '../../lib/options'
import type { Building, MeteringPointInput } from '../../types/api'

type MeteringPointFormModalProps = {
  isOpen: boolean
  title: string
  submitLabel: string
  form: MeteringPointInput
  isPending: boolean
  onClose: () => void
  onSubmit: (event: FormEvent<HTMLFormElement>) => void
  setForm: Dispatch<SetStateAction<MeteringPointInput>>
  /** The ZEV's buildings; the select shows only when there is more than one (#890). */
  buildings?: Building[]
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
  buildings = [],
}: MeteringPointFormModalProps) {
  const { t } = useTranslation()

  return (
    <FormModal isOpen={isOpen} title={title} onClose={onClose}>
      <form onSubmit={onSubmit} className="form-grid">
        <label>
          <span>{t('pages.meteringPoints.form.meterId')}</span>
          <input
            value={form.meter_id}
            onChange={(event) => {
              const value = event.target.value
              setForm((previous) => ({ ...previous, meter_id: value }))
            }}
            required
          />
        </label>

        <label>
          <span>{t('pages.meteringPoints.form.meterType')}</span>
          <select
            value={form.meter_type}
            onChange={(event) => {
              const value = event.target.value as MeteringPointInput['meter_type']
              setForm((previous) => ({
                ...previous,
                meter_type: value,
                // A consumption-only meter cannot have surplus behind it.
                has_behind_meter_generation: value === 'consumption' ? false : previous.has_behind_meter_generation,
              }))
            }}
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
            onChange={(event) => {
              const checked = event.currentTarget.checked
              setForm((previous) => ({ ...previous, is_active: checked }))
            }}
            label={t('pages.meteringPoints.form.active')}
            description={t('pages.meteringPoints.form.activeHint')}
          />
        </div>

        {(form.meter_type === 'bidirectional' || form.meter_type === 'production') && (
          <div style={{ gridColumn: '1 / -1' }}>
            <Switch
              checked={form.has_behind_meter_generation ?? false}
              onChange={(event) => {
                const checked = event.currentTarget.checked
                setForm((previous) => ({ ...previous, has_behind_meter_generation: checked }))
              }}
              label={t('pages.meteringPoints.form.behindMeterGeneration')}
              description={t('pages.meteringPoints.form.behindMeterGenerationHelp')}
            />
          </div>
        )}

        {buildings.length > 1 && (
          <label style={{ gridColumn: '1 / -1' }}>
            <span>{t('pages.meteringPoints.form.building')}</span>
            <select
              value={form.building ?? ''}
              onChange={(event) => {
                const value = event.target.value
                setForm((previous) => ({ ...previous, building: value || undefined }))
              }}
              required
            >
              <option value="">{t('pages.meteringPoints.form.buildingPlaceholder')}</option>
              {buildings.map((building) => (
                <option key={building.id} value={building.id}>{building.name}</option>
              ))}
            </select>
          </label>
        )}

        <label style={{ gridColumn: '1 / -1' }}>
          <span>{t('pages.meteringPoints.form.location')}</span>
          <input
            value={form.location_description ?? ''}
            onChange={(event) => {
              const value = event.target.value
              setForm((previous) => ({ ...previous, location_description: value }))
            }}
          />
        </label>

        <FormModalFooter
          onCancel={onClose}
          isPending={isPending}
          submitLabel={submitLabel}
        />
      </form>
    </FormModal>
  )
}
