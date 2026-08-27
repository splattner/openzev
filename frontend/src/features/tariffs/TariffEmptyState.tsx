import { faPlus } from '@fortawesome/free-solid-svg-icons'
import { EmptyState } from '../../components/EmptyState'

type TariffEmptyStateProps = {
  onOpenCreateTariffModal: () => void
}

export function TariffEmptyState({ onOpenCreateTariffModal }: TariffEmptyStateProps) {
  return (
    <EmptyState
      titleKey="pages.tariffs.noTariffs"
      descriptionKey="pages.tariffs.description"
      actions={[
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
