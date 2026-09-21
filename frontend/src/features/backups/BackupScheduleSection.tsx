import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Switch } from '@mantine/core'
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome'
import { faFloppyDisk } from '@fortawesome/free-solid-svg-icons'
import { useTranslation } from 'react-i18next'
import { fetchBackupSchedule, updateBackupSchedule } from '../../lib/api/backups'
import { formatApiError } from '../../lib/api/errors'
import { queryKeys } from '../../lib/api/queryKeys'
import { formatDateTime, useAppSettings } from '../../lib/appSettings'
import { useToast } from '../../lib/toast'
import type { BackupStatus } from '../../types/api'
import {
    WEEKDAYS,
    buildSchedulePayload,
    scheduleChanged,
    scheduleToForm,
    type ScheduleFormState,
} from './backupHelpers'

/**
 * When backups run by themselves.
 *
 * The schedule is data (beat's own periodic task), so changing it needs no
 * deploy. Two things are said out loud because nothing else would: an
 * unattended schedule that writes unencrypted archives (ADR 0024), and that
 * nothing runs unless a beat process does.
 */
export function BackupScheduleSection({ status }: { status: BackupStatus | undefined }) {
    const { t } = useTranslation()
    const { settings } = useAppSettings()
    const queryClient = useQueryClient()
    const { pushToast } = useToast()

    const scheduleQuery = useQuery({ queryKey: queryKeys.backups.schedule(), queryFn: fetchBackupSchedule })
    const saved = scheduleQuery.data

    const [form, setForm] = useState<ScheduleFormState | null>(null)
    // Adopt the saved schedule once it arrives, and again after every save.
    useEffect(() => {
        if (saved) setForm(scheduleToForm(saved))
    }, [saved])

    const save = useMutation({
        mutationFn: (payload: NonNullable<ReturnType<typeof buildSchedulePayload>>) => updateBackupSchedule(payload),
        onSuccess: (next) => {
            queryClient.setQueryData(queryKeys.backups.schedule(), next)
            void queryClient.invalidateQueries({ queryKey: queryKeys.backups.status() })
            pushToast(t('pages.backups.schedule.saved'), 'success')
        },
        onError: (error) => pushToast(formatApiError(error), 'error'),
    })

    if (!saved || !form) {
        return (
            <section className="card page-stack">
                <h3 style={{ margin: 0 }}>{t('pages.backups.schedule.title')}</h3>
                <div className="muted">{t('common.loading')}</div>
            </section>
        )
    }

    const payload = buildSchedulePayload(form)
    const canSave = !!payload && scheduleChanged(form, saved) && !save.isPending
    const update = (patch: Partial<ScheduleFormState>) => setForm({ ...form, ...patch })

    return (
        <section className="card page-stack">
            <div>
                <h3 style={{ margin: 0 }}>{t('pages.backups.schedule.title')}</h3>
                <p className="muted" style={{ margin: '0.25rem 0 0' }}>{t('pages.backups.schedule.description')}</p>
            </div>

            {form.enabled && status && !status.encrypted && (
                <div className="warning-banner">{t('pages.backups.schedule.unencrypted')}</div>
            )}
            {form.enabled && status && status.destinations_enabled === 0 && (
                <div className="warning-banner">{t('pages.backups.schedule.noDestination')}</div>
            )}

            <form
                className="page-stack"
                onSubmit={(event) => {
                    event.preventDefault()
                    if (canSave && payload) save.mutate(payload)
                }}
            >
                <Switch
                    checked={form.enabled}
                    onChange={(event) => update({ enabled: event.currentTarget.checked })}
                    label={t('pages.backups.schedule.enabled')}
                />

                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: '1rem' }}>
                    <label>
                        <span>{t('pages.backups.schedule.frequency')}</span>
                        <select
                            value={form.frequency}
                            onChange={(event) => update({ frequency: event.target.value as ScheduleFormState['frequency'] })}
                        >
                            <option value="daily">{t('pages.backups.schedule.daily')}</option>
                            <option value="weekly">{t('pages.backups.schedule.weekly')}</option>
                        </select>
                    </label>

                    {form.frequency === 'weekly' && (
                        <label>
                            <span>{t('pages.backups.schedule.weekday')}</span>
                            <select
                                value={form.day_of_week}
                                onChange={(event) => update({ day_of_week: Number(event.target.value) })}
                            >
                                {WEEKDAYS.map((day) => (
                                    <option key={day} value={day}>{t(`pages.backups.schedule.weekdays.${day}`)}</option>
                                ))}
                            </select>
                        </label>
                    )}

                    <label>
                        <span>{t('pages.backups.schedule.time', { timezone: saved.timezone })}</span>
                        <input type="time" value={form.time} onChange={(event) => update({ time: event.target.value })} required />
                    </label>
                </div>

                <p className="muted" style={{ margin: 0 }}>
                    {t('pages.backups.schedule.hint')}
                    {saved.last_run_at && <> {t('pages.backups.schedule.lastRun', { date: formatDateTime(saved.last_run_at, settings) })}</>}
                </p>

                <div className="actions-row">
                    <button type="submit" className="button button-primary" disabled={!canSave}>
                        <FontAwesomeIcon icon={faFloppyDisk} fixedWidth />
                        {t('common.save')}
                    </button>
                </div>
            </form>
        </section>
    )
}
