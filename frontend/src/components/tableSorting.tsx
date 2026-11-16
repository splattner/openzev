import { createSortedRowModel, rowSortingFeature, tableFeatures, useTable, type SortingState } from '@tanstack/react-table'
import { createContext, useContext, useLayoutEffect, useMemo, useState, type HTMLAttributes, type ThHTMLAttributes } from 'react'
import { useTranslation } from 'react-i18next'

const features = tableFeatures({ rowSortingFeature, sortedRowModel: createSortedRowModel() })

type SortValue = string | number | null | undefined
const HeaderFitsContext = createContext(true)

export function SingleLineTableHead({ children, ...props }: HTMLAttributes<HTMLTableSectionElement>) {
    const [head, setHead] = useState<HTMLTableSectionElement | null>(null)
    const [fits, setFits] = useState(true)

    useLayoutEffect(() => {
        if (!head || typeof ResizeObserver === 'undefined') return
        const row = head.rows[0]
        const measure = () => {
            const boxes = Array.from(row.querySelectorAll('.sortable-header'), cell => cell.getBoundingClientRect()).filter(box => box.width && box.height)
            setFits(boxes.every(box => Math.abs(box.top - boxes[0].top) < 1))
        }
        measure()
        const observer = new ResizeObserver(measure)
        observer.observe(row)
        return () => observer.disconnect()
    }, [head])

    useLayoutEffect(() => {
        if (!fits && head?.contains(document.activeElement)) head.closest('table')?.focus()
    }, [fits, head])

    return (
        <HeaderFitsContext.Provider value={fits}>
            <thead {...props} ref={setHead} className={`single-line-table-head ${props.className ?? ''}`} data-header-fits={fits}>{children}</thead>
        </HeaderFitsContext.Provider>
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
    const fits = useContext(HeaderFitsContext)
    const sortContent = <>{children}<span aria-hidden="true">{direction === 'asc' ? '▲' : direction === 'desc' ? '▼' : ''}</span></>
    return (
        <th {...props} className={`sortable-header ${props.className ?? ''}`} tabIndex={-1} aria-sort={onSort && primary && direction ? (direction === 'asc' ? 'ascending' : 'descending') : undefined}>
            {onSort && fits ? (
                <button type="button" ref={preserveHeaderFocus} className="data-table-sort" onClick={onSort}>
                    {sortContent}
                </button>
            ) : onSort ? <span className="data-table-sort">{sortContent}</span> : children}
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
