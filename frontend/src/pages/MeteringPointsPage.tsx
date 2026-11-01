import { useState } from 'react'
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
import { ConnectionPointCard, PointLiveDialog, useLiveSetup } from '../features/meteringPoints/LiveSetup'
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
    const liveSetup = useLiveSetup({ zevId: selectedZevId || undefined, canWrite, isManagedScope })
    const [livePoint, setLivePoint] = useState<MeteringPoint | null>(null)

    const {
        meteringPointsQuery,
        dataQualityQuery,
        assignmentsQuery,
        scope,
        saveMpMutation,
        deleteMpMutation,
        saveAssignMutation,
        deleteAssignMutation,
        deleteMeteringDataMutation,
        mpForm,
        setMpForm,
        mpFieldErrors,
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
        sort,
        setSort,
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
        unassignedCount,
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

    // Every building is a group with the same header, one or several. A role that has no buildings loaded
    // (participants), or a community whose buildings have not arrived yet, gets one plain list.
    const groups = isManagedScope && buildings.length > 0
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
                {dataQualityQuery.isError ? (
                    <Notice tone="warning" onRetry={() => void dataQualityQuery.refetch()} isRetrying={dataQualityQuery.isFetching}>
                        {t('pages.meteringPoints.qualityLoadFailed')}
                    </Notice>
                ) : scopedMeteringPoints.some(point => meteringPointHealthById.get(point.id) === 'unknown') && (
                    <p className="muted" role="status">{t(dataQualityQuery.isFetching ? 'pages.meteringPoints.qualityLoading' : 'pages.meteringPoints.qualityIncomplete')}</p>
                )}
                {isManagedScope && (assignmentsQuery.isError ? (
                    <Notice tone="warning" onRetry={() => void assignmentsQuery.refetch()} isRetrying={assignmentsQuery.isFetching}>
                        {t('pages.meteringPoints.assignmentsLoadFailed')}
                    </Notice>
                ) : assignmentsQuery.data === undefined && (
                    <p className="muted" role="status">{t('pages.meteringPoints.assignmentsLoading')}</p>
                ))}
                {isManagedScope && selectedZevId && (
                    <ConnectionPointCard zevId={selectedZevId} setup={liveSetup} canWrite={canWrite} confirm={confirm} />
                )}
                <MeteringPointsToolbar
                    isManagedScope={isManagedScope}
                    readOnly={readOnly}
                    totalCount={scopedMeteringPoints.length}
                    activeCount={activeCount}
                    inactiveCount={inactiveCount}
                    unassignedCount={unassignedCount}
                    needsAttentionCount={needsAttentionCount}
                    searchTerm={searchTerm}
                    view={view}
                    sort={sort}
                    typeFilter={typeFilter}
                    typeCounts={typeCounts}
                    buildings={buildings}
                    buildingFilter={buildingFilter}
                    onChangeBuildingFilter={setBuildingFilter}
                    onChangeSearchTerm={setSearchTerm}
                    onChangeView={setView}
                    onChangeSort={setSort}
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
                    fieldErrors={mpFieldErrors}
                    historyProtected={meteringPointsQuery.data?.find((point) => point.id === editingMpId)?.history_protected}
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
                {scopedMeteringPoints.length === 0 && !hasGroups ? (
                    <div className="table-card">
                        <MeteringPointsEmptyState
                            isManagedScope={isManagedScope}
                            readOnly={readOnly}
                            hasFilters={false}
                            onOpenCreateModal={openCreateMpModal}
                            onClearFilters={() => undefined}
                        />
                    </div>
                ) : meteringPoints.length === 0 && !hasGroups ? (
                    <div className="table-card">
                        <MeteringPointsEmptyState
                            isManagedScope={isManagedScope}
                            readOnly={readOnly}
                            hasFilters={hasFilters}
                            onOpenCreateModal={openCreateMpModal}
                            onClearFilters={clearFilters}
                        />
                    </div>
                ) : (
                    <MeteringPointsList
                        settings={settings}
                        meteringPoints={meteringPoints}
                        assignmentsAvailable={assignmentsQuery.data !== undefined}
                        assignmentsByMeteringPoint={filteredAssignmentsByMeteringPoint}
                        participantNameById={participantNameById}
                        healthByMeteringPoint={meteringPointHealthById}
                        holderLessByMeteringPoint={meteringPointHolderLessById}
                        isManagedScope={isManagedScope}
                        groups={groups}
                        renderGroupHeader={(group) => (
                            <BuildingHeader
                                building={group.building}
                                landowners={landownersOf(group.building)}
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
                        liveSetupPointIds={canWrite ? new Set(liveSetup.zevEligibleByPoint.keys()) : undefined}
                        onOpenLive={setLivePoint}
                    />
                )}

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

                {livePoint && <PointLiveDialog point={livePoint} setup={liveSetup} confirm={confirm} onClose={() => setLivePoint(null)} />}

                {dialog && (
                    <ConfirmDialog {...dialog} isLoading={dialogLoading} onConfirm={handleConfirm} onCancel={handleCancel} />
                )}
            </PageState>
        </>
    )
}
