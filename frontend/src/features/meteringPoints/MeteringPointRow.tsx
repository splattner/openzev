import { useMemo, type MouseEvent } from 'react'
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome'
import {
  faBolt,
  faChartLine,
  faChevronDown,
  faDatabase,
  faEllipsis,
  faPen,
  faPlus,
  faRightLeft,
  faSolarPanel,
  faTrash,
  faTriangleExclamation,
  faUserPlus,
  type IconDefinition,
} from '@fortawesome/free-solid-svg-icons'
import { Link } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { ActionMenu, type ActionMenuItem } from '../../components/ActionMenu'
import { BehindMeterBadge } from '../../components/BehindMeterBadge'
import { formatDateTime, formatShortDate } from '../../lib/appSettings'
import { formatBusinessIsoDate } from '../../lib/dates'
import { formatNumber } from '../../lib/numbers'
import { statusTone } from '../../lib/supplementary'
import type { AppSettings, MeteringPoint, MeteringPointAssignment } from '../../types/api'
import { SupplementarySourceStatus } from './SupplementarySourceStatus'
import {
  assignmentStateBadgeClass,
  assignmentStateSortOrder,
  getAssignmentState,
  meteringPointHealthBadgeClass,
  type MeteringPointHealth,
} from './useMeteringPointForms'

export type ConfirmOptions = {
  title: string
  message: string
  confirmText: string
  isDangerous: boolean
  onConfirm: () => void | Promise<void>
}

export const METER_TYPE_ICON: Record<MeteringPoint['meter_type'], IconDefinition> = {
  consumption: faBolt,
  production: faSolarPanel,
  bidirectional: faRightLeft,
}

