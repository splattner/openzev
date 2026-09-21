import { faPlus } from '@fortawesome/free-solid-svg-icons'
import { useTranslation } from 'react-i18next'
import { DataTable, type ColumnDef, type ColumnFiltersState } from '../../components/DataTable'
import { EmptyState } from '../../components/EmptyState'

interface ImportHistoryTableProps<T> {
    rows: T[]
    columns: ColumnDef<T, unknown>[]
    getRowId: (row: T) => string
    filters: ColumnFiltersState
    onFiltersChange: (filters: ColumnFiltersState) => void
    onNewImport: () => void
}

export function ImportHistoryTable<T>({ rows, columns, getRowId, filters, onFiltersChange, onNewImport }: ImportHistoryTableProps<T>) {
    const { t } = useTranslation()
    const filenameFilter = filters.find((filter) => filter.id === 'filename')?.value as string | undefined ?? ''
    const sourceFilter = filters.find((filter) => filter.id === 'source')?.value as string | undefined ?? ''

    function setFilter(id: string, value: string) {
        const next = filters.filter((filter) => filter.id !== id)
        if (value) next.push({ id, value })
        onFiltersChange(next)
    }

    if (rows.length === 0) {
        return (
            <EmptyState
                titleKey="pages.imports.emptyState.title"
                descriptionKey="pages.imports.emptyState.description"
                actions={[
                    { labelKey: 'pages.imports.emptyState.createAction', onClick: onNewImport, variant: 'primary', icon: faPlus },
                ]}
            />
        )
    }

    return (
        <div className="table-card" style={{ width: '100%' }}>
            <div className="imports-history-filters">
                <input
                    type="search"
                    value={filenameFilter}
                    onChange={(event) => setFilter('filename', event.target.value)}
                    placeholder={t('pages.imports.history.searchFilename')}
                    aria-label={t('pages.imports.history.searchFilename')}
                />
                <select
                    value={sourceFilter}
                    onChange={(event) => setFilter('source', event.target.value)}
                    aria-label={t('pages.imports.history.filterSource')}
                >
                    <option value="">{t('pages.imports.history.allSources')}</option>
                    <option value="csv">{t('pages.imports.format.csv')}</option>
                    <option value="sdatch">{t('pages.imports.format.sdatch')}</option>
                </select>
            </div>
            <DataTable
                data={rows}
                columns={columns}
                getRowId={getRowId}
                initialSorting={[{ id: 'created_at', desc: true }]}
                columnFilters={filters}
                onColumnFiltersChange={onFiltersChange}
                initialPageSize={25}
                emptyMessage={t('pages.imports.noRows')}
            />
        </div>
    )
}
