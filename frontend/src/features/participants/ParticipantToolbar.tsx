import { FontAwesomeIcon } from '@fortawesome/react-fontawesome'
import { faPlus } from '@fortawesome/free-solid-svg-icons'
import { useTranslation } from 'react-i18next'
import { FilterTabs } from '../../components/FilterTabs'
import { Toolbar } from '../../components/Toolbar'

export type ParticipantReadinessFilter = 'all' | 'attention' | 'noMetering'

type ParticipantToolbarProps = {
  totalCount: number
  warningCount: number
  noMeteringCount: number
  searchTerm: string
  readinessFilter: ParticipantReadinessFilter
  onSearchTermChange: (value: string) => void
  onReadinessFilterChange: (value: ParticipantReadinessFilter) => void
  onOpenCreateModal: () => void
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
      <Toolbar
        actions={!readOnly ? (
          <button className="button button-primary" type="button" onClick={onOpenCreateModal}>
            <FontAwesomeIcon icon={faPlus} fixedWidth />
            {t('pages.participants.newParticipant')}
          </button>
        ) : null}
      >
        <div className="list-filters">
          <FilterTabs
            label={t('pages.participants.summaryLabel')}
            tabs={[
              { value: 'all', label: t('pages.participants.summary.total'), count: totalCount },
              { value: 'attention', label: t('pages.participants.summary.attention'), count: warningCount, attention: true },
              { value: 'noMetering', label: t('pages.participants.summary.noMetering'), count: noMeteringCount },
            ]}
            value={readinessFilter}
            onChange={onReadinessFilterChange}
          />
          {/* Nothing else narrows participants, so the search shares the row. */}
          <input
            value={searchTerm}
            onChange={(event) => onSearchTermChange(event.target.value)}
            placeholder={t('pages.participants.filters.searchPlaceholder')}
            aria-label={t('pages.participants.filters.search')}
          />
        </div>
      </Toolbar>
    </section>
  )
}
