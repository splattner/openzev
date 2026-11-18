import { createSortedRowModel, rowSortingFeature, tableFeatures, useTable, type SortingState } from '@tanstack/react-table'
import { createContext, useContext, useLayoutEffect, useMemo, useState, type HTMLAttributes, type ThHTMLAttributes } from 'react'
import { useTranslation } from 'react-i18next'

const features = tableFeatures({ rowSortingFeature, sortedRowModel: createSortedRowModel() })

type SortValue = string | number | null | undefined
const TableSortingControlsContext = createContext(true)

export function ResponsiveTableHead({ children, ...props }: HTMLAttributes<HTMLTableSectionElement>) {
    const [head, setHead] = useState<HTMLTableSectionElement | null>(null)
    const [cardLayout, setCardLayout] = useState(false)

    useLayoutEffect(() => {
        const table = head?.closest('table')
        if (!head || !table) return
        const measure = () => {
            setCardLayout(getComputedStyle(head).getPropertyValue('--table-card-layout').trim() === '1')
        }
        measure()
        if (typeof ResizeObserver === 'undefined') {
            // shortcut: without ResizeObserver, only viewport changes refresh; add a polyfill if legacy container resizing is required.
            window.addEventListener('resize', measure)
            return () => window.removeEventListener('resize', measure)
        }
        const observer = new ResizeObserver(measure)
        observer.observe(table.parentElement ?? table)
        return () => observer.disconnect()
    }, [head])

    useLayoutEffect(() => {
        if (cardLayout && head?.contains(document.activeElement)) head.closest('table')?.focus()
    }, [cardLayout, head])

    return (
        <TableSortingControlsContext.Provider value={!cardLayout}>
            <thead {...props} ref={setHead} className={`responsive-table-head ${props.className ?? ''}`} data-card-layout={cardLayout}>{children}</thead>
        </TableSortingControlsContext.Provider>
    )
}

function preserveHeaderFocus(button: HTMLButtonElement | null) {
    if (!button) return
    return () => {
        if (document.activeElement === button) button.closest('th')?.focus()
    }
}

export function SortableHeader({ direction, onSort, primary = true, children, ...props }: ThHTMLAttributes<HTMLTableCellElement> & {
    direction?: 'asc' | 'desc' | false
    onSort?: (event: unknown) => void
    primary?: boolean
}) {
    const showControls = useContext(TableSortingControlsContext)
    return (
        <th {...props} className={`sortable-header ${props.className ?? ''}`} tabIndex={-1} aria-sort={onSort && primary && direction ? (direction === 'asc' ? 'ascending' : 'descending') : undefined}>
            {onSort && showControls ? (
                <button type="button" ref={preserveHeaderFocus} className="data-table-sort" onClick={onSort}>
                    {children}<span aria-hidden="true">{direction === 'asc' ? '▲' : direction === 'desc' ? '▼' : ''}</span>
                </button>
            ) : children}
        </th>
    )
}

/** Sorting for tables whose selectable rows, detail rows or card layouts need their own markup. */
export function useTableSorting<T extends Record<string, any>, K extends string>(data: readonly T[], accessors: Record<K, (row: T) => SortValue>) {
    const [sorting, setSorting] = useState<SortingState>([])
    const { i18n } = useTranslation()
    const collator = useMemo(() => new Intl.Collator(i18n?.language, { numeric: true }), [i18n?.language])
    // Lookup-backed accessors can change while the original rows stay the same.
    const rows = [...data]
    const table = useTable({
        features,
        data: rows,
        columns: Object.entries<(row: T) => SortValue>(accessors).map(([id, accessor]) => ({
            id,
            accessorFn: (row: T) => {
                const value = accessor(row)
                return typeof value === 'number' && !Number.isFinite(value) ? undefined : value ?? undefined
            },
        })),
        defaultColumn: {
            sortUndefined: 'last',
            sortFn: (left, right, id) => {
                const a = left.getValue<SortValue>(id)
                const b = right.getValue<SortValue>(id)
                return typeof a === 'number' && typeof b === 'number' ? a - b : collator.compare(String(a ?? ''), String(b ?? ''))
            },
        },
        state: { sorting },
        onSortingChange: setSorting,
        enableMultiSort: false,
        autoResetAll: false,
    })
    return {
        rows: table.getRowModel().rows.map(row => row.original),
        header: (id: K, rowCount = data.length) => ({
            direction: table.getColumn(id)?.getIsSorted(),
            onSort: rowCount > 1 ? table.getColumn(id)?.getToggleSortingHandler() : undefined,
        }),
    }
}
