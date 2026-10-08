import type { VseTariffCandidate } from '../../types/api'

/**
 * Selection rules for the tariff import wizard.
 *
 * Kept out of the component so they can be tested against real candidate
 * shapes: which rows may be ticked, and which are ticked for you, decides what
 * gets written into a ZEV's billing configuration.
 */

/** Statuses the backend will act on; everything else is shown but inert. */
const IMPORTABLE_STATUSES = new Set<VseTariffCandidate['status']>(['new', 'new_version'])

export function isSelectable(candidate: VseTariffCandidate): boolean {
    return IMPORTABLE_STATUSES.has(candidate.status)
}

/**
 * What the wizard ticks for you: only what the operator itself flags as its
 * standard product *and* that is applicable here. Pre-ticking a whole document
 * — 35 candidates for the operator this was built against — would be worse
 * than pre-ticking nothing, because it invites a blind confirmation.
 */
export function recommendedKeys(candidates: VseTariffCandidate[]): Set<string> {
    return new Set(
        candidates.filter((candidate) => candidate.recommended && isSelectable(candidate)).map((c) => c.key),
    )
}

function yearOf(date: string): number {
    return Number(date.slice(0, 4))
}

/**
 * The calendar years a document's candidates are valid in, ascending.
 *
 * Operators publish next year's prices beside this year's in one file, so the
 * wizard offers these as a filter. An open-ended candidate contributes only the
 * year it starts in — it would otherwise stretch the list without bound.
 */
export function candidateYears(candidates: VseTariffCandidate[]): number[] {
    const years = new Set<number>()
    for (const candidate of candidates) {
        const from = yearOf(candidate.valid_from)
        const to = candidate.valid_to ? yearOf(candidate.valid_to) : from
        for (let year = from; year <= to; year += 1) years.add(year)
    }
    return [...years].sort((a, b) => a - b)
}

/** Whether a candidate is valid at any point in `year`; `null` matches all. */
export function isValidInYear(candidate: VseTariffCandidate, year: number | null): boolean {
    if (year === null) return true
    if (yearOf(candidate.valid_from) > year) return false
    return !candidate.valid_to || yearOf(candidate.valid_to) >= year
}

/**
 * Whether this row's billing mode is still an open question.
 *
 * It is asked once, when the tariff is first imported. Every later version
 * inherits it, because versions of one tariff must agree on how it is billed —
 * so offering the picker again on a `new_version` row would offer a choice
 * whose only outcome is a row the import then refuses. The answer is changed
 * by editing the tariff, not by re-importing it.
 */
export function canChooseBillingMode(candidate: VseTariffCandidate): boolean {
    return candidate.billing_mode_options.length > 0 && candidate.status === 'new'
}

/**
 * The billing mode each candidate starts on, keyed by candidate.
 *
 * Held apart from the tick state so that clearing and re-selecting rows does
 * not throw away a choice the user already made about how a fee is billed.
 */
export function defaultBillingModes(candidates: VseTariffCandidate[]): Record<string, string> {
    return Object.fromEntries(candidates.map((candidate) => [candidate.key, candidate.billing_mode]))
}

/**
 * What to send for one ticked row. The mode is omitted when it is the one the
 * backend proposed, so an unchanged selection carries no override at all.
 */
export function selectionFor(
    candidate: VseTariffCandidate,
    chosen: string | undefined,
): { key: string; billing_mode?: string } {
    return chosen && chosen !== candidate.billing_mode
        ? { key: candidate.key, billing_mode: chosen }
        : { key: candidate.key }
}

export function toggleKey(selected: Set<string>, key: string): Set<string> {
    const next = new Set(selected)
    if (!next.delete(key)) next.add(key)
    return next
}

/** ``0.10600`` → ``0.106``: the stored precision is not news to the reader. */
export function trimPrice(value: string): string {
    const parsed = Number(value)
    return Number.isFinite(parsed) ? String(parsed) : value
}
