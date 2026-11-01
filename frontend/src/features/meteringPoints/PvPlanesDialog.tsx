import { useState, type FormEvent } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { FormModal } from '../../components/FormModal'
import { Notice } from '../../components/Notice'
import { formatApiError } from '../../lib/api/errors'
import { queryKeys } from '../../lib/api/queryKeys'
import { createPvPlane, deletePvPlane, fetchPvPlanes, updatePvPlane } from '../../lib/api/zev'
import { azimuthLabelKey, planeFieldProblems, planeInput, type PlaneDraft, PLANE_LIMITS } from '../../lib/pvPlanes'
import { useToast } from '../../lib/toast'
import type { MeteringPoint, PvPlane } from '../../types/api'

const emptyDraft = (): PlaneDraft => ({ label: '', kwp: '', tilt: '30', azimuth: '0' })

function draftOf(plane: PvPlane): PlaneDraft {
    return { label: plane.label, kwp: plane.peak_power_kwp, tilt: String(plane.tilt_deg), azimuth: String(plane.azimuth_deg) }
}

/** What the forecast needs from a plant: its roof planes (size, tilt, direction). The building's location is set on the building. */
export function PvPlanesDialog({ point, canWrite, onClose }: { point: MeteringPoint; canWrite: boolean; onClose: () => void }) {
    const { t } = useTranslation()
    const { pushToast } = useToast()
    const queryClient = useQueryClient()
    const [editing, setEditing] = useState<string | 'new' | null>(null)
    const [draft, setDraft] = useState<PlaneDraft>(emptyDraft())
    const [error, setError] = useState<string | null>(null)
    // Messages by the field appear after the first attempt to save, not while the form is still being filled in.
    const [submitted, setSubmitted] = useState(false)

    const planes = useQuery({ queryKey: queryKeys.zev.pvPlanes(point.id), queryFn: () => fetchPvPlanes(point.id) })
    const refresh = () => {
        void queryClient.invalidateQueries({ queryKey: queryKeys.zev.pvPlanes(point.id) })
        void queryClient.invalidateQueries({ queryKey: queryKeys.live.all })
    }
    const save = useMutation({
        mutationFn: ({ id, draft: values }: { id: string | 'new'; draft: PlaneDraft }) => {
            const input = planeInput(values)
            if (!input) throw new Error('invalid')
            return id === 'new' ? createPvPlane(point.id, input) : updatePvPlane(point.id, id, input)
        },
        onSuccess: () => {
            setEditing(null)
            setError(null)
            pushToast(t('pages.meteringPoints.planes.saved'), 'success')
            refresh()
        },
        onError: (failure) => setError(formatApiError(failure, t('pages.meteringPoints.planes.saveFailed'))),
    })
    const remove = useMutation({
        mutationFn: (id: string) => deletePvPlane(point.id, id),
        onSuccess: () => {
            pushToast(t('pages.meteringPoints.planes.deleted'), 'success')
            refresh()
        },
        onError: (failure) => pushToast(formatApiError(failure, t('pages.meteringPoints.planes.saveFailed')), 'error'),
    })

    function open(id: string | 'new', values: PlaneDraft) {
        setEditing(id)
        setDraft(values)
        setSubmitted(false)
        setError(null)
    }
    function submit(event: FormEvent<HTMLFormElement>) {
        event.preventDefault()
        if (!editing) return
        setSubmitted(true)
        if (!planeInput(draft)) return
        save.mutate({ id: editing, draft })
    }
    const set = (field: keyof PlaneDraft, value: string) => setDraft((previous) => ({ ...previous, [field]: value }))
    const problems = submitted ? planeFieldProblems(draft) : {}
    const rows = planes.data ?? []
    const full = rows.length >= PLANE_LIMITS.maxPerPoint

    return (
        <FormModal isOpen size="md" title={t('pages.meteringPoints.planes.title', { meter: point.meter_id })} onClose={onClose}>
            <div className="dialog-stack">
                <p className="muted m-0">{t('pages.meteringPoints.planes.intro')}</p>
                {planes.isError && <Notice tone="error" onRetry={() => void planes.refetch()}>{t('pages.meteringPoints.planes.loadFailed')}</Notice>}
                {planes.isPending && <p className="muted m-0">{t('common.loading')}</p>}
                {planes.data && rows.length === 0 && editing !== 'new' && <p className="m-0">{t('pages.meteringPoints.planes.empty')}</p>}
                {rows.length > 0 && (
                    <ul className="dialog-list">
                        {rows.map((plane) => (
                            <li key={plane.id} className="actions-row actions-row-wrap actions-row-between">
                                <span>
                                    <strong>{plane.label || t('pages.meteringPoints.planes.unnamed')}</strong>
                                    {' · '}
                                    {t('pages.meteringPoints.planes.summary', {
                                        kwp: plane.peak_power_kwp, tilt: plane.tilt_deg, direction: t(azimuthLabelKey(plane.azimuth_deg)),
                                    })}
                                </span>
                                {canWrite && (
                                    <span className="actions-row">
                                        <button type="button" className="button button-secondary button-compact" onClick={() => open(plane.id, draftOf(plane))}>
                                            {t('common.edit')}
                                        </button>
                                        <button type="button" className="button button-danger button-compact" disabled={remove.isPending} onClick={() => remove.mutate(plane.id)}>
                                            {t('common.delete')}
                                        </button>
                                    </span>
                                )}
                            </li>
                        ))}
                    </ul>
                )}
                {canWrite && editing && (
                    <form className="form-grid form-grid-start" noValidate onSubmit={submit}>
                        <label className="grid-span-full">
                            <span>{t('pages.meteringPoints.planes.label')}</span>
                            <input value={draft.label} maxLength={100} onChange={(event) => set('label', event.target.value)} placeholder={t('pages.meteringPoints.planes.labelPlaceholder')} />
                        </label>
                        <label>
                            <span>{t('pages.meteringPoints.planes.kwp')}</span>
                            <input type="number" inputMode="decimal" min={0.01} max={PLANE_LIMITS.maxKwp} step="0.01" value={draft.kwp} onChange={(event) => set('kwp', event.target.value)} required aria-invalid={problems.kwp || undefined} />
                            {problems.kwp && <span className="field-error" role="alert">{t('pages.meteringPoints.planes.errors.kwp', { max: PLANE_LIMITS.maxKwp })}</span>}
                        </label>
                        <label>
                            <span>{t('pages.meteringPoints.planes.tilt')}</span>
                            <input type="number" inputMode="numeric" min={0} max={90} step="1" value={draft.tilt} onChange={(event) => set('tilt', event.target.value)} required aria-invalid={problems.tilt || undefined} />
                            {problems.tilt && <span className="field-error" role="alert">{t('pages.meteringPoints.planes.errors.tilt')}</span>}
                            <small className="muted">{t('pages.meteringPoints.planes.tiltHint')}</small>
                        </label>
                        <label className="grid-span-full">
                            <span>{t('pages.meteringPoints.planes.azimuth')}</span>
                            <input type="number" inputMode="numeric" min={-180} max={180} step="1" value={draft.azimuth} onChange={(event) => set('azimuth', event.target.value)} required aria-invalid={problems.azimuth || undefined} />
                            {problems.azimuth && <span className="field-error" role="alert">{t('pages.meteringPoints.planes.errors.azimuth')}</span>}
                            <small className="muted">{t('pages.meteringPoints.planes.azimuthHint')}</small>
                        </label>
                        {error && <div className="error-banner grid-span-full" role="alert">{error}</div>}
                        <div className="actions-row actions-row-wrap grid-span-full">
                            <button type="button" className="button button-secondary" onClick={() => setEditing(null)}>
                                {t('common.cancel')}
                            </button>
                            <button type="submit" className="button button-primary" disabled={save.isPending}>
                                {save.isPending ? t('common.saving') : t('common.save')}
                            </button>
                        </div>
                    </form>
                )}
                {canWrite && !editing && (
                    <div className="actions-row">
                        <button type="button" className="button button-primary" disabled={full} onClick={() => open('new', emptyDraft())}>
                            {t('pages.meteringPoints.planes.add')}
                        </button>
                        {full && <small className="muted">{t('pages.meteringPoints.planes.max', { count: PLANE_LIMITS.maxPerPoint })}</small>}
                    </div>
                )}
                <p className="muted m-0">{t('pages.meteringPoints.planes.locationHint')}</p>
            </div>
        </FormModal>
    )
}
