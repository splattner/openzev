import type { ShortDateFormat } from '../../types/api'

export type DatePart = { text: string, strong: boolean }

/**
 * A short date split into runs, with the year — and the month too, for a
 * start within this year — marked strong: what tells one upcoming start from
 * another at a glance. `pattern` is the format the date was written in; a
 * separator between two strong fields is strong too, so `01.11.2026` reads
 * `01.` + `11.2026`.
 */
export function emphasizedDate(formatted: string, pattern: ShortDateFormat, withMonth: boolean): DatePart[] {
    const fields = pattern.split(/([./-])/)
    const texts = formatted.split(/([./-])/)
    if (fields.length !== texts.length) return [{ text: formatted, strong: false }]
    const field = (index: number) => fields[index] === 'yyyy' || (withMonth && fields[index] === 'MM')
    return texts.reduce<DatePart[]>((runs, text, index) => {
        const strong = index % 2 === 0 ? field(index) : field(index - 1) && field(index + 1)
        const last = runs[runs.length - 1]
        if (last && last.strong === strong) last.text += text
        else runs.push({ text, strong })
        return runs
    }, [])
}
