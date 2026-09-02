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
