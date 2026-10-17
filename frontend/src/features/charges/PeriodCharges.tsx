import { faEllipsis, faLock, faPen, faPlus, faTrash } from '@fortawesome/free-solid-svg-icons'
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useEffectEvent, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { ActionMenu } from '../../components/ActionMenu'
import { ConfirmDialog, consumeReportedError, useConfirmDialog } from '../../components/ConfirmDialog'
import { DataTable, type ColumnDef } from '../../components/DataTable'
import { Notice } from '../../components/Notice'
import { createCharge, deleteCharge, fetchCharges, updateCharge } from '../../lib/api/charges'
import { formatApiError } from '../../lib/api/errors'
import { queryKeys } from '../../lib/api/queryKeys'
import { fetchParticipants } from '../../lib/api/zev'
import { formatShortDate, useAppSettings } from '../../lib/appSettings'
import { useAuth } from '../../lib/auth'
import { useCommunityAccess } from '../../lib/communityAccess'
import { formatChfAmount } from '../../lib/numbers'
import { useToast } from '../../lib/toast'
import { useWriteScope } from '../../lib/useWriteScope'
import type { Charge } from '../../types/api'
import { bearersLabel } from './chargeForm'
import { ChargeFormModal } from './ChargeFormModal'

type PeriodChargesProps = {
    zevId: string
    periodStart: string
    periodEnd: string
    /** An invoice of the period is approved or further: the charges are frozen. */
    periodLocked: boolean
}

/**
 * The one-off costs billed in one period (#924): postage, a repair. Shown under
 * the period's invoices, since that is where they end up. New charges are dated
 * within the period; once an invoice of it is approved the list is read-only.
 */
