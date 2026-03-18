export type QuickRangePreset =
    | 'custom'
    | 'this_month'
    | 'last_month'
    | 'this_quarter'
    | 'last_quarter'
    | 'this_year'
    | 'last_year'

export const QUICK_RANGE_OPTIONS: Array<{ value: QuickRangePreset; label: string }> = [
    { value: 'custom', label: 'Custom' },
    { value: 'this_month', label: 'This month' },
    { value: 'last_month', label: 'Last month' },
    { value: 'this_quarter', label: 'This quarter' },
    { value: 'last_quarter', label: 'Last quarter' },
    { value: 'this_year', label: 'This year' },
    { value: 'last_year', label: 'Last year' },
]

export function todayIso() {
    return new Date().toISOString().slice(0, 10)
}

export function daysAgoIso(days: number) {
    const d = new Date()
    d.setDate(d.getDate() - days)
    return d.toISOString().slice(0, 10)
}

function isoDateLocal(date: Date) {
    const year = date.getFullYear()
    const month = String(date.getMonth() + 1).padStart(2, '0')
    const day = String(date.getDate()).padStart(2, '0')
    return `${year}-${month}-${day}`
}

export function quickRangeToDates(preset: Exclude<QuickRangePreset, 'custom'>) {
    const now = new Date()
    const today = new Date(now.getFullYear(), now.getMonth(), now.getDate())

    if (preset === 'this_month') {
        const from = new Date(today.getFullYear(), today.getMonth(), 1)
        return { from: isoDateLocal(from), to: isoDateLocal(today) }
    }

    if (preset === 'last_month') {
        const from = new Date(today.getFullYear(), today.getMonth() - 1, 1)
        const to = new Date(today.getFullYear(), today.getMonth(), 0)
        return { from: isoDateLocal(from), to: isoDateLocal(to) }
    }

    if (preset === 'this_quarter') {
        const qStartMonth = Math.floor(today.getMonth() / 3) * 3
        const from = new Date(today.getFullYear(), qStartMonth, 1)
        return { from: isoDateLocal(from), to: isoDateLocal(today) }
    }

    if (preset === 'last_quarter') {
        const thisQuarterStartMonth = Math.floor(today.getMonth() / 3) * 3
        const from = new Date(today.getFullYear(), thisQuarterStartMonth - 3, 1)
        const to = new Date(today.getFullYear(), thisQuarterStartMonth, 0)
        return { from: isoDateLocal(from), to: isoDateLocal(to) }
    }

    if (preset === 'this_year') {
        const from = new Date(today.getFullYear(), 0, 1)
        return { from: isoDateLocal(from), to: isoDateLocal(today) }
    }

    const from = new Date(today.getFullYear() - 1, 0, 1)
    const to = new Date(today.getFullYear() - 1, 11, 31)
    return { from: isoDateLocal(from), to: isoDateLocal(to) }
}
