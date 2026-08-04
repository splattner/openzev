/**
 * Section-selection rules for ZEV export and import.
 *
 * The dependency graph itself comes from the backend
 * (`/zev/zevs/transfer-sections/`) so it lives in one place — assignments need
 * participants because of a foreign key, not because of a UI convention. What
 * is here is what the *UI* does with it: which boxes to disable, and what
 * ticking one implies about the others.
 */

export type TransferSectionName =
  | 'zev'
  | 'participants'
  | 'metering_points'
  | 'tariffs'
  | 'readings'
  | 'invoices'

export type TransferSection = {
  name: TransferSectionName
  requires: TransferSectionName[]
}

/**
 * Fallback used before the graph has loaded, so the dialog is never briefly
 * wrong. Kept identical to `SECTION_DEPENDENCIES` in `zev/transfer/schema.py`;
 * the served copy wins the moment it arrives.
 */
export const DEFAULT_SECTIONS: TransferSection[] = [
  { name: 'zev', requires: [] },
  { name: 'participants', requires: [] },
  { name: 'metering_points', requires: ['participants'] },
  { name: 'tariffs', requires: [] },
  { name: 'readings', requires: ['metering_points'] },
  { name: 'invoices', requires: ['participants'] },
]

/** True when every prerequisite of `section` is currently selected. */
export function isSelectable(section: TransferSection, selected: TransferSectionName[]): boolean {
  return section.requires.every((requirement) => selected.includes(requirement))
}

/** The unmet prerequisites of `section`, for the "needs X" hint on a disabled box. */
export function unmetRequirements(
  section: TransferSection,
  selected: TransferSectionName[],
): TransferSectionName[] {
  return section.requires.filter((requirement) => !selected.includes(requirement))
}

/**
 * Toggle `name`, keeping the selection coherent in both directions.
 *
 * Ticking a section pulls its prerequisites in; unticking one drops whatever
 * depended on it. Without the second half a user can select readings, then
 * untick metering points, and submit a selection the backend rejects — the
 * error would be correct and the interaction still bad.
 */
export function toggleSection(
  sections: TransferSection[],
  selected: TransferSectionName[],
  name: TransferSectionName,
): TransferSectionName[] {
  const byName = new Map(sections.map((section) => [section.name, section]))
  const next = new Set(selected)

  if (next.has(name)) {
    next.delete(name)
    // Repeat until nothing changes: dropping a section can orphan another that
    // in turn orphans a third.
    let changed = true
    while (changed) {
      changed = false
      for (const section of sections) {
        if (next.has(section.name) && section.requires.some((requirement) => !next.has(requirement))) {
          next.delete(section.name)
          changed = true
        }
      }
    }
  } else {
    const pending = [name]
    while (pending.length > 0) {
      const current = pending.pop() as TransferSectionName
      if (next.has(current)) continue
      next.add(current)
      pending.push(...(byName.get(current)?.requires ?? []))
    }
  }

  return sections.map((section) => section.name).filter((sectionName) => next.has(sectionName))
}
