import { FontAwesomeIcon } from '@fortawesome/react-fontawesome'
import {
  faChartLine,
  faDatabase,
  faEllipsis,
  faPen,
  faTrash,
  faTriangleExclamation,
  faUserPlus,
} from '@fortawesome/free-solid-svg-icons'
import { Link } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { ActionMenu, type ActionMenuItem } from '../../components/ActionMenu'
import { formatDateTime, formatShortDate } from '../../lib/appSettings'
import { todayLocalIso } from '../../lib/dates'
import type { AppSettings, MeteringPoint, MeteringPointAssignment } from '../../types/api'
import {
  assignmentStateBadgeClass,
  assignmentStateSortOrder,
  getAssignmentState,
  meteringPointHealthBadgeClass,
  type MeteringPointHealth,
} from './useMeteringPointForms'

type ConfirmOptions = {
  title: string
  message: string
  confirmText: string
  isDangerous: boolean
  onConfirm: () => void | Promise<void>
}

type MeteringPointsListProps = {
  meteringPoints: MeteringPoint[]
  assignmentsByMeteringPoint: Map<string, MeteringPointAssignment[]>
  participantNameById: Map<string, string>
  healthByMeteringPoint: Map<string, MeteringPointHealth>
  /** Empty for a role that has no assignment data loaded (see the hook) — never render a false positive from a missing entry. */
  holderLessByMeteringPoint: Map<string, boolean>
  settings: AppSettings
  canManageMeteringPoints: boolean
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
  assignmentsByMeteringPoint,
  participantNameById,
  healthByMeteringPoint,
  holderLessByMeteringPoint,
  settings,
  canManageMeteringPoints,
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
  const todayIso = todayLocalIso()

  // Shared by both the compact (single current holder) and expanded assignment
  // rendering below — Remove lives in the overflow menu everywhere, matching
  // the meter-level Edit/Delete pattern instead of a standalone danger button.
  function assignmentMenuItems(assignment: MeteringPointAssignment): ActionMenuItem[] {
    return [
      {
        key: 'remove',
        label: t('pages.meteringPoints.removeAssignment'),
        icon: <FontAwesomeIcon icon={faTrash} fixedWidth />,
        disabled: deleteAssignmentPending || dialogLoading,
        danger: true,
        onClick: () =>
          confirm({
            title: t('pages.meteringPoints.removeAssignTitle'),
            message: t('pages.meteringPoints.removeAssignMessage', {
              name: participantNameById.get(assignment.participant) ?? assignment.participant,
            }),
            confirmText: t('pages.meteringPoints.removeAssignConfirm'),
            isDangerous: true,
            onConfirm: () => onDeleteAssignment(assignment.id),
          }),
      },
    ]
  }

  return (
    <div className="metering-point-list">
      {meteringPoints.map((point) => {
        const assignments = assignmentsByMeteringPoint.get(point.id) ?? []
        const sortedAssignments = [...assignments].sort((left, right) => {
          const leftState = getAssignmentState(left, todayIso)
          const rightState = getAssignmentState(right, todayIso)
          const stateDelta = assignmentStateSortOrder(leftState) - assignmentStateSortOrder(rightState)

          if (stateDelta !== 0) return stateDelta
          return right.valid_from.localeCompare(left.valid_from)
        })

        const health = healthByMeteringPoint.get(point.id) ?? 'no_data'
        const isHolderLess = holderLessByMeteringPoint.get(point.id) ?? false
        // The common case (one tenant, ongoing) doesn't need the full
        // history layout — collapse it to a single line (#624).
        const isSingleCurrentHolder = sortedAssignments.length === 1
          && getAssignmentState(sortedAssignments[0], todayIso) === 'current'

        const pointMenuItems: ActionMenuItem[] = []
        if (canManageMeteringPoints) {
          pointMenuItems.push({
            key: 'edit',
            label: t('common.edit'),
            icon: <FontAwesomeIcon icon={faPen} fixedWidth />,
            onClick: () => onOpenEditMeteringPoint(point),
          })

          if (canDeleteData) {
            pointMenuItems.push({
              key: 'delete-data',
              label: t('pages.meteringPoints.deleteData.button'),
              icon: <FontAwesomeIcon icon={faDatabase} fixedWidth />,
              onClick: () => onOpenDeleteDataModal(point),
            })
          }

          pointMenuItems.push({
            key: 'delete',
            label: t('common.delete'),
            icon: <FontAwesomeIcon icon={faTrash} fixedWidth />,
            disabled: deleteMeteringPointPending || dialogLoading,
            danger: true,
            onClick: () =>
              confirm({
                title: t('pages.meteringPoints.deleteTitle'),
                message: t('pages.meteringPoints.deleteMessage', {
                  meterId: point.meter_id,
                  readingCount: point.reading_count,
                  assignmentCount: point.assignment_count,
                }),
                confirmText: t('pages.meteringPoints.deleteConfirm'),
                isDangerous: true,
                onConfirm: () => onDeleteMeteringPoint(point.id),
              }),
          })
        }

        return (
          <article key={point.id} className="metering-point-card">
            <div className="metering-point-card-header">
              <div className="metering-point-title">
                <strong>{point.meter_id}</strong>
                <span className="muted">{point.location_description || t('pages.meteringPoints.noLocation')}</span>
                <div className="metering-point-badges">
                  <span className={point.is_active ? 'badge badge-success' : 'badge badge-danger'}>
                    {point.is_active ? t('pages.meteringPoints.active') : t('pages.meteringPoints.inactive')}
                  </span>
                  <span className="badge badge-neutral">{t(`pages.meteringPoints.meterTypes.${point.meter_type}`)}</span>
                  <Link
                    className={meteringPointHealthBadgeClass(health)}
                    style={{ textDecoration: 'none' }}
                    to={`/metering-data?metering_point=${point.id}&tab=quality`}
                    title={t('pages.meteringPoints.health.linkHint')}
                  >
                    {t(`pages.meteringPoints.health.${health}`)}
                  </Link>
                  {isHolderLess && (
                    <span className="badge badge-danger" title={t('pages.meteringPoints.holderLessHint')}>
                      <FontAwesomeIcon icon={faTriangleExclamation} fixedWidth />
                      {t('pages.meteringPoints.holderLessBadge')}
                    </span>
                  )}
                </div>
                <span className="muted">
                  {point.last_reading_at
                    ? t('pages.meteringPoints.lastReading', { date: formatDateTime(point.last_reading_at, settings) })
                    : t('pages.meteringPoints.neverReceivedData')}
                </span>
              </div>

              <div className="metering-point-actions">
                {canManageMeteringPoints && (
                  <button
                    className="button button-primary button-compact"
                    type="button"
                    onClick={() => onOpenCreateAssignModal(point.id)}
                  >
                    <FontAwesomeIcon icon={faUserPlus} fixedWidth />
                    {t('pages.meteringPoints.assign')}
                  </button>
                )}
                <Link
                  className="button button-secondary button-compact"
                  style={{ textDecoration: 'none' }}
                  to={`/metering-data?metering_point=${point.id}`}
                >
                  <FontAwesomeIcon icon={faChartLine} fixedWidth />
                  {t('pages.meteringPoints.chart')}
                </Link>
                {canManageMeteringPoints && (
                  <ActionMenu
                    label={t('pages.meteringPoints.moreActions')}
                    icon={<FontAwesomeIcon icon={faEllipsis} fixedWidth />}
                    items={pointMenuItems}
                  />
                )}
              </div>
            </div>

            {canManageMeteringPoints && (
              <div className="metering-point-body">
                {isSingleCurrentHolder ? (
                  <div className="metering-assignment-compact">
                    <span>
                      {t('pages.meteringPoints.heldBySince', {
                        name: participantNameById.get(sortedAssignments[0].participant) ?? sortedAssignments[0].participant,
                        date: formatShortDate(sortedAssignments[0].valid_from, settings),
                      })}
                      {sortedAssignments[0].allocation_mode === 'community' && (
                        <span className="badge badge-info metering-assignment-compact-badge">
                          {t('pages.meteringPoints.communityBadge')}
                        </span>
                      )}
                    </span>
                    <div className="metering-assignment-actions">
                      <button
                        className="button button-secondary button-compact"
                        type="button"
                        onClick={() => onOpenEditAssignment(sortedAssignments[0])}
                      >
                        <FontAwesomeIcon icon={faPen} fixedWidth />
                        {t('common.edit')}
                      </button>
                      <ActionMenu
                        label={t('pages.meteringPoints.moreActions')}
                        icon={<FontAwesomeIcon icon={faEllipsis} fixedWidth />}
                        items={assignmentMenuItems(sortedAssignments[0])}
                      />
                    </div>
                  </div>
                ) : sortedAssignments.length > 0 ? (
                  <div className="metering-assignment-list">
                    {sortedAssignments.map((assignment) => {
                      const assignmentState = getAssignmentState(assignment, todayIso)
                      return (
                        <div key={assignment.id} className="metering-assignment-row">
                          <div className="metering-assignment-main">
                            <div className="metering-assignment-line">
                              <strong>{participantNameById.get(assignment.participant) ?? assignment.participant}</strong>
                              <span className={assignmentStateBadgeClass(assignmentState)}>
                                {t(`pages.meteringPoints.assignmentState.${assignmentState}`)}
                              </span>
                              {assignment.allocation_mode === 'community' && (
                                <span className="badge badge-info">
                                  {t('pages.meteringPoints.communityBadge')}
                                </span>
                              )}
                            </div>
                            <div className="muted">
                              {formatShortDate(assignment.valid_from, settings)} -{' '}
                              {assignment.valid_to ? formatShortDate(assignment.valid_to, settings) : t('pages.meteringPoints.openEnded')}
                            </div>
                          </div>

                          <div className="metering-assignment-actions">
                            <button
                              className="button button-secondary button-compact"
                              type="button"
                              onClick={() => onOpenEditAssignment(assignment)}
                            >
                              <FontAwesomeIcon icon={faPen} fixedWidth />
                              {t('common.edit')}
                            </button>
                            <ActionMenu
                              label={t('pages.meteringPoints.moreActions')}
                              icon={<FontAwesomeIcon icon={faEllipsis} fixedWidth />}
                              items={assignmentMenuItems(assignment)}
                            />
                          </div>
                        </div>
                      )
                    })}
                  </div>
                ) : (
                  <p className="muted metering-no-assignments">{t('pages.meteringPoints.noAssignments')}</p>
                )}
              </div>
            )}
          </article>
        )
      })}
    </div>
  )
}
