import { FontAwesomeIcon } from '@fortawesome/react-fontawesome'
import { faBuilding, faChevronDown, faEllipsis, faPen, faPlus, faTrash } from '@fortawesome/free-solid-svg-icons'
import { useTranslation } from 'react-i18next'
import { ActionMenu, type ActionMenuItem } from '../../components/ActionMenu'
import type { Building } from '../../types/api'
import { MeteringPointStatusDot } from './MeteringPointStatusDot'
import type { MeteringPointStatus } from './useMeteringPointForms'

type BuildingHeaderProps = {
  building: Building
  /** Names of the landowners whose role names this building, active today. */
  landowners: string[]
  /** `line`: the compact line above the list of a one-building ZEV; `group`: the header of a building's group. */
  variant: 'line' | 'group'
  /** Managers only: edit (and, in a group, delete and add a metering point). */
  canManage: boolean
  /** Group only: how many of the building's meters are in each status, for the roll-up. */
  statusCounts?: Record<MeteringPointStatus, number>
  /** Group only: whether the meters are folded away; the header is the toggle, unless `onToggleCollapsed` is absent. */
  collapsed?: boolean
  onToggleCollapsed?: () => void
  /** Group only: the id of the element holding the meters, for `aria-controls`. */
  panelId?: string
  deletePending?: boolean
  onEdit: (building: Building) => void
  onDelete?: (building: Building) => void
  onAddMeteringPoint?: (building: Building) => void
}

/** One-line address of a building: street lines, then postal code and city. */
function buildingAddress(building: Building): string {
  return [building.address_line1, building.address_line2, [building.postal_code, building.city].filter(Boolean).join(' ')]
    .filter((part) => part.trim())
    .join(', ')
}

/** The statuses worth a number in the header, worst first; healthy and inactive meters are not counted. */
const ROLLUP_STATUSES = ['danger', 'warning', 'pending'] as const

/** What is wrong in the building at a glance, so a folded header still says whether to open it. */
function BuildingRollup({ counts }: { counts: Record<MeteringPointStatus, number> }) {
  const { t } = useTranslation()
  const flagged = ROLLUP_STATUSES.filter((status) => counts[status] > 0)
  if (flagged.length === 0) {
    return counts.ok > 0 ? <span className="building-rollup building-rollup-ok">{t('pages.meteringPoints.buildings.rollup.allGood')}</span> : null
  }
  return (
    <span className="building-rollup">
      {flagged.map((status) => {
        const label = t(`pages.meteringPoints.buildings.rollup.${status}`, { count: counts[status] })
        return (
          <span key={status} className="building-rollup-count">
            <MeteringPointStatusDot status={status} />
            {label}
          </span>
        )
      })}
    </span>
  )
}

/**
 * The building a group of metering points is in (#890, ADR 0029): name,
 * address, EGID, landowners and how many meters it holds. In a group it is
 * also the toggle that folds the meters away, and carries the health roll-up.
 */
export function BuildingHeader({
  building,
  landowners,
  variant,
  canManage,
  statusCounts,
  collapsed = false,
  onToggleCollapsed,
  panelId,
  deletePending = false,
  onEdit,
  onDelete,
  onAddMeteringPoint,
}: BuildingHeaderProps) {
  const { t } = useTranslation()
  const address = buildingAddress(building)
  const hasMeters = building.metering_point_count > 0
  const isGroup = variant === 'group'

  const main = (
    <>
      <strong className="building-header-name">{building.name}</strong>
      <span className="building-header-meta muted">
        {address && <span>{address}</span>}
        {building.egid !== null && <span>{t('pages.meteringPoints.buildings.egidBadge', { egid: building.egid })}</span>}
        {landowners.length > 0 && <span>{t('pages.meteringPoints.buildings.landowners', { names: landowners.join(', ') })}</span>}
        {isGroup && <span>{t('pages.meteringPoints.buildings.meteringPoints', { count: building.metering_point_count })}</span>}
      </span>
    </>
  )

  const menuItems: ActionMenuItem[] = [{
    key: 'edit',
    label: t('pages.meteringPoints.buildings.edit'),
    icon: <FontAwesomeIcon icon={faPen} fixedWidth />,
    onClick: () => onEdit(building),
  }]
  // Rare and destructive: overflow + confirm, and only once nothing is left in it.
  if (isGroup && onDelete && !hasMeters) {
    menuItems.push({
      key: 'delete',
      label: t('pages.meteringPoints.buildings.deleteTitle'),
      icon: <FontAwesomeIcon icon={faTrash} fixedWidth />,
      danger: true,
      disabled: deletePending,
      onClick: () => onDelete(building),
    })
  }

  if (!isGroup) {
    return (
      <div className="building-header building-header-line">
        <div className="building-header-main">{main}</div>
        {canManage && (
          <div className="building-header-actions actions-row actions-row-wrap">
            <button type="button" className="button button-secondary button-compact" onClick={() => onEdit(building)}>
              <FontAwesomeIcon icon={faPen} fixedWidth />
              {t('common.edit')}
            </button>
          </div>
        )}
      </div>
    )
  }

  const toggleContent = (
    <>
      <FontAwesomeIcon icon={faChevronDown} className="building-header-chevron" fixedWidth />
      <span className="building-header-icon" aria-hidden="true">
        <FontAwesomeIcon icon={faBuilding} fixedWidth />
      </span>
      <span className="building-header-main">{main}</span>
    </>
  )

  return (
    <div className={`building-header building-header-group${collapsed ? ' is-collapsed' : ''}`}>
      {onToggleCollapsed ? (
        <button
          type="button"
          className="building-header-toggle"
          aria-expanded={!collapsed}
          aria-controls={panelId}
          onClick={onToggleCollapsed}
        >
          {toggleContent}
        </button>
      ) : (
        <div className="building-header-toggle">{toggleContent}</div>
      )}
      <div className="building-header-side">
        {statusCounts && <BuildingRollup counts={statusCounts} />}
        {canManage && (
          <div className="building-header-actions actions-row">
            {onAddMeteringPoint && (
              <button type="button" className="button button-secondary button-compact" onClick={() => onAddMeteringPoint(building)}>
                <FontAwesomeIcon icon={faPlus} fixedWidth />
                {t('pages.meteringPoints.buildings.addMeteringPoint')}
              </button>
            )}
            <ActionMenu
              label={t('pages.meteringPoints.moreActions')}
              icon={<FontAwesomeIcon icon={faEllipsis} fixedWidth />}
              iconOnly
              items={menuItems}
            />
          </div>
        )}
      </div>
    </div>
  )
}
