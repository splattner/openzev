import { FontAwesomeIcon } from '@fortawesome/react-fontawesome'
import {
  faChartLine,
  faDatabase,
  faEllipsis,
  faPen,
  faTrash,
  faUserPlus,
} from '@fortawesome/free-solid-svg-icons'
import { Link } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { ActionMenu, type ActionMenuItem } from '../../components/ActionMenu'
import { formatShortDate } from '../../lib/appSettings'
import { todayLocalIso } from '../../lib/dates'
import type { AppSettings, MeteringPoint, MeteringPointAssignment } from '../../types/api'
import {
  assignmentStateBadgeClass,
  assignmentStateSortOrder,
  getAssignmentState,
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
                message: t('pages.meteringPoints.deleteMessage', { meterId: point.meter_id }),
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
                <div className="metering-point-badges">
                  <span className={point.is_active ? 'badge badge-success' : 'badge badge-danger'}>
                    {point.is_active ? t('pages.meteringPoints.active') : t('pages.meteringPoints.inactive')}
                  </span>
                  <span className="badge badge-neutral">{t(`pages.meteringPoints.meterTypes.${point.meter_type}`)}</span>
                </div>
                <strong>{point.meter_id}</strong>
              </div>

              <div className="metering-point-actions">
                {canManageMeteringPoints && assignments.length === 0 && (
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
                {sortedAssignments.length > 0 ? (
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
                            <button
                              className="button button-danger button-compact"
                              type="button"
                              disabled={deleteAssignmentPending || dialogLoading}
                              onClick={() =>
                                confirm({
                                  title: t('pages.meteringPoints.removeAssignTitle'),
                                  message: t('pages.meteringPoints.removeAssignMessage', {
                                    name: participantNameById.get(assignment.participant) ?? assignment.participant,
                                  }),
                                  confirmText: t('pages.meteringPoints.removeAssignConfirm'),
                                  isDangerous: true,
                                  onConfirm: () => onDeleteAssignment(assignment.id),
                                })
                              }
                            >
                              <FontAwesomeIcon icon={faTrash} fixedWidth />
                              {t('pages.meteringPoints.removeAssignment')}
                            </button>
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
