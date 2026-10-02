import { faPlus } from '@fortawesome/free-solid-svg-icons'
import { EmptyState } from '../../components/EmptyState'

type TariffEmptyStateProps = {
  onOpenCreateTariffModal: () => void
  /** A viewer reads only (#761): no create action. */
  readOnly?: boolean
}

export function TariffEmptyState({ onOpenCreateTariffModal, readOnly = false }: TariffEmptyStateProps) {
  return (
    <EmptyState
      titleKey="pages.tariffs.noTariffs"
      descriptionKey="pages.tariffs.description"
      actions={readOnly ? [] : [
        {
          labelKey: 'pages.tariffs.newTariff',
          onClick: onOpenCreateTariffModal,
          variant: 'primary',
          icon: faPlus,
        },
      ]}
    />
  )
}
