import { EmptyState } from '../../components/EmptyState'

export function InvoicesEmptyState() {
  return (
    <EmptyState
      titleKey="pages.invoices.emptyState.title"
      descriptionKey="pages.invoices.emptyState.description"
      actions={[
        { labelKey: 'pages.invoices.emptyState.participantsAction', to: '/participants', variant: 'primary' },
        { labelKey: 'pages.invoices.emptyState.meteringPointsAction', to: '/metering-points', variant: 'secondary' },
        { labelKey: 'pages.invoices.emptyState.tariffsAction', to: '/tariffs', variant: 'secondary' },
      ]}
    />
  )
}