type MeteringPointRowProps = {
  point: MeteringPoint
  assignments: MeteringPointAssignment[]
  participantNameById: Map<string, string>
  settings: AppSettings
  todayIso: string
  health: MeteringPointHealth
  holderLess: boolean
  isManagedScope: boolean
  readOnly: boolean
  canDeleteData: boolean
  expanded: boolean
  onToggle: () => void
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

/**
 * One metering point as a line of facts — ID, type, holder, last reading — that
 * opens in place to its participants, measurement and location. Badges are for
 * what is unusual about the meter itself; its data health is in the details.
 */
export function MeteringPointRow({
  point,
  assignments,
  participantNameById,
  settings,
  todayIso,
  health,
  holderLess,
  isManagedScope,
  readOnly,
  canDeleteData,
  expanded,
  onToggle,
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
}: MeteringPointRowProps) {
  const { t } = useTranslation()
  const canWrite = isManagedScope && !readOnly
  const nameOf = (assignment: MeteringPointAssignment) => participantNameById.get(assignment.participant) ?? assignment.participant

  const sortedAssignments = useMemo(
    () => [...assignments].sort((left, right) => {
      const stateDelta = assignmentStateSortOrder(getAssignmentState(left, todayIso))
        - assignmentStateSortOrder(getAssignmentState(right, todayIso))
      return stateDelta || right.valid_from.localeCompare(left.valid_from)
    }),
    [assignments, todayIso],
  )
  const current = sortedAssignments.filter((assignment) => getAssignmentState(assignment, todayIso) === 'current')
  const upcoming = sortedAssignments.filter((assignment) => getAssignmentState(assignment, todayIso) === 'upcoming')
  const earlierCount = sortedAssignments.length - current.length - upcoming.length

  const typeLabel = t(`pages.meteringPoints.meterTypes.${point.meter_type}`)
  const location = point.location_description?.trim() ?? ''
  const subtitle = location || t('pages.meteringPoints.noLocation')
  const lastReadingDate = point.last_reading_at ? formatShortDate(formatBusinessIsoDate(new Date(point.last_reading_at)), settings) : null
  // A source in trouble is worth a badge on the row; a healthy or pending one sits in the details.
  const sourceTone = statusTone(point.supplementary_source_status)
  const sourceNeedsAttention = sourceTone === 'warning' || sourceTone === 'danger'

  function confirmRemoveAssignment(assignment: MeteringPointAssignment) {
    confirm({
      title: t('pages.meteringPoints.removeAssignTitle'),
      message: t('pages.meteringPoints.removeAssignMessage', { name: nameOf(assignment) }),
      confirmText: t('pages.meteringPoints.removeAssignConfirm'),
      isDangerous: true,
      onConfirm: () => onDeleteAssignment(assignment.id),
    })
  }

  const pointMenuItems: ActionMenuItem[] = []
  if (canWrite) {
    pointMenuItems.push({
      key: 'assign',
      label: t('pages.meteringPoints.assign'),
      icon: <FontAwesomeIcon icon={faUserPlus} fixedWidth />,
      onClick: () => onOpenCreateAssignModal(point.id),
    })
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

  // The whole line opens the details, but a click on a control inside it (or in its menu, which
  // React still bubbles through the portal) belongs to that control, and so does the end of a drag
  // that selected the meter ID to copy it.
  function handleRowClick(event: MouseEvent<HTMLDivElement>) {
    const target = event.target as HTMLElement
    if (!event.currentTarget.contains(target) || target.closest('a, button, input, select, [role="menu"]')) return
    if (window.getSelection()?.toString()) return
    onToggle()
  }

  function renderHolder() {
    if (current.length > 0) {
      return (
        <>
          <strong className="metering-holder-name">{nameOf(current[0])}</strong>
          {current.length > 1 && <span className="metering-holder-more">+{current.length - 1}</span>}
          <span className="muted metering-holder-since">
            {t('pages.meteringPoints.since', { date: formatShortDate(current[0].valid_from, settings) })}
          </span>
          {current[0].allocation_mode === 'community' && (
            <span className="badge badge-tag">{t('pages.meteringPoints.communityBadge')}</span>
          )}
          {earlierCount > 0 && (
            <span className="muted metering-holder-since">{t('pages.meteringPoints.earlierAssignments', { count: earlierCount })}</span>
          )}
        </>
      )
    }
    if (upcoming.length > 0) {
      return (
        <>
          <strong className="metering-holder-name">{nameOf(upcoming[0])}</strong>
          <span className={assignmentStateBadgeClass('upcoming')}>{t('pages.meteringPoints.assignmentState.upcoming')}</span>
          <span className="muted metering-holder-since">
            {t('pages.meteringPoints.fromDate', { date: formatShortDate(upcoming[0].valid_from, settings) })}
          </span>
        </>
      )
    }
    // Nobody holds it: the one place a row asks for action.
    if (canWrite && point.is_active) {
      return (
        <button
          className="button button-primary button-outline button-compact"
          type="button"
          onClick={() => onOpenCreateAssignModal(point.id)}
        >
          <FontAwesomeIcon icon={faUserPlus} fixedWidth />
          {t('pages.meteringPoints.assign')}
        </button>
      )
    }
    return <span className="muted" aria-label={t('pages.meteringPoints.noAssignments')}>—</span>
  }

  const detailId = `metering-point-detail-${point.id}`

  return (
    <article className={`metering-point-card${expanded ? ' is-expanded' : ''}`}>
      <div className="metering-point-row" onClick={handleRowClick}>
        <div className="metering-point-title">
          <div className="metering-point-id">
            <span className="metering-point-id-main">
              <span className="metering-point-type" role="img" aria-label={typeLabel} title={typeLabel}>
                <FontAwesomeIcon icon={METER_TYPE_ICON[point.meter_type]} fixedWidth />
              </span>
              <strong>{point.meter_id}</strong>
            </span>
            {!point.is_active && <span className="badge badge-neutral">{t('pages.meteringPoints.inactive')}</span>}
            {holderLess && (
              <span className="badge badge-danger" title={t('pages.meteringPoints.holderLessHint')}>
                <FontAwesomeIcon icon={faTriangleExclamation} fixedWidth />
                {t('pages.meteringPoints.holderLessBadge')}
              </span>
            )}
            {point.has_behind_meter_generation && <BehindMeterBadge />}
            {isManagedScope && sourceNeedsAttention && (
              <SupplementarySourceStatus point={point} canManage={!readOnly} confirm={confirm} />
            )}
          </div>
          <span className="muted metering-point-subtitle">{subtitle}</span>
        </div>
        {isManagedScope && <div className="metering-point-holder">{renderHolder()}</div>}
        <span className="metering-point-last muted">
          {lastReadingDate ?? t('pages.meteringPoints.never')}
        </span>
        <div className="metering-point-actions">
          <Link
            className="button button-ghost button-compact"
            to={`/metering/chart?metering_point=${point.id}`}
            aria-label={t('pages.meteringPoints.chart')}
            title={t('pages.meteringPoints.chart')}
          >
            <FontAwesomeIcon icon={faChartLine} fixedWidth />
          </Link>
          {canWrite && (
            <ActionMenu
              label={t('pages.meteringPoints.moreActions')}
              icon={<FontAwesomeIcon icon={faEllipsis} fixedWidth />}
              iconOnly
              items={pointMenuItems}
            />
          )}
          <button
            type="button"
            className="button button-ghost button-compact metering-point-expand"
            aria-expanded={expanded}
            aria-controls={expanded ? detailId : undefined}
            aria-label={t(expanded ? 'pages.meteringPoints.detail.hide' : 'pages.meteringPoints.detail.show', { meterId: point.meter_id })}
            onClick={onToggle}
          >
            <FontAwesomeIcon icon={faChevronDown} fixedWidth />
          </button>
        </div>
      </div>

      {expanded && (
        <div className="metering-point-detail" id={detailId}>
          <div className={`metering-detail-grid${isManagedScope ? ' metering-detail-grid-participants' : ''}`}>
            {isManagedScope && (
              <section className="metering-detail-card metering-detail-participants">
                <header>
                  <h4>{t('pages.meteringPoints.detail.participants')}</h4>
                  {canWrite && (
                    <button type="button" className="button button-ghost button-compact" onClick={() => onOpenCreateAssignModal(point.id)}>
                      <FontAwesomeIcon icon={faPlus} fixedWidth />
                      {t('pages.meteringPoints.detail.addAssignment')}
                    </button>
                  )}
                </header>
                {sortedAssignments.length === 0 ? (
                  <p className="muted metering-no-assignments">{t('pages.meteringPoints.noAssignments')}</p>
                ) : (
                  <ul className="metering-assignment-list">
                    {sortedAssignments.map((assignment) => {
                      const state = getAssignmentState(assignment, todayIso)
                      return (
                        <li key={assignment.id} className={`metering-assignment-row${state === 'ended' ? ' is-ended' : ''}`}>
                          <div className="metering-assignment-main">
                            <span className="metering-assignment-line">
                              <strong>{nameOf(assignment)}</strong>
                              {state !== 'current' && (
                                <span className={assignmentStateBadgeClass(state)}>
                                  {t(`pages.meteringPoints.assignmentState.${state}`)}
                                </span>
                              )}
                              {assignment.allocation_mode === 'community' && (
                                <span className="badge badge-tag">{t('pages.meteringPoints.communityBadge')}</span>
                              )}
                            </span>
                            <span className="muted">
                              {formatShortDate(assignment.valid_from, settings)} –{' '}
                              {assignment.valid_to ? formatShortDate(assignment.valid_to, settings) : t('pages.meteringPoints.openEnded')}
                            </span>
                          </div>
                          {canWrite && (
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
                                iconOnly
                                items={[{
                                  key: 'remove',
                                  label: t('pages.meteringPoints.removeAssignment'),
                                  icon: <FontAwesomeIcon icon={faTrash} fixedWidth />,
                                  disabled: deleteAssignmentPending || dialogLoading,
                                  danger: true,
                                  onClick: () => confirmRemoveAssignment(assignment),
                                }]}
                              />
                            </div>
                          )}
                        </li>
                      )
                    })}
                  </ul>
                )}
              </section>
            )}

            <section className="metering-detail-card">
              <header><h4>{t('pages.meteringPoints.detail.measurement')}</h4></header>
              <dl className="metering-detail-facts">
                <div>
                  <dt>{t('pages.meteringPoints.detail.lastReading')}</dt>
                  <dd>{point.last_reading_at ? formatDateTime(point.last_reading_at, settings) : t('pages.meteringPoints.neverReceivedData')}</dd>
                </div>
                {point.first_reading_at && (
                  <div>
                    <dt>{t('pages.meteringPoints.detail.firstReading')}</dt>
                    <dd>{formatDateTime(point.first_reading_at, settings)}</dd>
                  </div>
                )}
                <div>
                  <dt>{t('pages.meteringPoints.detail.readings')}</dt>
                  <dd>{formatNumber(point.reading_count, { maxDecimals: 0 })}</dd>
                </div>
                <div>
                  <dt>{t('pages.meteringPoints.detail.dataQuality')}</dt>
                  <dd>
                    <Link
                      className={meteringPointHealthBadgeClass(health)}
                      style={{ textDecoration: 'none' }}
                      to={`/metering-data?metering_point=${point.id}&tab=quality`}
                      title={t('pages.meteringPoints.health.linkHint')}
                    >
                      {t(`pages.meteringPoints.health.${health}`)}
                    </Link>
                  </dd>
                </div>
              </dl>
              {isManagedScope && !sourceNeedsAttention && (
                <div className="metering-detail-source">
                  <SupplementarySourceStatus point={point} canManage={!readOnly} confirm={confirm} />
                </div>
              )}
            </section>
          </div>
          {canWrite && (
            <div className="metering-detail-actions actions-row actions-row-wrap">
              <button type="button" className="button button-secondary button-compact" onClick={() => onOpenEditMeteringPoint(point)}>
                <FontAwesomeIcon icon={faPen} fixedWidth />
                {t('pages.meteringPoints.detail.editMeteringPoint')}
              </button>
            </div>
          )}
        </div>
      )}
    </article>
  )
}
