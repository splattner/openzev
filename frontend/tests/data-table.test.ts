import { act, createElement, forwardRef, memo, useState } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { DataTable, type CellContext, type ColumnDef, type ColumnFiltersState } from '../src/components/DataTable'

vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key }) }))

type Row = {
    id: string
    name: string
    amount: number
    // Labels sort opposite to the numeric values.
    amountLabel: string
}

const rows: Row[] = [
    { id: 'ten', name: 'Ten', amount: 10, amountLabel: 'Alpha' },
    { id: 'two', name: 'Two', amount: 2, amountLabel: 'Zulu' },
]

const columns: ColumnDef<Row, unknown>[] = [
    { accessorKey: 'name', header: 'Name' },
    {
        accessorKey: 'amount',
        header: 'Amount',
        sortDescFirst: false,
        meta: { numeric: true },
        cell: ({ row }) => row.original.amountLabel,
    },
    { id: 'actions', header: 'Actions', enableSorting: false, cell: () => '—' },
]

let container: HTMLDivElement
let root: ReturnType<typeof createRoot>

beforeEach(() => {
    container = document.createElement('div')
    document.body.append(container)
    root = createRoot(container)
})

afterEach(() => {
    act(() => root.unmount())
    container.remove()
})

function render(tableRows: Row[], filters?: ColumnFiltersState, options: {
    pageSize?: number
    enableSorting?: boolean
    tableClassName?: string
    onRowClick?: (row: Row) => void
    rowClassName?: (row: Row) => string | undefined
} = {}) {
    act(() => root.render(createElement(DataTable<Row>, {
        data: tableRows,
        columns,
        getRowId: (row) => row.id,
        columnFilters: filters,
        onColumnFiltersChange: () => undefined,
        emptyMessage: 'Empty',
        ...options,
    })))
}

function rowNames(): string[] {
    return Array.from(container.querySelectorAll('tbody tr'))
        .map((row) => row.querySelector('td')?.textContent ?? '')
}

function header(label: string): HTMLTableCellElement {
    const cell = Array.from(container.querySelectorAll<HTMLTableCellElement>('thead th'))
        .find((th) => th.textContent?.startsWith(label))
    if (!cell) throw new Error(`header ${label} not found`)
    return cell
}

function expectPlainHeaders(): void {
    expect(container.querySelectorAll('.data-table-sort')).toHaveLength(0)
    expect(container.querySelectorAll('thead th[aria-sort]')).toHaveLength(0)
    expect(header('Name').textContent).toBe('Name')
}

