import { formatIsoDate } from './dates'

export type QuickRangePreset =
    | 'custom'
    | 'this_month'
    | 'last_month'
    | 'this_quarter'
    | 'last_quarter'
    | 'this_year'
    | 'last_year'

export function quickRangeToDates(preset: Exclude<QuickRangePreset, 'custom'>) {
    const now = new Date()
    const today = new Date(now.getFullYear(), now.getMonth(), now.getDate())

    if (preset === 'this_month') {
        const from = new Date(today.getFullYear(), today.getMonth(), 1)
        return { from: formatIsoDate(from), to: formatIsoDate(today) }
    }

    if (preset === 'last_month') {
        const from = new Date(today.getFullYear(), today.getMonth() - 1, 1)
        const to = new Date(today.getFullYear(), today.getMonth(), 0)
        return { from: formatIsoDate(from), to: formatIsoDate(to) }
    }

    if (preset === 'this_quarter') {
        const qStartMonth = Math.floor(today.getMonth() / 3) * 3
        const from = new Date(today.getFullYear(), qStartMonth, 1)
        return { from: formatIsoDate(from), to: formatIsoDate(today) }
    }

    if (preset === 'last_quarter') {
        const thisQuarterStartMonth = Math.floor(today.getMonth() / 3) * 3
        const from = new Date(today.getFullYear(), thisQuarterStartMonth - 3, 1)
        const to = new Date(today.getFullYear(), thisQuarterStartMonth, 0)
        return { from: formatIsoDate(from), to: formatIsoDate(to) }
    }

    if (preset === 'this_year') {
        const from = new Date(today.getFullYear(), 0, 1)
        return { from: formatIsoDate(from), to: formatIsoDate(today) }
    }

    const from = new Date(today.getFullYear() - 1, 0, 1)
    const to = new Date(today.getFullYear() - 1, 11, 31)
    return { from: formatIsoDate(from), to: formatIsoDate(to) }
}
