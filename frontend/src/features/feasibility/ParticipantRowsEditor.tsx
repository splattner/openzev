import { useFieldArray, type UseFormReturn } from 'react-hook-form'
import { useTranslation } from 'react-i18next'
import { emptyParticipantRow, type FeasibilityFormValues } from './useFeasibilityForm'

type Props = {
    form: UseFormReturn<FeasibilityFormValues>
}

export function ParticipantRowsEditor({ form }: Props) {
    const { t } = useTranslation()
    const { fields, append, remove } = useFieldArray({ control: form.control, name: 'participants' })

    return (
        <div style={{ display: 'grid', gap: '0.6rem' }}>
            {fields.map((field, index) => (
                <div
                    key={field.id}
                    style={{
                        border: '1px solid rgba(148, 163, 184, 0.35)',
                        borderRadius: '0.75rem',
                        padding: '0.6rem 0.7rem 0.7rem',
                        display: 'grid',
                        gap: '0.5rem',
                    }}
                >
                    <div style={{ display: 'grid', gridTemplateColumns: '1fr auto', gap: '0.5rem', alignItems: 'end' }}>
                        <label className="m-0">
                            <span className="muted" style={{ fontSize: '0.72rem' }}>{t('pages.feasibility.form.participantName')}</span>
                            <input
                                placeholder={t('pages.feasibility.form.participantNamePlaceholder')}
                                {...form.register(`participants.${index}.name` as const)}
                            />
                        </label>
                        <button
                            type="button"
                            className="button button-danger button-compact"
                            onClick={() => remove(index)}
                            aria-label={t('common.delete')}
                            title={t('common.delete')}
                        >
                            {t('common.delete')}
                        </button>
                    </div>
                    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.5rem' }}>
                        <label className="m-0">
                            <span className="muted" style={{ fontSize: '0.72rem' }}>{t('pages.feasibility.form.participantProduction')}</span>
                            <input type="number" step="any" min="0" {...form.register(`participants.${index}.annual_production_kwh` as const)} />
                        </label>
                        <label className="m-0">
                            <span className="muted" style={{ fontSize: '0.72rem' }}>{t('pages.feasibility.form.participantConsumption')}</span>
                            <input type="number" step="any" min="0" {...form.register(`participants.${index}.annual_consumption_kwh` as const)} />
                        </label>
                    </div>
                </div>
            ))}
            <button
                type="button"
                className="button button-secondary button-compact"
                onClick={() => append(emptyParticipantRow)}
            >
                {t('pages.feasibility.form.addParticipant')}
            </button>
        </div>
    )
}
