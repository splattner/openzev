import { FontAwesomeIcon } from '@fortawesome/react-fontawesome'
import { faPlus } from '@fortawesome/free-solid-svg-icons'
import { useTranslation } from 'react-i18next'
import { METER_TYPE_OPTIONS } from '../../lib/options'
import type {
  MeteringPointAssignmentFilter,
  MeteringPointAttentionFilter,
  MeteringPointStatusFilter,
  MeteringPointTypeFilter,
} from './useMeteringPointForms'

type MeteringPointsToolbarProps = {
  canManageMeteringPoints: boolean
  totalCount: number
  activeCount: number
  inactiveCount: number
  assignedCount: number
  needsAttentionCount: number
  searchTerm: string
  statusFilter: MeteringPointStatusFilter
  typeFilter: MeteringPointTypeFilter
  attentionFilter: MeteringPointAttentionFilter
  assignmentFilter: MeteringPointAssignmentFilter
  onChangeSearchTerm: (value: string) => void
  onChangeStatusFilter: (value: MeteringPointStatusFilter) => void
  onChangeTypeFilter: (value: MeteringPointTypeFilter) => void
  onChangeAttentionFilter: (value: MeteringPointAttentionFilter) => void
  onChangeAssignmentFilter: (value: MeteringPointAssignmentFilter) => void
  onClearFilters: () => void
  onOpenCreateModal: () => void
}

export function MeteringPointsToolbar({
  canManageMeteringPoints,
  totalCount,
  activeCount,
  inactiveCount,
  assignedCount,
  needsAttentionCount,
  searchTerm,
  statusFilter,
  typeFilter,
  attentionFilter,
  assignmentFilter,
  onChangeSearchTerm,
  onChangeStatusFilter,
  onChangeTypeFilter,
  onChangeAttentionFilter,
  onChangeAssignmentFilter,
  onClearFilters,
  onOpenCreateModal,
}: MeteringPointsToolbarProps) {
  const { t } = useTranslation()

  return (
    <section className="card metering-toolbar">
      <div className="metering-toolbar-header">
        {/* Each chip both reports a count and toggles the matching filter — clicking an
            already-active chip clears just that dimension, so this doubles as "Clear filters"
            when Total is clicked (every dimension reset at once). */}
        <div className="metering-summary" aria-label={t('pages.meteringPoints.summaryLabel')}>
          <button type="button" className="metering-summary-stat" onClick={onClearFilters}>
            <span className="metering-summary-label">{t('pages.meteringPoints.summary.total')}</span>
            <span className="metering-summary-value">{totalCount}</span>
          </button>
          <button
            type="button"
            className={`metering-summary-stat${statusFilter === 'active' ? ' is-active' : ''}`}
            onClick={() => onChangeStatusFilter(statusFilter === 'active' ? 'all' : 'active')}
          >
            <span className="metering-summary-label">{t('pages.meteringPoints.summary.active')}</span>
            <span className="metering-summary-value">{activeCount}</span>
          </button>
          <button
            type="button"
            className={`metering-summary-stat${statusFilter === 'inactive' ? ' is-active' : ''}`}
            onClick={() => onChangeStatusFilter(statusFilter === 'inactive' ? 'all' : 'inactive')}
          >
            <span className="metering-summary-label">{t('pages.meteringPoints.summary.inactive')}</span>
            <span className="metering-summary-value">{inactiveCount}</span>
          </button>
          {canManageMeteringPoints && (
            <>
              <button
                type="button"
                className={`metering-summary-stat${assignmentFilter === 'assigned' ? ' is-active' : ''}`}
                onClick={() => onChangeAssignmentFilter(assignmentFilter === 'assigned' ? 'all' : 'assigned')}
              >
                <span className="metering-summary-label">{t('pages.meteringPoints.summary.assigned')}</span>
                <span className="metering-summary-value">{assignedCount}</span>
              </button>
              <button
                type="button"
                className={`metering-summary-stat${assignmentFilter === 'unassigned' ? ' is-active' : ''}`}
                onClick={() => onChangeAssignmentFilter(assignmentFilter === 'unassigned' ? 'all' : 'unassigned')}
              >
                <span className="metering-summary-label">{t('pages.meteringPoints.summary.unassigned')}</span>
                <span className="metering-summary-value">{totalCount - assignedCount}</span>
              </button>
            </>
          )}
          <button
            type="button"
            className={`metering-summary-stat${attentionFilter === 'attention' ? ' is-active' : ''}`}
            onClick={() => onChangeAttentionFilter(attentionFilter === 'attention' ? 'all' : 'attention')}
          >
            <span className="metering-summary-label">{t('pages.meteringPoints.summary.needsAttention')}</span>
            <span className="metering-summary-value">{needsAttentionCount}</span>
          </button>
        </div>

        {canManageMeteringPoints && (
          <button className="button button-primary" type="button" onClick={onOpenCreateModal}>
            <FontAwesomeIcon icon={faPlus} fixedWidth />
            {t('pages.meteringPoints.newMeteringPoint')}
          </button>
        )}
      </div>

      <div className="metering-filter-grid">
        <label>
          <span>{t('pages.meteringPoints.filters.search')}</span>
          <input
            value={searchTerm}
            onChange={(event) => onChangeSearchTerm(event.target.value)}
            placeholder={t('pages.meteringPoints.filters.searchPlaceholder')}
          />
        </label>
        <label>
          <span>{t('pages.meteringPoints.filters.status')}</span>
          <select value={statusFilter} onChange={(event) => onChangeStatusFilter(event.target.value as MeteringPointStatusFilter)}>
            <option value="all">{t('pages.meteringPoints.filters.allStatuses')}</option>
            <option value="active">{t('pages.meteringPoints.active')}</option>
            <option value="inactive">{t('pages.meteringPoints.inactive')}</option>
          </select>
        </label>
        <label>
          <span>{t('pages.meteringPoints.filters.type')}</span>
          <select value={typeFilter} onChange={(event) => onChangeTypeFilter(event.target.value as MeteringPointTypeFilter)}>
            <option value="all">{t('pages.meteringPoints.filters.allTypes')}</option>
            {METER_TYPE_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>
                {t(option.labelKey)}
              </option>
            ))}
          </select>
        </label>
        <label>
          <span>{t('pages.meteringPoints.filters.attention')}</span>
          <select value={attentionFilter} onChange={(event) => onChangeAttentionFilter(event.target.value as MeteringPointAttentionFilter)}>
            <option value="all">{t('pages.meteringPoints.filters.allAttention')}</option>
            <option value="attention">{t('pages.meteringPoints.filters.needsAttention')}</option>
          </select>
        </label>
      </div>
    </section>
  )
}