export function PeriodCharges({ zevId, periodStart, periodEnd, periodLocked }: PeriodChargesProps) {
    const { t } = useTranslation()
    const queryClient = useQueryClient()
    const { pushToast } = useToast()
    const { settings } = useAppSettings()
    const { user } = useAuth()
    const { dialog, confirm, handleConfirm, handleCancel, isLoading: dialogLoading } = useConfirmDialog()
    const cancelConfirmation = useEffectEvent(handleCancel)
    const { canWriteSelectedCommunity } = useCommunityAccess()
    const { scope, isCurrent, assertWritable } = useWriteScope(
        { selectedZevId: zevId, canWrite: canWriteSelectedCommunity, accountId: user?.id },
        t('common.error'),
    )
    const canEdit = canWriteSelectedCommunity && !periodLocked
    const [formOpen, setFormOpen] = useState(false)
    const [editing, setEditing] = useState<Charge | null>(null)

    const chargesQuery = useQuery({
        queryKey: queryKeys.charges.list(zevId, periodStart, periodEnd),
        queryFn: () => fetchCharges(zevId, { period_start: periodStart, period_end: periodEnd }),
    })
    const participantsQuery = useQuery({
        queryKey: queryKeys.zev.participants(zevId),
        queryFn: fetchParticipants,
    })
    const participants = useMemo(
        () => (participantsQuery.data ?? []).filter((participant) => participant.zev === zevId),
        [participantsQuery.data, zevId],
    )
    const participantNames = useMemo(
        () => new Map(participants.map((participant) => [participant.id, participant.display_name || participant.full_name || ''])),
        [participants],
    )

    // A dialog belongs to one period of one community: never let it survive a change.
    useEffect(() => {
        setFormOpen(false)
        setEditing(null)
        cancelConfirmation()
    }, [zevId, user?.id, canEdit, periodStart, periodEnd])

    const invalidate = () => {
        void queryClient.invalidateQueries({ queryKey: queryKeys.charges.lists() })
        // A charge changes what the period's readiness reports (stale drafts).
        void queryClient.invalidateQueries({ queryKey: ['invoices'] })
    }

    const saveMutation = useMutation({
        mutationFn: ({ payload, id, scope: submittingScope }: {
            payload: Parameters<typeof createCharge>[0]
            id: string | null
            scope: typeof scope
        }) => {
            assertWritable(submittingScope)
            return id ? updateCharge(id, payload) : createCharge(payload)
        },
        onSuccess: (_, variables) => {
            invalidate()
            if (!isCurrent(variables.scope)) return
            setFormOpen(false)
            setEditing(null)
            pushToast(t(variables.id ? 'pages.charges.messages.updated' : 'pages.charges.messages.created'), 'success')
        },
        onError: (error, variables) => {
            if (isCurrent(variables.scope)) {
                pushToast(formatApiError(error, t(variables.id ? 'pages.charges.messages.updateFailed' : 'pages.charges.messages.createFailed')), 'error')
            }
        },
    })

    const deleteMutation = useMutation({
        mutationFn: ({ charge, scope: submittingScope }: { charge: Charge; scope: typeof scope }) => {
            assertWritable(submittingScope)
            return deleteCharge(charge.id)
        },
        onSuccess: (_, variables) => {
            invalidate()
            if (isCurrent(variables.scope)) pushToast(t('pages.charges.messages.deleted'), 'success')
        },
        onError: (error, variables) => {
            if (isCurrent(variables.scope)) pushToast(formatApiError(error, t('pages.charges.messages.deleteFailed')), 'error')
        },
    })

    const openCreate = () => {
        setEditing(null)
        setFormOpen(true)
    }
    const openEdit = (charge: Charge) => {
        setEditing(charge)
        setFormOpen(true)
    }
    const confirmDelete = (charge: Charge) =>
        confirm({
            title: t('pages.charges.deleteTitle'),
            message: t('pages.charges.deleteMessage', { description: charge.description }),
            confirmText: t('common.delete'),
            isDangerous: true,
            onConfirm: () => consumeReportedError(deleteMutation.mutateAsync({ charge, scope })),
        })

    const columns = useMemo<ColumnDef<Charge, unknown>[]>(() => [
        {
            id: 'charge_date',
            accessorKey: 'charge_date',
            header: t('pages.charges.columns.date'),
            cell: ({ row }) => formatShortDate(row.original.charge_date, settings),
        },
        {
            id: 'description',
            accessorKey: 'description',
            header: t('pages.charges.columns.description'),
            cell: ({ row }) => row.original.description,
        },
        {
            id: 'amount_chf',
            accessorFn: (charge) => Number(charge.amount_chf),
            header: t('pages.charges.columns.amount'),
            meta: { numeric: true },
            cell: ({ row }) => formatChfAmount(Number(row.original.amount_chf)),
        },
        {
            id: 'bearers',
            header: t('pages.charges.columns.bearers'),
            enableSorting: false,
            cell: ({ row }) => bearersLabel(row.original, participantNames, t),
        },
        {
            id: 'vat_treatment',
            accessorKey: 'vat_treatment',
            header: t('pages.charges.columns.vat'),
            cell: ({ row }) => t(`pages.charges.vatTreatment.${row.original.vat_treatment}`),
        },
        {
            id: 'actions',
            header: () => <span className="visually-hidden">{t('common.actions')}</span>,
            enableSorting: false,
            meta: { numeric: true },
            cell: ({ row }) => {
                const charge = row.original
                if (!canEdit || charge.is_locked) return null
                return (
                    <ActionMenu
                        label={t('common.actions')}
                        iconOnly
                        icon={<FontAwesomeIcon icon={faEllipsis} fixedWidth />}
                        items={[
                            {
                                key: 'edit',
                                label: t('common.edit'),
                                icon: <FontAwesomeIcon icon={faPen} fixedWidth />,
                                onClick: () => openEdit(charge),
                            },
                            {
                                key: 'delete',
                                label: t('common.delete'),
                                icon: <FontAwesomeIcon icon={faTrash} fixedWidth />,
                                onClick: () => confirmDelete(charge),
                                danger: true,
                            },
                        ]}
                    />
                )
            },
        },
        // eslint-disable-next-line react-hooks/exhaustive-deps
    ], [t, settings, participantNames, canEdit, scope])

    const charges = chargesQuery.data ?? []

    return (
        <section className="period-charges" aria-labelledby="period-charges-title">
            <div className="period-charges-header">
                <div>
                    <h3 id="period-charges-title" className="m-0">{t('pages.charges.title')}</h3>
                    <p className="muted m-0">{t('pages.charges.description')}</p>
                </div>
                {canWriteSelectedCommunity && !periodLocked ? (
                    <button type="button" className="button button-secondary" onClick={openCreate}>
                        <FontAwesomeIcon icon={faPlus} fixedWidth />
                        {t('pages.charges.create')}
                    </button>
                ) : null}
            </div>

            {periodLocked ? (
                <p className="muted m-0">
                    <FontAwesomeIcon icon={faLock} fixedWidth /> {t('pages.charges.periodLocked')}
                </p>
            ) : null}

            {chargesQuery.isError ? (
                <Notice tone="error" onRetry={() => void chargesQuery.refetch()} isRetrying={chargesQuery.isFetching}>
                    {t('common.error')}
                </Notice>
            ) : chargesQuery.isLoading ? (
                <p className="muted">{t('common.loading')}</p>
            ) : charges.length === 0 ? (
                <p className="muted">{t('pages.charges.emptyPeriod')}</p>
            ) : (
                <div className="table-card">
                    <DataTable
                        data={charges}
                        columns={columns}
                        getRowId={(charge) => charge.id}
                        initialSorting={[{ id: 'charge_date', desc: false }]}
                    />
                </div>
            )}

            <ChargeFormModal
                isOpen={formOpen}
                isPending={saveMutation.isPending}
                zevId={zevId}
                charge={editing}
                participants={participants}
                minDate={periodStart}
                maxDate={periodEnd}
                onClose={() => { setFormOpen(false); setEditing(null) }}
                onSubmit={(payload) => saveMutation.mutate({ payload, id: editing?.id ?? null, scope })}
            />

            {dialog && (
                <ConfirmDialog {...dialog} isLoading={dialogLoading} onConfirm={handleConfirm} onCancel={handleCancel} />
            )}
        </section>
    )
}
