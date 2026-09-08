import { FontAwesomeIcon } from '@fortawesome/react-fontawesome'
import { faPlus } from '@fortawesome/free-solid-svg-icons'
import { useTranslation } from 'react-i18next'
import type { MeteringPointStatusFilter, MeteringPointTypeFilter } from './useMeteringPointForms'

type MeteringPointsToolbarProps = {
  canManageMeteringPoints: boolean
  totalCount: number
  activeCount: number
  inactiveCount: number
  assignedCount: number
  searchTerm: string
  statusFilter: MeteringPointStatusFilter
  typeFilter: MeteringPointTypeFilter
  onChangeSearchTerm: (value: string) => void
  onChangeStatusFilter: (value: MeteringPointStatusFilter) => void
  onChangeTypeFilter: (value: MeteringPointTypeFilter) => void
  onOpenCreateModal: () => void
}

export function MeteringPointsToolbar({
  canManageMeteringPoints,
  totalCount,
  activeCount,
  inactiveCount,
  assignedCount,
  searchTerm,
  statusFilter,
  typeFilter,
  onChangeSearchTerm,
  onChangeStatusFilter,
  onChangeTypeFilter,
  onOpenCreateModal,
}: MeteringPointsToolbarProps) {
  const { t } = useTranslation()

  return (
    <section className="card metering-toolbar">
      <div className="metering-toolbar-header">
        <div className="metering-summary" aria-label={t('pages.meteringPoints.summaryLabel')}>
          <span className="metering-summary-stat">
            <span className="metering-summary-label">{t('pages.meteringPoints.summary.total')}</span>
            <span className="metering-summary-value">{totalCount}</span>
          </span>
          <span className="metering-summary-stat">
            <span className="metering-summary-label">{t('pages.meteringPoints.summary.active')}</span>
            <span className="metering-summary-value">{activeCount}</span>
          </span>
          <span className="metering-summary-stat">
            <span className="metering-summary-label">{t('pages.meteringPoints.summary.inactive')}</span>
            <span className="metering-summary-value">{inactiveCount}</span>
          </span>
          {canManageMeteringPoints && (
            <>
              <span className="metering-summary-stat">
                <span className="metering-summary-label">{t('pages.meteringPoints.summary.assigned')}</span>
                <span className="metering-summary-value">{assignedCount}</span>
              </span>
              <span className="metering-summary-stat">
                <span className="metering-summary-label">{t('pages.meteringPoints.summary.unassigned')}</span>
                <span className="metering-summary-value">{totalCount - assignedCount}</span>
              </span>
            </>
          )}
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
            <option value="consumption">{t('pages.meteringPoints.meterTypes.consumption')}</option>
            <option value="production">{t('pages.meteringPoints.meterTypes.production')}</option>
            <option value="bidirectional">{t('pages.meteringPoints.meterTypes.bidirectional')}</option>
          </select>
        </label>
      </div>
    </section>
  )
}
