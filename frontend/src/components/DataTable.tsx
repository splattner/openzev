import {
    columnFilteringFeature,
    columnSizingFeature,
    columnVisibilityFeature,
    createFilteredRowModel,
    createPaginatedRowModel,
    createSortedRowModel,
    filterFn_equalsString,
    filterFn_includesString,
    flexRender,
    metaHelper,
    rowPaginationFeature,
    rowSortingFeature,
    sortFn_alphanumeric,
    sortFn_basic,
    sortFn_datetime,
    sortFn_text,
    tableFeatures,
    useTable,
    type ColumnDef as TanStackColumnDef,
    type ColumnFiltersState,
    type SortingState,
} from '@tanstack/react-table'
import { useState, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'

const features = tableFeatures({
    columnFilteringFeature,
    columnSizingFeature,
    columnVisibilityFeature,
    rowPaginationFeature,
    rowSortingFeature,
    filteredRowModel: createFilteredRowModel(),
    paginatedRowModel: createPaginatedRowModel(),
    sortedRowModel: createSortedRowModel(),
    // Only the comparators/filters the tables use: `sortFn: 'auto'` resolves
    // among the sort functions, `equalsString` is named by column defs, `includesString` is
    // what `filterFn: 'auto'` picks for a text column.
    sortFns: { alphanumeric: sortFn_alphanumeric, basic: sortFn_basic, datetime: sortFn_datetime, text: sortFn_text },
    filterFns: { equalsString: filterFn_equalsString, includesString: filterFn_includesString },
    columnMeta: metaHelper<{ numeric?: boolean }>(),
})

type Features = typeof features

/** Column definition bound to this table's feature set, so callers keep
 *  writing `ColumnDef<Row, unknown>`. */
export type ColumnDef<TData extends Record<string, any>, TValue = unknown> = TanStackColumnDef<Features, TData, TValue>
export type { ColumnFiltersState }

/** TanStack Table's default column size — used as a sentinel to skip
 *  explicit width when the caller hasn't set one. */
const TANSTACK_DEFAULT_SIZE = 150

/** One fixed page size: long enough that most lists fit on one page, so the
 *  footer offers only prev/next, never a rows-per-page choice. */
const PAGE_SIZE = 100

function preserveHeaderFocus(button: HTMLButtonElement | null) {
    if (!button) return
    return () => {
        if (document.activeElement === button) button.closest('th')?.focus()
    }
}

interface DataTableProps<T extends Record<string, any>> {
    data: T[]
    columns: ColumnDef<T, unknown>[]
    getRowId?: (row: T) => string
    initialSorting?: SortingState
    /** External filter controls (search boxes, selects) set this state. */
    columnFilters?: ColumnFiltersState
    onColumnFiltersChange?: (updater: ColumnFiltersState) => void
    enableSorting?: boolean
    loading?: boolean
    emptyMessage?: ReactNode
    /** Rows per page; a narrow container passes a short page. Read once, on mount. */
    pageSize?: number
}

export function DataTable<T extends Record<string, any>>({
    data,
    columns,
    getRowId,
    initialSorting = [],
    columnFilters,
    onColumnFiltersChange,
    enableSorting = true,
    loading,
    emptyMessage,
    pageSize = PAGE_SIZE,
}: DataTableProps<T>) {
    const { t } = useTranslation()
    const [sorting, setSorting] = useState<SortingState>(initialSorting)
    const [internalFilters, setInternalFilters] = useState<ColumnFiltersState>([])
    const [pagination, setPagination] = useState({ pageIndex: 0, pageSize })

    // TanStack Table returns unmemoizable functions, so React Compiler skips
    // this component — safe, the table state lives in the hook itself.
    const table = useTable({
        features,
        data,
        columns,
        state: {
            sorting,
            pagination,
            columnFilters: columnFilters ?? internalFilters,
        },
        onSortingChange: setSorting,
        onPaginationChange: setPagination,
        onColumnFiltersChange: onColumnFiltersChange
            ? (updater) => {
                const next = typeof updater === 'function' ? updater(columnFilters ?? internalFilters) : updater
                onColumnFiltersChange(next)
            }
            : setInternalFilters,
        manualSorting: !enableSorting,
        getRowId,
    })

    const rows = table.getRowModel().rows
    const filteredRowCount = table.getFilteredRowModel().rows.length
    const showSortControls = enableSorting && filteredRowCount > 1

    return (
        <div className="data-table">
            <div className="table-scroll">
                <table>
                    <thead>
                        {table.getHeaderGroups().map((headerGroup) => (
                            <tr key={headerGroup.id}>
                                {headerGroup.headers.map((header) => {
                                    const canSort = showSortControls && header.column.getCanSort()
                                    const dir = header.column.getIsSorted()
                                    const ariaSort = canSort && header.column.getSortIndex() === 0 && dir
                                        ? (dir === 'asc' ? 'ascending' : 'descending') : undefined
                                    return (
                                        <th key={header.id} tabIndex={-1} aria-sort={ariaSort} style={{ width: header.getSize() !== TANSTACK_DEFAULT_SIZE ? header.getSize() : undefined }}>
                                            {header.isPlaceholder ? null : canSort ? (
                                                <button
                                                    type="button"
                                                    ref={preserveHeaderFocus}
                                                    className="data-table-sort"
                                                    onClick={header.column.getToggleSortingHandler()}
                                                >
                                                    {flexRender(header.column.columnDef.header, header.getContext())}
                                                    <span aria-hidden="true">{dir === 'asc' ? '▲' : dir === 'desc' ? '▼' : ''}</span>
                                                </button>
                                            ) : (
                                                flexRender(header.column.columnDef.header, header.getContext())
                                            )}
                                        </th>
                                    )
                                })}
                            </tr>
                        ))}
                    </thead>
                    <tbody>
                        {loading ? (
                            <tr><td colSpan={columns.length}>{t('common.loading')}</td></tr>
                        ) : rows.length === 0 ? (
                            <tr><td colSpan={columns.length}>{emptyMessage ?? t('common.empty')}</td></tr>
                        ) : (
                            rows.map((row) => (
                                <tr key={row.id}>
                                    {row.getVisibleCells().map((cell) => (
                                        <td key={cell.id} className={cell.column.columnDef.meta?.numeric ? 'numeric' : undefined}>
                                            {flexRender(cell.column.columnDef.cell, cell.getContext())}
                                        </td>
                                    ))}
                                </tr>
                            ))
                        )}
                    </tbody>
                </table>
            </div>
            {/* Footer (range, prev/next) only when data spans more
                than one page — a single-page footer would render permanently
                disabled buttons. */}
            {rows.length > 0 && table.getPageCount() > 1 && (
                <div className="data-table-footer actions-row actions-row-end muted">
                    <span aria-live="polite">
                        {t('common.pagination.range', {
                            from: table.state.pagination.pageIndex * table.state.pagination.pageSize + 1,
                            to: Math.min((table.state.pagination.pageIndex + 1) * table.state.pagination.pageSize, filteredRowCount),
                            total: filteredRowCount,
                        })}
                    </span>
                    <span className="flex-1" />
                    <button
                        className="button button-secondary button-compact"
                        type="button"
                        aria-label={t('common.pagination.previous')}
                        onClick={() => table.previousPage()}
                        disabled={!table.getCanPreviousPage()}
                    >
                        ‹
                    </button>
                    <span>{table.state.pagination.pageIndex + 1} / {Math.max(1, table.getPageCount())}</span>
                    <button
                        className="button button-secondary button-compact"
                        type="button"
                        aria-label={t('common.pagination.next')}
                        onClick={() => table.nextPage()}
                        disabled={!table.getCanNextPage()}
                    >
                        ›
                    </button>
                </div>
            )}
        </div>
    )
}
