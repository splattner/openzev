import { faPlus } from '@fortawesome/free-solid-svg-icons'
import { EmptyState } from '../../components/EmptyState'

type MeteringPointsEmptyStateProps = {
  canManageMeteringPoints: boolean
  /** A viewer reads only (#761): no create action. */
  readOnly?: boolean
  hasFilters: boolean
  onOpenCreateModal: () => void
  onClearFilters: () => void
}

export function MeteringPointsEmptyState({
  canManageMeteringPoints,
  readOnly = false,
  hasFilters,
  onOpenCreateModal,
  onClearFilters,
}: MeteringPointsEmptyStateProps) {
  if (hasFilters) {
    return (
      <EmptyState
        titleKey="pages.meteringPoints.noResults.title"
        descriptionKey="pages.meteringPoints.noResults.description"
        actions={[{ labelKey: 'pages.meteringPoints.filters.clear', onClick: onClearFilters, variant: 'secondary' }]}
      />
    )
  }

  const participantsAction = {
    labelKey: 'pages.meteringPoints.emptyState.participantsAction' as const,
    to: '/participants' as const,
    variant: 'secondary' as const,
  }

  return (
    <EmptyState
      titleKey="pages.meteringPoints.emptyState.title"
      descriptionKey="pages.meteringPoints.emptyState.description"
      actions={
        canManageMeteringPoints && !readOnly
          ? [
              {
                labelKey: 'pages.meteringPoints.emptyState.createAction' as const,
                onClick: onOpenCreateModal,
                variant: 'primary' as const,
                icon: faPlus,
              },
              participantsAction,
            ]
          : []
      }
    />
  )
}
