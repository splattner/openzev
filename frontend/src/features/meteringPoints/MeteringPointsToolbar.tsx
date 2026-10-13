import { FontAwesomeIcon } from '@fortawesome/react-fontawesome'
import { faBuilding, faPlus } from '@fortawesome/free-solid-svg-icons'
import { useTranslation } from 'react-i18next'
import { FilterTabs, type FilterTab } from '../../components/FilterTabs'
import { Toolbar } from '../../components/Toolbar'
import { METER_TYPE_OPTIONS } from '../../lib/options'
import type { Building, MeteringPoint } from '../../types/api'
import type {
  MeteringPointBuildingFilter,
  MeteringPointSort,
  MeteringPointTypeFilter,
  MeteringPointView,
} from './useMeteringPointForms'

type MeteringPointsToolbarProps = {
  isManagedScope: boolean
  readOnly?: boolean
  totalCount: number
  activeCount: number
  inactiveCount: number
  unassignedCount: number
  needsAttentionCount: number
  searchTerm: string
  view: MeteringPointView
  sort: MeteringPointSort
  typeFilter: MeteringPointTypeFilter
  /** Metering points per type, across the whole list. */
  typeCounts: Partial<Record<MeteringPoint['meter_type'], number>>
  /** The ZEV's buildings; the filter shows only when there is more than one (#890). */
  buildings?: Building[]
  buildingFilter?: MeteringPointBuildingFilter
  onChangeBuildingFilter?: (value: MeteringPointBuildingFilter) => void
  onChangeSearchTerm: (value: string) => void
  onChangeView: (value: MeteringPointView) => void
  onChangeSort: (value: MeteringPointSort) => void
  onChangeTypeFilter: (value: MeteringPointTypeFilter) => void
  onOpenCreateModal: () => void
  /** Managers: add a building (secondary action next to adding a metering point). */
  onOpenCreateBuildingModal?: () => void
}

const SORT_OPTIONS: Array<{ value: MeteringPointSort; labelKey: string }> = [
  { value: 'meter_id', labelKey: 'pages.meteringPoints.sort.meterId' },
  { value: 'location', labelKey: 'pages.meteringPoints.sort.location' },
  { value: 'last_reading', labelKey: 'pages.meteringPoints.sort.lastReading' },
]

export function MeteringPointsToolbar({
  isManagedScope,
  readOnly = false,
  totalCount,
  activeCount,
  inactiveCount,
  unassignedCount,
  needsAttentionCount,
  searchTerm,
  view,
  sort,
  typeFilter,
  typeCounts,
  buildings = [],
  buildingFilter = 'all',
  onChangeBuildingFilter,
  onChangeSearchTerm,
  onChangeView,
  onChangeSort,
  onChangeTypeFilter,
  onOpenCreateModal,
  onOpenCreateBuildingModal,
}: MeteringPointsToolbarProps) {
  const { t } = useTranslation()
  // Assignments are a manager's concern: participants only see their own meters.
  const tabs: Array<FilterTab<MeteringPointView>> = [
    { value: 'all', label: t('pages.meteringPoints.summary.total'), count: totalCount },
    { value: 'active', label: t('pages.meteringPoints.summary.active'), count: activeCount },
    { value: 'inactive', label: t('pages.meteringPoints.summary.inactive'), count: inactiveCount },
    { value: 'attention', label: t('pages.meteringPoints.summary.attention'), count: needsAttentionCount, attention: true },
    ...(isManagedScope
      ? [{ value: 'unassigned' as const, label: t('pages.meteringPoints.summary.unassigned'), count: unassignedCount }]
      : []),
  ]
  const typeTabs: Array<FilterTab<MeteringPointTypeFilter>> = [
    { value: 'all', label: t('pages.meteringPoints.filters.allTypes'), count: totalCount },
    ...METER_TYPE_OPTIONS.map((option) => ({ value: option.value, label: t(option.labelKey), count: typeCounts[option.value] ?? 0 })),
  ]
  // A list of one type has nothing to narrow by type.
  const showTypeTabs = typeFilter !== 'all' || typeTabs.filter((tab) => tab.value !== 'all' && tab.count > 0).length > 1

  return (
    <section className="card metering-toolbar">
      <Toolbar
        actions={
          isManagedScope && !readOnly ? (
            <div className="actions-row actions-row-wrap">
              {onOpenCreateBuildingModal && (
                <button className="button button-secondary" type="button" onClick={onOpenCreateBuildingModal}>
                  <FontAwesomeIcon icon={faBuilding} fixedWidth />
                  {t('pages.meteringPoints.buildings.add')}
                </button>
              )}
              <button className="button button-primary" type="button" onClick={onOpenCreateModal}>
                <FontAwesomeIcon icon={faPlus} fixedWidth />
                {t('pages.meteringPoints.newMeteringPoint')}
              </button>
            </div>
          ) : null
        }
      >
        <FilterTabs label={t('pages.meteringPoints.summaryLabel')} tabs={tabs} value={view} onChange={onChangeView} />
      </Toolbar>

      <div className="list-filters">
        <input
          value={searchTerm}
          onChange={(event) => onChangeSearchTerm(event.target.value)}
          placeholder={t('pages.meteringPoints.filters.searchPlaceholder')}
          aria-label={t('pages.meteringPoints.filters.search')}
        />
        {showTypeTabs && (
          <FilterTabs label={t('pages.meteringPoints.filters.type')} tabs={typeTabs} value={typeFilter} onChange={onChangeTypeFilter} />
        )}
        {totalCount > 1 && (
          <select
            value={sort}
            onChange={(event) => onChangeSort(event.target.value as MeteringPointSort)}
            aria-label={t('pages.meteringPoints.sort.label')}
          >
            {SORT_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>{t(option.labelKey)}</option>
            ))}
          </select>
        )}
        {buildings.length > 1 && onChangeBuildingFilter && (
          <select
            value={buildingFilter}
            onChange={(event) => onChangeBuildingFilter(event.target.value)}
            aria-label={t('pages.meteringPoints.filters.building')}
          >
            <option value="all">{t('pages.meteringPoints.filters.allBuildings')}</option>
            {buildings.map((building) => (
              <option key={building.id} value={building.id}>{building.name}</option>
            ))}
          </select>
        )}
      </div>
    </section>
  )
}
