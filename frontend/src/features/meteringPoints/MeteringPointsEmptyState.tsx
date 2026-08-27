import { faPlus } from '@fortawesome/free-solid-svg-icons'
import { EmptyState } from '../../components/EmptyState'

type MeteringPointsEmptyStateProps = {
  canManageMeteringPoints: boolean
  hasFilters: boolean
  onOpenCreateModal: () => void
  onClearFilters: () => void
}

export function MeteringPointsEmptyState({
  canManageMeteringPoints,
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
        canManageMeteringPoints
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
