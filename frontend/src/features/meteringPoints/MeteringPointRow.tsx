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
  meteringPointNeedsAttention,
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
  assignmentsAvailable: boolean
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
 * what is unusual about the meter itself; named issues appear in their relevant columns.
 */
export function MeteringPointRow({
  point,
  assignments,
  participantNameById,
  settings,
  todayIso,
  health,
  holderLess,
  assignmentsAvailable,
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
  const actionsId = `metering-point-actions-${point.id}`
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
  const lastReadingDate = point.last_reading_at ? formatShortDate(formatBusinessIsoDate(new Date(point.last_reading_at)), settings) : null
  // A source in trouble is worth a badge on the row; a healthy or pending one sits in the details.
  const sourceTone = statusTone(point.supplementary_source_status)
  const sourceNeedsAttention = sourceTone === 'warning' || sourceTone === 'danger'
  const needsAttention = meteringPointNeedsAttention(point, health, holderLess)
  const showDataIssue = needsAttention && health !== 'green' && health !== 'unknown'
  const dataIssueLabel = t(health === 'no_data' ? 'pages.meteringPoints.health.noReadings' : `pages.meteringPoints.health.${health}`)

  function confirmRemoveAssignment(assignment: MeteringPointAssignment) {
    confirm({
      title: t('pages.meteringPoints.removeAssignTitle'),
      message: t('pages.meteringPoints.removeAssignMessage', {
        name: nameOf(assignment),
        meterId: point.meter_id,
        from: formatShortDate(assignment.valid_from, settings),
        to: assignment.valid_to ? formatShortDate(assignment.valid_to, settings) : t('pages.meteringPoints.openEnded'),
      }),
      confirmText: t('pages.meteringPoints.removeAssignConfirm'),
      isDangerous: true,
      onConfirm: () => onDeleteAssignment(assignment.id),
    })
  }

  function handleEditPoint() {
    // Restore to the menu trigger, since its item disappears when the editor opens.
    document.getElementById(actionsId)?.querySelector<HTMLButtonElement>('[aria-haspopup="menu"]')?.focus()
    onOpenEditMeteringPoint(point)
  }

  function handleEditCurrentAssignment() {
    document.getElementById(actionsId)?.querySelector<HTMLButtonElement>('[aria-haspopup="menu"]')?.focus()
    onOpenEditAssignment(current[0])
  }

  const assignmentSection = current.length ? t('pages.meteringPoints.columns.holder') : undefined
  const pointSection = current.length ? t('pages.meteringPoints.columns.meter') : undefined
  const pointMenuItems: ActionMenuItem[] = []
  if (canWrite) {
    if (assignmentsAvailable) pointMenuItems.push({
      key: 'assign',
      section: assignmentSection,
      label: t('pages.meteringPoints.assign'),
      icon: <FontAwesomeIcon icon={faUserPlus} fixedWidth />,
      onClick: () => onOpenCreateAssignModal(point.id),
    })
    if (assignmentsAvailable && current.length === 1) {
      pointMenuItems.push({
        key: 'edit-assignment',
        label: t('pages.meteringPoints.editAssignTitle'),
        section: assignmentSection,
        icon: <FontAwesomeIcon icon={faPen} fixedWidth />,
        onClick: handleEditCurrentAssignment,
      }, {
        key: 'remove-assignment',
        label: t('pages.meteringPoints.removeAssignTitle'),
        section: assignmentSection,
        icon: <FontAwesomeIcon icon={faTrash} fixedWidth />,
        danger: true,
        disabled: deleteAssignmentPending || dialogLoading,
        onClick: () => confirmRemoveAssignment(current[0]),
      })
    }
    pointMenuItems.push({
      key: 'edit',
      section: pointSection,
      label: t('common.edit'),
      icon: <FontAwesomeIcon icon={faPen} fixedWidth />,
      onClick: handleEditPoint,
    })
    if (canDeleteData) {
      pointMenuItems.push({
        key: 'delete-data',
        section: pointSection,
        label: t('pages.meteringPoints.deleteData.button'),
        icon: <FontAwesomeIcon icon={faDatabase} fixedWidth />,
        onClick: () => onOpenDeleteDataModal(point),
      })
    }
    pointMenuItems.push({
      key: 'delete',
      section: pointSection,
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
  function handleRowClick(event: MouseEvent<HTMLTableRowElement>) {
    const target = event.target as HTMLElement
    if (!event.currentTarget.contains(target) || target.closest('a, button, input, select, [role="menu"]')) return
    if (window.getSelection()?.toString()) return
    onToggle()
  }

  function renderHolder() {
    if (!assignmentsAvailable) return <span className="muted">{t('pages.meteringPoints.assignmentsUnavailable')}</span>
    if (current.length > 0) {
      return (
        <>
          <strong className="metering-holder-name">
            {nameOf(current[0])}
          </strong>
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
    <tbody role="rowgroup" className={`metering-point-card${expanded ? ' is-expanded' : ''}`}>
      <tr role="row" className="metering-point-row" onClick={handleRowClick}>
        <td role="cell" className="metering-point-title">
          <div className="metering-point-id">
            <span className="metering-point-id-main">
              <span className="metering-point-type" role="img" aria-label={typeLabel} title={typeLabel}>
                <FontAwesomeIcon icon={METER_TYPE_ICON[point.meter_type]} fixedWidth />
              </span>
              <strong>{point.meter_id}</strong>
            </span>
            {!point.is_active && <span className="badge badge-neutral">{t('pages.meteringPoints.inactive')}</span>}
            {point.has_behind_meter_generation && <BehindMeterBadge />}
            {isManagedScope && sourceNeedsAttention && (
              <SupplementarySourceStatus point={point} canManage={!readOnly} confirm={confirm} />
            )}
          </div>
          {location && <span className="muted metering-point-subtitle">{location}</span>}
        </td>
        {isManagedScope && (
          <td role="cell" className="metering-point-holder">
            {needsAttention && holderLess && (
              <span className="badge badge-danger metering-holder-issue" title={t('pages.meteringPoints.holderLessHint')}>
                <FontAwesomeIcon icon={faTriangleExclamation} fixedWidth />
                {t('pages.meteringPoints.holderLessBadge')}
              </span>
            )}
            {renderHolder()}
          </td>
        )}
        <td role="cell" className="metering-point-last muted">
          {!(showDataIssue && health === 'no_data') && <span>{lastReadingDate ?? t('pages.meteringPoints.never')}</span>}
          {showDataIssue && (
            <Link
              className={`badge ${health === 'red' ? 'badge-danger' : 'badge-warning'} metering-quality-issue`}
              to={`/metering-data?metering_point=${point.id}&tab=quality`}
              aria-label={t('pages.meteringPoints.health.issueFor', { meterId: point.meter_id, status: dataIssueLabel })}
              title={t('pages.meteringPoints.health.linkHint')}
            >
              {dataIssueLabel}
            </Link>
          )}
        </td>
        <td id={actionsId} role="cell" className="metering-point-actions">
          <Link
            className="button button-ghost button-compact"
            to={`/metering/chart?metering_point=${point.id}`}
            aria-label={t('pages.meteringPoints.chartFor', { meterId: point.meter_id })}
            title={t('pages.meteringPoints.chartFor', { meterId: point.meter_id })}
          >
            <FontAwesomeIcon icon={faChartLine} fixedWidth />
          </Link>
          {canWrite && (
            <ActionMenu
              label={t('pages.meteringPoints.moreActionsFor', { meterId: point.meter_id })}
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
        </td>
      </tr>

      {expanded && (
        <tr className="metering-point-detail-row" role="row">
          <td role="cell" colSpan={isManagedScope ? 4 : 3} className="metering-point-detail" id={detailId}>
          <div className={`metering-detail-grid${isManagedScope ? ' metering-detail-grid-participants' : ''}`}>
            {isManagedScope && (
              <section className="metering-detail-card metering-detail-participants">
                <header>
                  <h4>{t('pages.meteringPoints.detail.participants')}</h4>
                  {canWrite && assignmentsAvailable && (
                    <button type="button" className="button button-ghost button-compact" onClick={() => onOpenCreateAssignModal(point.id)}>
                      <FontAwesomeIcon icon={faPlus} fixedWidth />
                      {t('pages.meteringPoints.detail.addAssignment')}
                    </button>
                  )}
                </header>
                {sortedAssignments.length === 0 ? (
                  <p className="muted metering-no-assignments">{t(assignmentsAvailable ? 'pages.meteringPoints.noAssignments' : 'pages.meteringPoints.assignmentsUnavailable')}</p>
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
                          {canWrite && assignmentsAvailable && (
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
                                aria-label={t('pages.meteringPoints.removeAssignmentFor', { name: nameOf(assignment) })}
                                disabled={deleteAssignmentPending || dialogLoading}
                                onClick={() => confirmRemoveAssignment(assignment)}
                              >
                                <FontAwesomeIcon icon={faTrash} fixedWidth />
                                {t('pages.meteringPoints.removeAssignment')}
                              </button>
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
          </td>
        </tr>
      )}
    </tbody>
  )
}
