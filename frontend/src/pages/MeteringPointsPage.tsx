import { useTranslation } from 'react-i18next'
import { PageHeader } from '../components/PageHeader'
import { PageState } from '../components/PageState'
import { Notice } from '../components/Notice'
import { ScopeGuard } from '../components/ScopeGuard'
import { ConfirmDialog } from '../components/ConfirmDialog'
import { MeteringAssignmentFormModal } from '../features/meteringPoints/MeteringAssignmentFormModal'
import { MeteringDeleteDataModal } from '../features/meteringPoints/MeteringDeleteDataModal'
import { MeteringPointsEmptyState } from '../features/meteringPoints/MeteringPointsEmptyState'
import { MeteringPointsList } from '../features/meteringPoints/MeteringPointsList'
import { MeteringPointFormModal } from '../features/meteringPoints/MeteringPointFormModal'
import { BuildingFormModal } from '../features/zev/BuildingFormModal'
import { BuildingHeader } from '../features/meteringPoints/BuildingHeader'
import { groupMeteringPointsByBuilding } from '../features/meteringPoints/useMeteringPointForms'
import { MeteringPointsToolbar } from '../features/meteringPoints/MeteringPointsToolbar'
import { useMeteringPointActions } from '../features/meteringPoints/useMeteringPointActions'
import { useAppSettings } from '../lib/appSettings'
import { useAuth } from '../lib/auth'
import { useManagedZev } from '../lib/managedZev'
import { useCommunityAccess, useScopeNote } from '../lib/communityAccess'
import { selectedCommunityName } from '../lib/membership'
import type { MeteringPoint } from '../types/api'

export function MeteringPointsPage() {
    const { user } = useAuth()
    const { selectedZevId, selectedZev, entries } = useManagedZev()
    const { canWriteSelectedCommunity: canWrite, isAdmin, isZevScope } = useCommunityAccess()
    const { t } = useTranslation()
    const scopeNote = useScopeNote()
    // Drafts survive a failed refresh, but never cross accounts, communities or write access.
    return (
        <div className="page-stack">
            <PageHeader
                eyebrow={selectedCommunityName({ selectedZev, entries, selectedZevId })}
                communitySwitch
                scopeNote={scopeNote}
                title={t('pages.meteringPoints.title')}
                description={t(isZevScope ? 'pages.meteringPoints.adminDescription' : 'pages.meteringPoints.participantDescription')}
            />
            <ScopeGuard>
                <MeteringPointsView
                    key={`${user?.id}:${selectedZevId}:${canWrite}:${isAdmin}`}
                    canWrite={canWrite}
                    canDeleteData={isAdmin}
                />
            </ScopeGuard>
        </div>
    )
}

