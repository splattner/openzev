import { FontAwesomeIcon } from '@fortawesome/react-fontawesome'
import { faBuilding, faEllipsis, faPen, faPlus, faTrash } from '@fortawesome/free-solid-svg-icons'
import { useTranslation } from 'react-i18next'
import { ActionMenu, type ActionMenuItem } from '../../components/ActionMenu'
import type { Building } from '../../types/api'

type BuildingHeaderProps = {
  building: Building
  /** Names of the landowners whose role names this building, active today. */
  landowners: string[]
  /** Managers only: add a metering point, edit, and delete an empty building. */
  canManage: boolean
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

/**
 * The building a group of metering points is in (#890, ADR 0029): name,
 * address, EGID, landowners and how many meters it holds.
 * Every building has this header, whether the community has one or several.
 */
export function BuildingHeader({
  building,
  landowners,
  canManage,
  deletePending = false,
  onEdit,
  onDelete,
  onAddMeteringPoint,
}: BuildingHeaderProps) {
  const { t } = useTranslation()
  const address = buildingAddress(building)

  const menuItems: ActionMenuItem[] = []
  // Rare and destructive: overflow + confirm, and only once nothing is left in it.
  if (onDelete && building.metering_point_count === 0) {
    menuItems.push({
      key: 'delete',
      label: t('pages.meteringPoints.buildings.deleteTitle'),
      icon: <FontAwesomeIcon icon={faTrash} fixedWidth />,
      danger: true,
      disabled: deletePending,
      onClick: () => onDelete(building),
    })
  }

  return (
    <div className="building-header">
      <div className="building-header-id">
        <span className="building-header-icon" aria-hidden="true">
          <FontAwesomeIcon icon={faBuilding} fixedWidth />
        </span>
        <div className="building-header-main">
          <h2 id={`metering-building-${building.id}`} className="building-header-name">{building.name}</h2>
          <span className="building-header-meta muted">
            {address && <span>{address}</span>}
            {building.egid !== null && <span>{t('pages.meteringPoints.buildings.egidBadge', { egid: building.egid })}</span>}
            {landowners.length > 0 && <span>{t('pages.meteringPoints.buildings.landowners', { names: landowners.join(', ') })}</span>}
            <span>{t('pages.meteringPoints.buildings.meteringPoints', { count: building.metering_point_count })}</span>
          </span>
        </div>
      </div>
      <div className="building-header-side">
        {canManage && (
          <div className="building-header-actions actions-row actions-row-wrap">
            {onAddMeteringPoint && (
              <button type="button" className="button button-secondary button-compact" onClick={() => onAddMeteringPoint(building)}>
                <FontAwesomeIcon icon={faPlus} fixedWidth />
                {t('pages.meteringPoints.buildings.addMeteringPoint')}
              </button>
            )}
            <button type="button" className="button button-secondary button-compact" onClick={() => onEdit(building)}>
              <FontAwesomeIcon icon={faPen} fixedWidth />
              {t('pages.meteringPoints.buildings.edit')}
            </button>
            {menuItems.length > 0 && <ActionMenu
              label={t('pages.meteringPoints.moreActions')}
              icon={<FontAwesomeIcon icon={faEllipsis} fixedWidth />}
              iconOnly
              items={menuItems}
            />}
          </div>
        )}
      </div>
    </div>
  )
}
