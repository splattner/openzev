import { flexRender, getCoreRowModel, getFilteredRowModel, getPaginationRowModel, getSortedRowModel, useReactTable, type ColumnDef, type ColumnFiltersState, type RowData, type SortingState } from '@tanstack/react-table'
import { useState, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'

declare module '@tanstack/react-table' {
    // eslint-disable-next-line @typescript-eslint/no-unused-vars
    interface ColumnMeta<TData extends RowData, TValue> {
        numeric?: boolean
    }
}

export type { ColumnDef, ColumnFiltersState }

/** TanStack Table's default column size — used as a sentinel to skip
 *  explicit width when the caller hasn't set one. */
const TANSTACK_DEFAULT_SIZE = 150

interface DataTableProps<T> {
    data: T[]
    columns: ColumnDef<T, unknown>[]
    getRowId?: (row: T) => string
    initialSorting?: SortingState
    /** External filter controls (search boxes, selects) set this state. */
    columnFilters?: ColumnFiltersState
    onColumnFiltersChange?: (updater: ColumnFiltersState) => void
    enableSorting?: boolean
    pageSizeOptions?: number[]
    initialPageSize?: number
    loading?: boolean
    emptyMessage?: ReactNode
}

export function DataTable<T>({
    data,
    columns,
    getRowId,
    initialSorting = [],
    columnFilters,
    onColumnFiltersChange,
    enableSorting = true,
    pageSizeOptions = [10, 25, 50, 100],
    initialPageSize = 25,
    loading,
    emptyMessage,
}: DataTableProps<T>) {
    const { t } = useTranslation()
    const [sorting, setSorting] = useState<SortingState>(initialSorting)
    const [internalFilters, setInternalFilters] = useState<ColumnFiltersState>([])
    const [pagination, setPagination] = useState({ pageIndex: 0, pageSize: initialPageSize })

    // TanStack Table returns unmemoizable functions, so React Compiler skips
    // this component — safe, the table state lives in the hook itself.
    // eslint-disable-next-line react-hooks/incompatible-library
    const table = useReactTable({
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
        getCoreRowModel: getCoreRowModel(),
        getSortedRowModel: enableSorting ? getSortedRowModel() : undefined,
        getFilteredRowModel: getFilteredRowModel(),
        getPaginationRowModel: getPaginationRowModel(),
        getRowId,
    })

    const rows = table.getRowModel().rows

    return (
        <div className="data-table">
            <div className="table-scroll">
                <table>
                    <thead>
                        {table.getHeaderGroups().map((headerGroup) => (
                            <tr key={headerGroup.id}>
                                {headerGroup.headers.map((header) => {
                                    const canSort = enableSorting && header.column.getCanSort()
                                    const dir = header.column.getIsSorted()
                                    const ariaSort: 'ascending' | 'descending' | 'none' | undefined =
                                        canSort ? (dir === 'asc' ? 'ascending' : dir === 'desc' ? 'descending' : 'none') : undefined
                                    return (
                                        <th key={header.id} aria-sort={ariaSort} style={{ width: header.getSize() !== TANSTACK_DEFAULT_SIZE ? header.getSize() : undefined }}>
                                            {header.isPlaceholder ? null : canSort ? (
                                                <button
                                                    type="button"
                                                    className="data-table-sort"
                                                    onClick={header.column.getToggleSortingHandler()}
                                                    aria-label={typeof header.column.columnDef.header === 'string' ? header.column.columnDef.header : undefined}
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
            {/* Footer (range, page size, prev/next) only when data spans more
                than one page — a single-page footer would render permanently
                disabled buttons. */}
            {rows.length > 0 && table.getPageCount() > 1 && (
                <div className="data-table-footer actions-row actions-row-end muted" style={{ fontSize: '0.82rem', alignItems: 'center' }}>
                    <span>
                        {t('common.pagination.range', {
                            from: table.getState().pagination.pageIndex * table.getState().pagination.pageSize + 1,
                            to: Math.min((table.getState().pagination.pageIndex + 1) * table.getState().pagination.pageSize, table.getFilteredRowModel().rows.length),
                            total: table.getFilteredRowModel().rows.length,
                        })}
                    </span>
                    <span style={{ flex: 1 }} />
                    <label style={{ display: 'inline-flex', alignItems: 'center', gap: '0.4rem' }}>
                        <span>{t('common.pagination.rowsPerPage')}</span>
                        <select
                            value={table.getState().pagination.pageSize}
                            onChange={(e) => table.setPageSize(Number(e.target.value))}
                            style={{ width: 'auto' }}
                        >
                            {pageSizeOptions.map((size) => (
                                <option key={size} value={size}>{size}</option>
                            ))}
                        </select>
                    </label>
                    <button
                        className="button button-secondary button-compact"
                        type="button"
                        aria-label={t('common.pagination.previous')}
                        onClick={() => table.previousPage()}
                        disabled={!table.getCanPreviousPage()}
                    >
                        ‹
                    </button>
                    <span>{table.getState().pagination.pageIndex + 1} / {Math.max(1, table.getPageCount())}</span>
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