function MeteringPointsView({ canWrite, canDeleteData }: { canWrite: boolean; canDeleteData: boolean }) {
    const { selectedZevId } = useManagedZev()
    const { settings } = useAppSettings()
    const { t } = useTranslation()
    const { isZevScope: isManagedScope } = useCommunityAccess()
    const readOnly = !canWrite

    const {
        meteringPointsQuery,
        scope,
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
        assignHasOpenEndedWarning,
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
        view,
        setView,
        typeFilter,
        setTypeFilter,
        buildingFilter,
        setBuildingFilter,
        buildings,
        landownersOf,
        editingBuilding,
        showBuildingModal,
        openCreateBuildingModal,
        openEditBuildingModal,
        closeBuildingModal,
        saveBuildingMutation,
        submitBuilding,
        deleteBuildingMutation,
        confirmDeleteBuilding,
        openCreateMpModalInBuilding,
        clearFilters,
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
        needsAttentionCount,
        hasFilters,
        meteringPointHealthById,
        meteringPointHolderLessById,
        dialog,
        confirm,
        dialogLoading,
        handleConfirm,
        handleCancel,
    } = useMeteringPointActions({
        selectedZevId,
        isManagedScope,
        canWrite,
        canDeleteData,
    })

    // Several buildings: cards grouped by building (a one-building ZEV keeps the flat list).
    const groups = isManagedScope && buildings.length > 1
        ? groupMeteringPointsByBuilding(buildings, meteringPoints, { filtersActive: hasFilters })
        : null
    // An empty building still shows its header, so the page is not "empty".
    const hasGroups = !!groups && groups.length > 0

    const typeCounts: Partial<Record<MeteringPoint['meter_type'], number>> = {}
    for (const point of scopedMeteringPoints) typeCounts[point.meter_type] = (typeCounts[point.meter_type] ?? 0) + 1

    return (
        <>
            {meteringPointsQuery.isError && meteringPointsQuery.data !== undefined && (
                <Notice tone="warning" onRetry={() => void meteringPointsQuery.refetch()} isRetrying={meteringPointsQuery.isFetching}>
                    {t('pages.meteringPoints.loadFailed')}
                </Notice>
            )}
            <PageState
                isLoading={meteringPointsQuery.isLoading}
                isError={meteringPointsQuery.isError && meteringPointsQuery.data === undefined}
                skeleton="cardList"
                error={t('pages.meteringPoints.loadFailed')}
                onRetry={() => void meteringPointsQuery.refetch()}
                isRetrying={meteringPointsQuery.isFetching}
            >
                <MeteringPointsToolbar
                    isManagedScope={isManagedScope}
                    readOnly={readOnly}
                    totalCount={scopedMeteringPoints.length}
                    activeCount={activeCount}
                    inactiveCount={inactiveCount}
                    assignedCount={assignedCount}
                    needsAttentionCount={needsAttentionCount}
                    searchTerm={searchTerm}
                    view={view}
                    typeFilter={typeFilter}
                    typeCounts={typeCounts}
                    buildings={buildings}
                    buildingFilter={buildingFilter}
                    onChangeBuildingFilter={setBuildingFilter}
                    onChangeSearchTerm={setSearchTerm}
                    onChangeView={setView}
                    onChangeTypeFilter={setTypeFilter}
                    onOpenCreateModal={openCreateMpModal}
                    onOpenCreateBuildingModal={openCreateBuildingModal}
                />
                {isManagedScope && (
                    <BuildingFormModal
                        isOpen={showBuildingModal}
                        zevId={selectedZevId ?? ''}
                        building={editingBuilding}
                        isPending={saveBuildingMutation.isPending}
                        onClose={closeBuildingModal}
                        onSubmit={submitBuilding}
                    />
                )}
                <MeteringPointFormModal
                    isOpen={showMpModal}
                    title={editingMpId ? t('pages.meteringPoints.editTitle') : t('pages.meteringPoints.createTitle')}
                    submitLabel={editingMpId ? t('pages.meteringPoints.saveChanges') : t('pages.meteringPoints.createButton')}
                    form={mpForm}
                    isPending={saveMpMutation.isPending}
                    onClose={closeMpModal}
                    onSubmit={submitMpForm}
                    setForm={setMpForm}
                    buildings={buildings}
                />
                <MeteringAssignmentFormModal
                    isOpen={showAssignModal}
                    title={editingAssignId ? t('pages.meteringPoints.editAssignTitle') : t('pages.meteringPoints.assignTitle')}
                    form={assignForm}
                    participants={assignParticipants}
                    isPending={saveAssignMutation.isPending}
                    hasOpenEndedWarning={assignHasOpenEndedWarning}
                    onClose={closeAssignModal}
                    onSubmit={submitAssignForm}
                    setForm={setAssignForm}
                    submitLabel={editingAssignId ? t('pages.meteringPoints.saveAssignment') : t('pages.meteringPoints.assignParticipant')}
                />

                {hasFilters && meteringPoints.length > 0 && (
                    <p className="muted metering-filtered-count">
                        {t('pages.meteringPoints.filteredCount', { shown: meteringPoints.length, total: scopedMeteringPoints.length })}
                    </p>
                )}
                {isManagedScope && buildings.length === 1 && (
                    <BuildingHeader
                        building={buildings[0]}
                        landowners={landownersOf(buildings[0])}
                        variant="line"
                        canManage={canWrite}
                        onEdit={openEditBuildingModal}
                    />
                )}
                <div className="table-card">
                    {scopedMeteringPoints.length === 0 && !hasGroups ? (
                        <MeteringPointsEmptyState
                            isManagedScope={isManagedScope}
                            readOnly={readOnly}
                            hasFilters={false}
                            onOpenCreateModal={openCreateMpModal}
                            onClearFilters={() => undefined}
                        />
                    ) : meteringPoints.length === 0 && !hasGroups ? (
                        <MeteringPointsEmptyState
                            isManagedScope={isManagedScope}
                            readOnly={readOnly}
                            hasFilters={hasFilters}
                            onOpenCreateModal={openCreateMpModal}
                            onClearFilters={clearFilters}
                        />
                    ) : (
                        <MeteringPointsList
                            settings={settings}
                            meteringPoints={meteringPoints}
                            assignmentsByMeteringPoint={filteredAssignmentsByMeteringPoint}
                            participantNameById={participantNameById}
                            healthByMeteringPoint={meteringPointHealthById}
                            holderLessByMeteringPoint={meteringPointHolderLessById}
                            isManagedScope={isManagedScope}
                            showBuilding={isManagedScope && buildings.length > 1}
                            groups={groups}
                            renderGroupHeader={(group) => (
                                <BuildingHeader
                                    building={group.building}
                                    landowners={landownersOf(group.building)}
                                    variant="group"
                                    canManage={canWrite}
                                    deletePending={deleteBuildingMutation.isPending}
                                    onEdit={openEditBuildingModal}
                                    onDelete={confirmDeleteBuilding}
                                    onAddMeteringPoint={(building) => openCreateMpModalInBuilding(building.id)}
                                />
                            )}
                            readOnly={readOnly}
                            canDeleteData={canDeleteData}
                            deleteMeteringPointPending={deleteMpMutation.isPending}
                            deleteAssignmentPending={deleteAssignMutation.isPending}
                            dialogLoading={dialogLoading}
                            confirm={confirm}
                            onOpenCreateAssignModal={openCreateAssignModal}
                            onOpenEditMeteringPoint={openEditMpModal}
                            onOpenDeleteDataModal={openDeleteDataModal}
                            onOpenEditAssignment={openEditAssignModal}
                            onDeleteMeteringPoint={(id) => deleteMpMutation.mutate({ id, scope })}
                            onDeleteAssignment={(id) => deleteAssignMutation.mutate({ id, scope })}
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
            </PageState>
        </>
    )
}
