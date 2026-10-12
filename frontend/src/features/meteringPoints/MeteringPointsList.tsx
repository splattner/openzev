import { useState, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { todayBusinessIso } from '../../lib/dates'
import type { AppSettings, Building, MeteringPoint, MeteringPointAssignment } from '../../types/api'
import { MeteringPointRow, type ConfirmOptions } from './MeteringPointRow'
import {
  countMeteringPointStatuses,
  type BuildingGroup,
  type MeteringPointHealth,
  type MeteringPointStatus,
} from './useMeteringPointForms'

/** What a group's header needs to be the toggle of its meters and to summarise them. */
export type BuildingGroupHeaderState = {
  collapsed: boolean
  /** Absent while a filter is active: the matches are then always shown. */
  onToggle?: () => void
  /** The id of the element holding the group's meters. */
  panelId: string
  statusCounts: Record<MeteringPointStatus, number>
}

type MeteringPointsListProps = {
  meteringPoints: MeteringPoint[]
  assignmentsByMeteringPoint: Map<string, MeteringPointAssignment[]>
  participantNameById: Map<string, string>
  healthByMeteringPoint: Map<string, MeteringPointHealth>
  statusByMeteringPoint: Map<string, MeteringPointStatus>
  /** Empty for a role that has no assignment data loaded (see the hook) — never render a false positive from a missing entry. */
  holderLessByMeteringPoint: Map<string, boolean>
  settings: AppSettings
  isManagedScope: boolean
  /** Name the building under each meter; only for a ZEV with several buildings and no group headers (#890). */
  showBuilding?: boolean
  buildings?: Building[]
  /** Several buildings: the meters grouped by building, each group headed by `renderGroupHeader`. */
  groups?: BuildingGroup[] | null
  renderGroupHeader?: (group: BuildingGroup, state: BuildingGroupHeaderState) => ReactNode
  /** Whether a filter narrows the list; the matches are never folded away. */
  filtersActive?: boolean
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
  onEditBuilding?: (building: Building) => void
}

function toggled(set: Set<string>, id: string): Set<string> {
  const next = new Set(set)
  if (next.has(id)) next.delete(id)
  else next.add(id)
  return next
}

export function MeteringPointsList({
  meteringPoints,
  assignmentsByMeteringPoint,
  participantNameById,
  healthByMeteringPoint,
  statusByMeteringPoint,
  holderLessByMeteringPoint,
  settings,
  isManagedScope,
  showBuilding = false,
  buildings = [],
  groups = null,
  renderGroupHeader,
  filtersActive = false,
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
  onEditBuilding,
}: MeteringPointsListProps) {
  const { t } = useTranslation()
  const todayIso = todayBusinessIso()
  const [expandedIds, setExpandedIds] = useState<Set<string>>(() => new Set())
  const [collapsedBuildingIds, setCollapsedBuildingIds] = useState<Set<string>>(() => new Set())

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
      buildingLabel={showBuilding && !groups ? point.building_name : null}
      building={showBuilding && !groups ? buildings.find((candidate) => candidate.id === point.building) ?? null : null}
      expanded={expandedIds.has(point.id)}
      onToggle={() => setExpandedIds((current) => toggled(current, point.id))}
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
      onEditBuilding={onEditBuilding}
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
        {groups.map((group) => {
          const panelId = `building-panel-${group.building.id}`
          const collapsed = collapsedBuildingIds.has(group.building.id) && !filtersActive
          return (
            <section key={group.building.id} className={`building-group ${sheetClass}`}>
              {renderGroupHeader(group, {
                collapsed,
                onToggle: filtersActive ? undefined : () => setCollapsedBuildingIds((current) => toggled(current, group.building.id)),
                panelId,
                statusCounts: countMeteringPointStatuses(group.points, statusByMeteringPoint),
              })}
              <div id={panelId} hidden={collapsed}>
                {group.points.length === 0 ? (
                  <p className="muted building-group-empty">{t('pages.meteringPoints.buildings.emptyGroup')}</p>
                ) : (
                  <>
                    {columns}
                    <div className="metering-point-list">{group.points.map(renderRow)}</div>
                  </>
                )}
              </div>
            </section>
          )
        })}
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
