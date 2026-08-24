import { useTranslation } from 'react-i18next'
import { ConfirmDialog } from '../components/ConfirmDialog'
import { MeteringAssignmentFormModal } from '../features/meteringPoints/MeteringAssignmentFormModal'
import { MeteringDeleteDataModal } from '../features/meteringPoints/MeteringDeleteDataModal'
import { MeteringPointsEmptyState } from '../features/meteringPoints/MeteringPointsEmptyState'
import { MeteringPointsList } from '../features/meteringPoints/MeteringPointsList'
import { MeteringPointFormModal } from '../features/meteringPoints/MeteringPointFormModal'
import { MeteringPointsToolbar } from '../features/meteringPoints/MeteringPointsToolbar'
import { useMeteringPointActions } from '../features/meteringPoints/useMeteringPointActions'
import { useAppSettings } from '../lib/appSettings'
import { useAuth } from '../lib/auth'
import { useManagedZev } from '../lib/managedZev'

// ── Component ─────────────────────────────────────────────────────────────────

export function MeteringPointsPage() {
    const { user } = useAuth()
    const { selectedZevId } = useManagedZev()
    const { settings } = useAppSettings()
    const { t } = useTranslation()
    const canManageMeteringPoints = user?.role === 'admin' || user?.role === 'zev_owner'

    const {
        meteringPointsQuery,
        saveMpMutation,
        deleteMpMutation,
        saveAssignMutation,
        deleteAssignMutation,
        deleteMeteringDataMutation,
        mpForm,
        setMpForm,
        editingMpId,
        showMpModal,
        assignForm,
        setAssignForm,
        editingAssignId,
        showAssignModal,
        showDeleteDataModal,
        deleteDataTarget,
        deleteDataMode,
        setDeleteDataMode,
        deleteDataFrom,
        setDeleteDataFrom,
        deleteDataTo,
        setDeleteDataTo,
        searchTerm,
        setSearchTerm,
        statusFilter,
        setStatusFilter,
        typeFilter,
        setTypeFilter,
        openCreateMpModal,
        openEditMpModal,
        closeMpModal,
        submitMpForm,
        openCreateAssignModal,
        openEditAssignModal,
        closeAssignModal,
        submitAssignForm,
        openDeleteDataModal,
        closeDeleteDataModal,
        submitDeleteData,
        participantNameById,
        assignParticipants,
        filteredAssignmentsByMeteringPoint,
        meteringPoints,
        scopedMeteringPoints,
        activeCount,
        inactiveCount,
        assignedCount,
        hasFilters,
        dialog,
        confirm,
        dialogLoading,
        handleConfirm,
        handleCancel,
    } = useMeteringPointActions({
        selectedZevId,
        canManageMeteringPoints,
    })

    // ── Loading / error ───────────────────────────────────────────────────────────
    if (meteringPointsQuery.isLoading) {
        return <div className="card">{t('pages.meteringPoints.loading')}</div>
    }
    if (meteringPointsQuery.isError) {
        return <div className="card error-banner">{t('pages.meteringPoints.loadFailed')}</div>
    }

    return (
        <div className="page-stack">
            <header>
                <h2>{t('pages.meteringPoints.title')}</h2>
                <p className="muted">
                    {canManageMeteringPoints
                        ? t('pages.meteringPoints.adminDescription')
                        : t('pages.meteringPoints.participantDescription')}
                </p>
            </header>

            <MeteringPointsToolbar
                canManageMeteringPoints={canManageMeteringPoints}
                totalCount={scopedMeteringPoints.length}
                activeCount={activeCount}
                inactiveCount={inactiveCount}
                assignedCount={assignedCount}
                searchTerm={searchTerm}
                statusFilter={statusFilter}
                typeFilter={typeFilter}
                onChangeSearchTerm={setSearchTerm}
                onChangeStatusFilter={setStatusFilter}
                onChangeTypeFilter={setTypeFilter}
                onOpenCreateModal={openCreateMpModal}
            />

            {/* ── Metering Point Create/Edit Modal ──────────────────────────────────── */}
            <MeteringPointFormModal
                isOpen={showMpModal}
                title={editingMpId ? t('pages.meteringPoints.editTitle') : t('pages.meteringPoints.createTitle')}
                submitLabel={editingMpId ? t('pages.meteringPoints.saveChanges') : t('pages.meteringPoints.createButton')}
                form={mpForm}
                isPending={saveMpMutation.isPending}
                onClose={closeMpModal}
                onSubmit={submitMpForm}
                setForm={setMpForm}
            />

            {/* ── Assignment Create/Edit Modal ──────────────────────────────────────── */}
            <MeteringAssignmentFormModal
                isOpen={showAssignModal}
                title={editingAssignId ? t('pages.meteringPoints.editAssignTitle') : t('pages.meteringPoints.assignTitle')}
                form={assignForm}
                participants={assignParticipants}
                isPending={saveAssignMutation.isPending}
                onClose={closeAssignModal}
                onSubmit={submitAssignForm}
                setForm={setAssignForm}
                submitLabel={editingAssignId ? t('pages.meteringPoints.saveAssignment') : t('pages.meteringPoints.assignParticipant')}
            />

            {/* ── Metering Points List ──────────────────────────────────────────────── */}
            <div className="table-card">
                {scopedMeteringPoints.length === 0 ? (
                    <MeteringPointsEmptyState
                        canManageMeteringPoints={canManageMeteringPoints}
                        hasFilters={false}
                        onOpenCreateModal={openCreateMpModal}
                        onClearFilters={() => undefined}
                    />
                ) : meteringPoints.length === 0 ? (
                    <MeteringPointsEmptyState
                        canManageMeteringPoints={canManageMeteringPoints}
                        hasFilters={hasFilters}
                        onOpenCreateModal={openCreateMpModal}
                        onClearFilters={() => {
                            setSearchTerm('')
                            setStatusFilter('all')
                            setTypeFilter('all')
                        }}
                    />
                ) : (
                    <MeteringPointsList
                        settings={settings}
                        meteringPoints={meteringPoints}
                        assignmentsByMeteringPoint={filteredAssignmentsByMeteringPoint}
                        participantNameById={participantNameById}
                        canManageMeteringPoints={canManageMeteringPoints}
                        canDeleteData={user?.role === 'admin'}
                        deleteMeteringPointPending={deleteMpMutation.isPending}
                        deleteAssignmentPending={deleteAssignMutation.isPending}
                        dialogLoading={dialogLoading}
                        confirm={confirm}
                        onOpenCreateAssignModal={openCreateAssignModal}
                        onOpenEditMeteringPoint={openEditMpModal}
                        onOpenDeleteDataModal={openDeleteDataModal}
                        onOpenEditAssignment={openEditAssignModal}
                        onDeleteMeteringPoint={(id) => deleteMpMutation.mutate(id)}
                        onDeleteAssignment={(id) => deleteAssignMutation.mutate(id)}
                    />
                )}
            </div>

            <MeteringDeleteDataModal
                settings={settings}
                isOpen={showDeleteDataModal}
                meterId={deleteDataTarget?.meter_id}
                mode={deleteDataMode}
                dateFrom={deleteDataFrom}
                dateTo={deleteDataTo}
                isPending={deleteMeteringDataMutation.isPending}
                onClose={closeDeleteDataModal}
                onConfirm={submitDeleteData}
                onChangeMode={setDeleteDataMode}
                onChangeRange={(nextFrom, nextTo) => {
                    setDeleteDataFrom(nextFrom)
                    setDeleteDataTo(nextTo)
                }}
            />

            {dialog && (
                <ConfirmDialog {...dialog} isLoading={dialogLoading} onConfirm={handleConfirm} onCancel={handleCancel} />
            )}
        </div>
    )
}
