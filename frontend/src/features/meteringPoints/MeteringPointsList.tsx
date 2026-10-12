import { useState, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { todayBusinessIso } from '../../lib/dates'
import type { AppSettings, MeteringPoint, MeteringPointAssignment } from '../../types/api'
import { MeteringPointRow, type ConfirmOptions } from './MeteringPointRow'
import {
  countMeteringPointStatuses,
  type BuildingGroup,
  type MeteringPointHealth,
  type MeteringPointStatus,
} from './useMeteringPointForms'

/** What a group's header needs to sum its meters up. */
export type BuildingGroupHeaderState = {
  statusCounts: Record<MeteringPointStatus, number>
}

type MeteringPointsListProps = {
  meteringPoints: MeteringPoint[]
  /** Every meter of the community, filters aside: a building's roll-up sums up the building, not just what the filters leave. */
  allMeteringPoints?: MeteringPoint[]
  assignmentsByMeteringPoint: Map<string, MeteringPointAssignment[]>
  participantNameById: Map<string, string>
  healthByMeteringPoint: Map<string, MeteringPointHealth>
  statusByMeteringPoint: Map<string, MeteringPointStatus>
  /** Empty for a role that has no assignment data loaded (see the hook) — never render a false positive from a missing entry. */
  holderLessByMeteringPoint: Map<string, boolean>
  settings: AppSettings
  isManagedScope: boolean
  /** The meters grouped by building, each group headed by `renderGroupHeader`; without them (a role that has no buildings) one plain list. */
  groups?: BuildingGroup[] | null
  renderGroupHeader?: (group: BuildingGroup, state: BuildingGroupHeaderState) => ReactNode
  /** A viewer reads only (#761): no edit, assign, delete. */
  readOnly?: boolean
  canDeleteData: boolean
  deleteMeteringPointPending: boolean
  deleteAssignmentPending: boolean
  dialogLoading: boolean
  confirm: (options: ConfirmOptions) => void
  onOpenCreateAssignModal: (meteringPointId: string) => void
  onOpenEditMeteringPoint: (point: MeteringPoint) => void
  onOpenDeleteDataModal: (point: MeteringPoint) => void
  onOpenEditAssignment: (assignment: MeteringPointAssignment) => void
  onDeleteMeteringPoint: (id: string) => void
  onDeleteAssignment: (id: string) => void
}

export function MeteringPointsList({
  meteringPoints,
  allMeteringPoints,
  assignmentsByMeteringPoint,
  participantNameById,
  healthByMeteringPoint,
  statusByMeteringPoint,
  holderLessByMeteringPoint,
  settings,
  isManagedScope,
  groups = null,
  renderGroupHeader,
  readOnly = false,
  canDeleteData,
  deleteMeteringPointPending,
  deleteAssignmentPending,
  dialogLoading,
  confirm,
  onOpenCreateAssignModal,
  onOpenEditMeteringPoint,
  onOpenDeleteDataModal,
  onOpenEditAssignment,
  onDeleteMeteringPoint,
  onDeleteAssignment,
}: MeteringPointsListProps) {
  const { t } = useTranslation()
  const todayIso = todayBusinessIso()
  const [expandedIds, setExpandedIds] = useState<Set<string>>(() => new Set())

  const renderRow = (point: MeteringPoint) => (
    <MeteringPointRow
      key={point.id}
      point={point}
      assignments={assignmentsByMeteringPoint.get(point.id) ?? []}
      participantNameById={participantNameById}
      settings={settings}
      todayIso={todayIso}
      health={healthByMeteringPoint.get(point.id) ?? 'no_data'}
      holderLess={holderLessByMeteringPoint.get(point.id) ?? false}
      status={statusByMeteringPoint.get(point.id) ?? 'pending'}
      isManagedScope={isManagedScope}
      readOnly={readOnly}
      canDeleteData={canDeleteData}
      expanded={expandedIds.has(point.id)}
      onToggle={() => setExpandedIds((current) => {
        const next = new Set(current)
        if (!next.delete(point.id)) next.add(point.id)
        return next
      })}
      deleteMeteringPointPending={deleteMeteringPointPending}
      deleteAssignmentPending={deleteAssignmentPending}
      dialogLoading={dialogLoading}
      confirm={confirm}
      onOpenCreateAssignModal={onOpenCreateAssignModal}
      onOpenEditMeteringPoint={onOpenEditMeteringPoint}
      onOpenDeleteDataModal={onOpenDeleteDataModal}
      onOpenEditAssignment={onOpenEditAssignment}
      onDeleteMeteringPoint={onDeleteMeteringPoint}
      onDeleteAssignment={onDeleteAssignment}
    />
  )

  const sheetClass = `metering-sheet${isManagedScope ? ' metering-sheet-holders' : ''}`
  const columns = (
    <div className="metering-point-columns" aria-hidden="true">
      <span />
      <span>{t('pages.meteringPoints.columns.meter')}</span>
      {isManagedScope && <span>{t('pages.meteringPoints.columns.holder')}</span>}
      <span>{t('pages.meteringPoints.columns.lastReading')}</span>
      <span />
    </div>
  )

  if (groups && renderGroupHeader) {
    return (
      <div className="building-groups">
        {groups.map((group) => (
          <section key={group.building.id} className={`building-group ${sheetClass}`}>
            {renderGroupHeader(group, {
              statusCounts: countMeteringPointStatuses(
                (allMeteringPoints ?? meteringPoints).filter((candidate) => candidate.building === group.building.id),
                statusByMeteringPoint,
              ),
            })}
            {group.points.length === 0 ? (
              <p className="muted building-group-empty">{t('pages.meteringPoints.buildings.emptyGroup')}</p>
            ) : (
              <>
                {columns}
                <div className="metering-point-list">{group.points.map(renderRow)}</div>
              </>
            )}
          </section>
        ))}
      </div>
    )
  }

  return (
    <div className={sheetClass}>
      {columns}
      <div className="metering-point-list">{meteringPoints.map(renderRow)}</div>
    </div>
  )
}
