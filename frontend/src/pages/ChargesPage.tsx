import { faEllipsis, faLock, faPen, faPlus, faTrash } from '@fortawesome/free-solid-svg-icons'
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useEffectEvent, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { ActionMenu } from '../components/ActionMenu'
import { ConfirmDialog, consumeReportedError, useConfirmDialog } from '../components/ConfirmDialog'
import { DataTable, type ColumnDef } from '../components/DataTable'
import { EmptyState } from '../components/EmptyState'
import { Notice } from '../components/Notice'
import { PageHeader } from '../components/PageHeader'
import { PageSkeleton } from '../components/PageSkeleton'
import { ScopeGuard } from '../components/ScopeGuard'
import { bearersLabel } from '../features/charges/chargeForm'
import { ChargeFormModal } from '../features/charges/ChargeFormModal'
import { createCharge, deleteCharge, fetchCharges, updateCharge } from '../lib/api/charges'
import { formatApiError } from '../lib/api/errors'
import { queryKeys } from '../lib/api/queryKeys'
import { fetchParticipants } from '../lib/api/zev'
import { formatShortDate, useAppSettings } from '../lib/appSettings'
import { useAuth } from '../lib/auth'
import { useCommunityAccess, useScopeNote } from '../lib/communityAccess'
import { useManagedZev } from '../lib/managedZev'
import { formatChfAmount } from '../lib/numbers'
import { useToast } from '../lib/toast'
import { useWriteScope } from '../lib/useWriteScope'
import type { Charge } from '../types/api'

/**
 * One-off costs passed on to participants (#924): postage, a repair. Each is
 * recorded once and billed on the invoice whose period contains its date; it
 * is locked once such an invoice has been issued.
 */
export function ChargesPage() {
    const { t } = useTranslation()
    const queryClient = useQueryClient()
    const { pushToast } = useToast()
    const { settings } = useAppSettings()
    const { user } = useAuth()
    const { dialog, confirm, handleConfirm, handleCancel, isLoading: dialogLoading } = useConfirmDialog()
    const cancelConfirmation = useEffectEvent(handleCancel)
    const { selectedZevId, selectedZev } = useManagedZev()
    const scopeNote = useScopeNote()
    const { canWriteSelectedCommunity } = useCommunityAccess()
    const { scope, isCurrent, assertWritable } = useWriteScope(
        { selectedZevId, canWrite: canWriteSelectedCommunity, accountId: user?.id },
        t('common.error'),
    )
    const readOnly = !canWriteSelectedCommunity
    const [formOpen, setFormOpen] = useState(false)
    const [editing, setEditing] = useState<Charge | null>(null)

    const enabled = !!selectedZevId && selectedZev?.id === selectedZevId
    const chargesQuery = useQuery({
        queryKey: queryKeys.charges.list(selectedZevId || undefined),
        queryFn: () => fetchCharges(selectedZevId || undefined),
        enabled,
    })
    const participantsQuery = useQuery({
        queryKey: queryKeys.zev.participants(selectedZevId || undefined),
        queryFn: fetchParticipants,
        enabled,
    })
    const participants = useMemo(
        () => (participantsQuery.data ?? []).filter((participant) => participant.zev === selectedZevId),
        [participantsQuery.data, selectedZevId],
    )
    const participantNames = useMemo(
        () => new Map(participants.map((participant) => [participant.id, participant.display_name || participant.full_name || ''])),
        [participants],
    )

    useEffect(() => {
        setFormOpen(false)
        setEditing(null)
        cancelConfirmation()
    }, [selectedZevId, user?.id, readOnly])

    const invalidate = (zevId: string | null) => {
        void queryClient.invalidateQueries({ queryKey: queryKeys.charges.list(zevId || undefined) })
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
            invalidate(variables.scope.selectedZevId ?? null)
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
            invalidate(variables.scope.selectedZevId ?? null)
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
            cell: ({ row }) => (
                <>
                    {row.original.description}
                    {row.original.is_locked ? (
                        <span className="badge badge-info" title={t('pages.charges.lockedHint')}>
                            <FontAwesomeIcon icon={faLock} fixedWidth /> {t('pages.charges.locked')}
                        </span>
                    ) : null}
                </>
            ),
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
                if (readOnly) return null
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
                                disabled: charge.is_locked,
                            },
                            {
                                key: 'delete',
                                label: t('common.delete'),
                                icon: <FontAwesomeIcon icon={faTrash} fixedWidth />,
                                onClick: () => confirmDelete(charge),
                                disabled: charge.is_locked,
                                danger: true,
                            },
                        ]}
                    />
                )
            },
        },
        // eslint-disable-next-line react-hooks/exhaustive-deps
    ], [t, settings, participantNames, readOnly, scope])

    const charges = chargesQuery.data ?? []

    return (
        <div className="page-stack">
            <PageHeader
                eyebrow={selectedZev?.name}
                communitySwitch
                scopeNote={scopeNote}
                title={t('pages.charges.title')}
                description={t('pages.charges.description')}
                actions={!readOnly ? (
                    <button type="button" className="button button-primary" onClick={openCreate}>
                        <FontAwesomeIcon icon={faPlus} fixedWidth />
                        {t('pages.charges.create')}
                    </button>
                ) : undefined}
            />
            <ScopeGuard skeleton="table">
                {chargesQuery.isLoading ? <PageSkeleton variant="table" /> : chargesQuery.isError ? (
                    <Notice tone="error" onRetry={() => void chargesQuery.refetch()} isRetrying={chargesQuery.isFetching}>
                        {t('common.error')}
                    </Notice>
                ) : charges.length === 0 ? (
                    <EmptyState
                        titleKey="pages.charges.emptyState.title"
                        descriptionKey="pages.charges.emptyState.description"
                        actions={!readOnly ? [{ labelKey: 'pages.charges.create', onClick: openCreate, variant: 'primary', icon: faPlus }] : []}
                    />
                ) : (
                    <div className="table-card">
                        <DataTable
                            data={charges}
                            columns={columns}
                            getRowId={(charge) => charge.id}
                            initialSorting={[{ id: 'charge_date', desc: true }]}
                        />
                    </div>
                )}
            </ScopeGuard>

            {selectedZevId ? (
                <ChargeFormModal
                    isOpen={formOpen}
                    isPending={saveMutation.isPending}
                    zevId={selectedZevId}
                    charge={editing}
                    participants={participants}
                    onClose={() => { setFormOpen(false); setEditing(null) }}
                    onSubmit={(payload) => saveMutation.mutate({ payload, id: editing?.id ?? null, scope })}
                />
            ) : null}

            {dialog && (
                <ConfirmDialog {...dialog} isLoading={dialogLoading} onConfirm={handleConfirm} onCancel={handleCancel} />
            )}
        </div>
    )
}
