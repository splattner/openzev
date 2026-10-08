import { useTranslation } from 'react-i18next'
import { FilterTabs } from '../../components/FilterTabs'
import type { InvoiceRowCounts, InvoiceRowFilter } from './invoiceRowFilters'

type InvoiceRowFilterTabsProps = {
  counts: InvoiceRowCounts
  /** The filter the list currently shows; `null` is the whole period. */
  activeFilter: InvoiceRowFilter
  onFilterChange: (filter: InvoiceRowFilter) => void
}

/** All rows first, then the workflow stages, then the rows needing attention. */
const SEGMENTS: Array<{ filter: InvoiceRowFilter; count: keyof InvoiceRowCounts; labelKey: string }> = [
  { filter: null, count: 'all', labelKey: 'pages.invoices.filters.all' },
  { filter: 'drafts', count: 'drafts', labelKey: 'pages.invoices.filters.drafts' },
  { filter: 'approved', count: 'approved', labelKey: 'pages.invoices.filters.approved' },
  { filter: 'sent', count: 'sent', labelKey: 'pages.invoices.filters.sent' },
  { filter: 'issues', count: 'issues', labelKey: 'pages.invoices.filters.issues' },
]

/** Counts stay period-wide. */
export function InvoiceRowFilterTabs({ counts, activeFilter, onFilterChange }: InvoiceRowFilterTabsProps) {
  const { t } = useTranslation()
  return (
    <FilterTabs
      label={t('pages.invoices.filters.label')}
      tabs={SEGMENTS.map(({ filter, count, labelKey }) => ({
        value: filter,
        label: t(labelKey),
        count: counts[count],
        attention: filter === 'issues',
      }))}
      value={activeFilter}
      onChange={onFilterChange}
    />
  )
}
