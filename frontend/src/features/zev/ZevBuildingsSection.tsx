import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome'
import { faPen, faPlus, faTrash } from '@fortawesome/free-solid-svg-icons'
import { ConfirmDialog, useConfirmDialog } from '../../components/ConfirmDialog'
import { createBuilding, deleteBuilding, fetchBuildings, fetchPartyRoles, updateBuilding } from '../../lib/api/zev'
import { formatApiError } from '../../lib/api/errors'
import { queryKeys } from '../../lib/api/queryKeys'
import { todayBusinessIso } from '../../lib/dates'
import { useToast } from '../../lib/toast'
import type { Building, BuildingInput } from '../../types/api'
import { BuildingFormModal } from './BuildingFormModal'

interface Props {
    zevId: string
    /** Add, change and delete buildings. A viewer (or a disabled ZEV) only reads. */
    canManage: boolean
}

/**
 * ZEV settings → Buildings (#890, SPEC-2026-10-buildings-and-sites §7.3):
 * where the community's metering points are. A building is a site, not a
 * billing address: a participant can be billed elsewhere than where its meters
 * are.
 */
export function ZevBuildingsSection({ zevId, canManage }: Props) {
    const { t } = useTranslation()
    const { pushToast } = useToast()
    const queryClient = useQueryClient()
    const { dialog, confirm, handleConfirm, handleCancel, isLoading: dialogLoading } = useConfirmDialog()
    const [editing, setEditing] = useState<Building | null>(null)
    const [modalOpen, setModalOpen] = useState(false)

    const buildingsQuery = useQuery({
        queryKey: queryKeys.zev.buildings(zevId),
        queryFn: () => fetchBuildings(zevId),
        enabled: Boolean(zevId),
    })
    // Which landowners own which building (their role row names it).
    const rolesQuery = useQuery({
        queryKey: queryKeys.zev.partyRoles(zevId, true),
        queryFn: () => fetchPartyRoles(zevId, { includeEnded: true }),
        enabled: Boolean(zevId),
    })

    function afterChange() {
        void queryClient.invalidateQueries({ queryKey: queryKeys.zev.buildings(zevId) })
        void queryClient.invalidateQueries({ queryKey: ['zev', 'partyRoles', zevId] })
        void queryClient.invalidateQueries({ queryKey: ['metering', 'points'] })
    }

    const save = useMutation({
        mutationFn: (input: BuildingInput) => (editing ? updateBuilding(editing.id, input) : createBuilding({ ...input, zev: zevId })),
        onSuccess: () => {
            setModalOpen(false)
            setEditing(null)
            afterChange()
            pushToast(t('pages.zevSettings.buildings.saved'), 'success')
        },
        onError: (error) => pushToast(formatApiError(error, t('pages.zevSettings.buildings.saveFailed')), 'error'),
    })

    const remove = useMutation({
        mutationFn: (building: Building) => deleteBuilding(building.id),
        onSuccess: () => {
            afterChange()
            pushToast(t('pages.zevSettings.buildings.deleted'), 'success')
        },
        onError: (error) => pushToast(formatApiError(error, t('pages.zevSettings.buildings.saveFailed')), 'error'),
    })

    function confirmDelete(building: Building) {
        confirm({
            title: t('pages.zevSettings.buildings.deleteTitle'),
            message: t('pages.zevSettings.buildings.deleteMessage', { name: building.name }),
            confirmText: t('common.delete'),
            isDangerous: true,
            onConfirm: () => remove.mutateAsync(building).then(() => undefined),
        })
    }

    const buildings = buildingsQuery.data ?? []
    const today = todayBusinessIso()
    const landownersOf = (building: Building) => [
        ...new Set(
            (rolesQuery.data ?? [])
                .filter((row) => row.role === 'landowner' && row.building === building.id && (row.valid_to === null || row.valid_to >= today))
                .map((row) => row.party_display_name),
        ),
    ]

    return (
        <section className="card page-stack">
            <div className="zev-parties-block-header">
                <div>
                    <h3 style={{ marginTop: 0 }}>{t('pages.zevSettings.buildings.title')}</h3>
                    <p className="muted" style={{ margin: 0 }}>{t('pages.zevSettings.buildings.description')}</p>
                </div>
                {canManage && (
                    <button
                        type="button"
                        className="button button-primary button-compact"
                        onClick={() => { setEditing(null); setModalOpen(true) }}
                    >
                        <FontAwesomeIcon icon={faPlus} fixedWidth />
                        {t('pages.zevSettings.buildings.add')}
                    </button>
                )}
            </div>

            {buildingsQuery.isLoading && <p className="muted">{t('common.loading')}</p>}
            {buildingsQuery.isError && <p className="error-banner">{t('common.error')}</p>}
            {buildingsQuery.isSuccess && buildings.length === 0 && <p className="muted">{t('pages.zevSettings.buildings.none')}</p>}
            {buildingsQuery.isSuccess && buildings.length > 0 && (
                <ul className="zev-access-list">
                    {buildings.map((building) => {
                        const landowners = landownersOf(building)
                        const address = [building.address_line1, building.address_line2, [building.postal_code, building.city].filter(Boolean).join(' ')]
                            .filter(Boolean)
                            .join(', ')
                        return (
                            <li key={building.id} className="zev-access-row">
                                <div className="zev-access-who">
                                    <strong>{building.name}</strong>
                                    <span className="zev-access-badges">
                                        <span className="badge badge-neutral">
                                            {t('pages.zevSettings.buildings.meteringPoints', { count: building.metering_point_count })}
                                        </span>
                                        {building.egid !== null && (
                                            <span className="badge badge-info">{t('pages.zevSettings.buildings.egidBadge', { egid: building.egid })}</span>
                                        )}
                                    </span>
                                </div>
                                <div className="zev-access-meta muted">
                                    {address && <span>{address}</span>}
                                    {landowners.length > 0 && (
                                        <span>{t('pages.zevSettings.buildings.landowners', { names: landowners.join(', ') })}</span>
                                    )}
                                    {building.notes && <span>{building.notes}</span>}
                                </div>
                                {canManage && (
                                    <div className="zev-access-actions actions-row actions-row-wrap">
                                        <button
                                            type="button"
                                            className="button button-secondary button-compact"
                                            onClick={() => { setEditing(building); setModalOpen(true) }}
                                        >
                                            <FontAwesomeIcon icon={faPen} fixedWidth />
                                            {t('common.edit')}
                                        </button>
                                        <button
                                            type="button"
                                            className="button button-danger button-compact"
                                            disabled={remove.isPending || building.metering_point_count > 0}
                                            title={building.metering_point_count > 0 ? t('pages.zevSettings.buildings.deleteBlocked') : undefined}
                                            onClick={() => confirmDelete(building)}
                                        >
                                            <FontAwesomeIcon icon={faTrash} fixedWidth />
                                            {t('common.delete')}
                                        </button>
                                    </div>
                                )}
                            </li>
                        )
                    })}
                </ul>
            )}

            <BuildingFormModal
                isOpen={modalOpen}
                zevId={zevId}
                building={editing}
                isPending={save.isPending}
                onClose={() => { setModalOpen(false); setEditing(null) }}
                onSubmit={(input) => save.mutate(input)}
            />
            {dialog && (
                <ConfirmDialog {...dialog} isLoading={dialogLoading} onConfirm={handleConfirm} onCancel={handleCancel} />
            )}
        </section>
    )
}