describe('DataTable sorting', () => {
    it.each([0, 1])('renders plain headers with %i rows', (count) => {
        render(rows.slice(0, count))
        expectPlainHeaders()
    })

    it('offers sorting with two rows and sorts on the accessor value, not the display label', () => {
        render(rows)
        expect(rowNames()).toEqual(['Ten', 'Two'])
        expect(container.querySelector('th[aria-sort]')).toBeNull()
        expect(header('Amount').classList.contains('numeric')).toBe(true)
        expect(header('Amount').getAttribute('scope')).toBe('col')

        act(() => header('Amount').querySelector('button')!.click())

        expect(rowNames()).toEqual(['Two', 'Ten'])
        expect(header('Amount').getAttribute('aria-sort')).toBe('ascending')

        act(() => header('Amount').querySelector('button')!.click())

        expect(rowNames()).toEqual(['Ten', 'Two'])
        expect(header('Amount').getAttribute('aria-sort')).toBe('descending')
    })

    it('hides the controls again when a filter leaves a single row', () => {
        render(rows)
        expect(container.querySelectorAll('.data-table-sort')).toHaveLength(2)

        act(() => header('Amount').querySelector('button')!.click())
        render(rows, [{ id: 'name', value: 'Ten' }])

        expect(rowNames()).toEqual(['Ten'])
        expectPlainHeaders()

        render(rows)
        expect(container.querySelectorAll('.data-table-sort')).toHaveLength(2)
        expect(rowNames()).toEqual(['Two', 'Ten'])
    })

    it('does not sort action columns', () => {
        render(rows)

        expect(header('Actions').getAttribute('aria-sort')).toBeNull()
        expect(header('Actions').querySelector('.data-table-sort')).toBeNull()
        expect(header('Amount').querySelector('.data-table-sort')).not.toBeNull()
    })

    it('applies table class, row class and row click', () => {
        const clicked: string[] = []
        render(rows, undefined, {
            tableClassName: 'participant-table',
            rowClassName: (row) => row.id === 'ten' ? 'is-selected' : undefined,
            onRowClick: (row) => clicked.push(row.id),
        })

        expect(container.querySelector('table.participant-table')).not.toBeNull()
        const renderedRows = container.querySelectorAll('tbody tr')
        expect(renderedRows[0].classList.contains('is-selected')).toBe(true)
        expect(renderedRows[1].classList.contains('is-selected')).toBe(false)

        act(() => renderedRows[1].dispatchEvent(new MouseEvent('click', { bubbles: true })))
        expect(clicked).toEqual(['two'])
    })

    it('preserves focus and cell state across caller rerenders and row removal', () => {
        function StatefulCell({ row }: CellContext<Row, unknown>) {
            const [count, setCount] = useState(0)
            return createElement('button', { onClick: () => setCount(count + 1) }, `${row.original.name} ${count}`)
        }
        const draw = (data: Row[]) => act(() => root.render(createElement(DataTable<Row>, {
            data,
            columns: [{ accessorKey: 'name', header: 'Name', cell: StatefulCell }],
            getRowId: (row) => row.id,
        })))

        draw(rows)
        const button = container.querySelector<HTMLButtonElement>('tbody button')!
        button.focus()
        act(() => button.click())
        draw([rows[0]])

        expect(document.activeElement?.textContent).toBe('Ten 1')
    })

    it.each([
        ['memo', memo(({ row }: CellContext<Row, unknown>) => row.original.name)],
        ['forwardRef', forwardRef<HTMLSpanElement, CellContext<Row, unknown>>(({ row }, ref) =>
            createElement('span', { ref }, row.original.name))],
    ])('renders a %s cell component', (_name, CellComponent) => {
        act(() => root.render(createElement(DataTable<Row>, {
            data: rows,
            columns: [{
                accessorKey: 'name',
                cell: CellComponent,
            }],
        })))
        expect(rowNames()).toEqual(['Ten', 'Two'])
    })
})


describe('DataTable sort state and focus', () => {
    it('exposes aria-sort only on the primary sort column during multi-sort', () => {
        render(rows)
        act(() => header('Amount').querySelector('button')!.click())
        act(() => header('Name').querySelector('button')!.dispatchEvent(new MouseEvent('click', { bubbles: true, shiftKey: true })))
        expect(container.querySelectorAll('th[aria-sort]')).toHaveLength(1)
        expect(header('Amount').getAttribute('aria-sort')).toBe('ascending')
        expect(header('Name').getAttribute('aria-sort')).toBeNull()
    })

    it('keeps sort controls when pagination shows one of several rows', () => {
        render(rows, undefined, { pageSize: 1 })
        expect(rowNames()).toHaveLength(1)
        expect(container.querySelectorAll('.data-table-sort')).toHaveLength(2)
    })

    it('respects the table sorting opt-out', () => {
        render(rows, undefined, { enableSorting: false })
        expectPlainHeaders()
    })

    it('retains button focus on sorting and moves it to the header when the control disappears', () => {
        render(rows)
        const button = header('Amount').querySelector('button')!
        button.focus()
        act(() => button.click())
        expect(document.activeElement).toBe(button)
        render([rows[1]])
        expect(document.activeElement).toBe(header('Amount'))
    })

    it('leaves focus on the external filter when controls disappear', () => {
        render(rows)
        const input = document.createElement('input')
        container.prepend(input)
        input.focus()
        render(rows, [{ id: 'name', value: 'Ten' }])
        expect(document.activeElement).toBe(input)
    })
})
