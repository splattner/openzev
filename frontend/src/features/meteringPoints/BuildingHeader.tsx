import { FontAwesomeIcon } from '@fortawesome/react-fontawesome'
import { faPen, faPlus, faTrash } from '@fortawesome/free-solid-svg-icons'
import { useTranslation } from 'react-i18next'
import type { Building } from '../../types/api'

type BuildingHeaderProps = {
  building: Building
  /** Names of the landowners whose role names this building, active today. */
  landowners: string[]
  /** `line`: the compact line above the list of a one-building ZEV; `group`: the header of a building's group. */
  variant: 'line' | 'group'
  /** Managers only: edit (and, in a group, delete and add a metering point). */
  canManage: boolean
  deletePending?: boolean
  onEdit: (building: Building) => void
  onDelete?: (building: Building) => void
  onAddMeteringPoint?: (building: Building) => void
}

/** One-line address of a building: street lines, then postal code and city. */
export function buildingAddress(building: Building): string {
  return [building.address_line1, building.address_line2, [building.postal_code, building.city].filter(Boolean).join(' ')]
    .filter((part) => part.trim())
    .join(', ')
}

/**
 * The building a group of metering points is in (#890, ADR 0029): name,
 * address, EGID, landowners and how many meters it holds.
 */
export function BuildingHeader({
  building,
  landowners,
  variant,
  canManage,
  deletePending = false,
  onEdit,
  onDelete,
  onAddMeteringPoint,
}: BuildingHeaderProps) {
  const { t } = useTranslation()
  const address = buildingAddress(building)
  const hasMeters = building.metering_point_count > 0
  const isGroup = variant === 'group'

  return (
    <div className={`building-header building-header-${variant}`}>
      <div className="building-header-main">
        <strong className="building-header-name">{building.name}</strong>
        <span className="building-header-meta muted">
          {address && <span>{address}</span>}
          {building.egid !== null && <span>{t('pages.meteringPoints.buildings.egidBadge', { egid: building.egid })}</span>}
          {landowners.length > 0 && <span>{t('pages.meteringPoints.buildings.landowners', { names: landowners.join(', ') })}</span>}
          {isGroup && <span>{t('pages.meteringPoints.buildings.meteringPoints', { count: building.metering_point_count })}</span>}
        </span>
      </div>
      {canManage && (
        <div className="building-header-actions actions-row actions-row-wrap">
          {isGroup && onAddMeteringPoint && (
            <button type="button" className="button button-secondary button-compact" onClick={() => onAddMeteringPoint(building)}>
              <FontAwesomeIcon icon={faPlus} fixedWidth />
              {t('pages.meteringPoints.buildings.addMeteringPoint')}
            </button>
          )}
          <button type="button" className="button button-secondary button-compact" onClick={() => onEdit(building)}>
            <FontAwesomeIcon icon={faPen} fixedWidth />
            {t('common.edit')}
          </button>
          {isGroup && onDelete && (
            <button
              type="button"
              className="button button-danger button-compact"
              disabled={deletePending || hasMeters}
              title={hasMeters ? t('pages.meteringPoints.buildings.deleteBlocked') : undefined}
              onClick={() => onDelete(building)}
            >
              <FontAwesomeIcon icon={faTrash} fixedWidth />
              {t('common.delete')}
            </button>
          )}
        </div>
      )}
    </div>
  )
}
