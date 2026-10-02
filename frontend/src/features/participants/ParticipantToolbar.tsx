import { FontAwesomeIcon } from '@fortawesome/react-fontawesome'
import { faPlus } from '@fortawesome/free-solid-svg-icons'
import { useTranslation } from 'react-i18next'

export type ParticipantReadinessFilter = 'all' | 'attention' | 'ready'

type ParticipantToolbarProps = {
  totalCount: number
  warningCount: number
  noMeteringCount: number
  searchTerm: string
  readinessFilter: ParticipantReadinessFilter
  onSearchTermChange: (value: string) => void
  onReadinessFilterChange: (value: ParticipantReadinessFilter) => void
  onOpenCreateModal: () => void
  /** A viewer reads only (#761): no "New participant". */
  readOnly?: boolean
}

export function ParticipantToolbar({
  totalCount,
  warningCount,
  noMeteringCount,
  searchTerm,
  readinessFilter,
  onSearchTermChange,
  onReadinessFilterChange,
  onOpenCreateModal,
  readOnly = false,
}: ParticipantToolbarProps) {
  const { t } = useTranslation()

  return (
    <section className="card participant-toolbar">
      <div className="participant-toolbar-header">
        <div className="participant-summary" aria-label={t('pages.participants.summaryLabel')}>
          <span className="participant-summary-stat">
            <span className="participant-summary-label">{t('pages.participants.summary.total')}</span>
            <span className="participant-summary-value">{totalCount}</span>
          </span>
          <span className="participant-summary-stat">
            <span className="participant-summary-label">{t('pages.participants.summary.attention')}</span>
            <span className="participant-summary-value">{warningCount}</span>
          </span>
          <span className="participant-summary-stat">
            <span className="participant-summary-label">{t('pages.participants.summary.noMetering')}</span>
            <span className="participant-summary-value">{noMeteringCount}</span>
          </span>
        </div>

        {!readOnly && (
          <button className="button button-primary" type="button" onClick={onOpenCreateModal}>
            <FontAwesomeIcon icon={faPlus} fixedWidth />
            {t('pages.participants.newParticipant')}
          </button>
        )}
      </div>

      <div className="participant-filter-grid">
        <label>
          <span>{t('pages.participants.filters.search')}</span>
          <input
            value={searchTerm}
            onChange={(event) => onSearchTermChange(event.target.value)}
            placeholder={t('pages.participants.filters.searchPlaceholder')}
          />
        </label>
        <label>
          <span>{t('pages.participants.filters.readiness')}</span>
          <select value={readinessFilter} onChange={(event) => onReadinessFilterChange(event.target.value as ParticipantReadinessFilter)}>
            <option value="all">{t('pages.participants.filters.all')}</option>
            <option value="attention">{t('pages.participants.filters.attention')}</option>
            <option value="ready">{t('pages.participants.filters.ready')}</option>
          </select>
        </label>
      </div>
    </section>
  )
}
