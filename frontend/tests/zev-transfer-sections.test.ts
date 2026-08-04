import { describe, expect, it } from 'vitest'
import {
  DEFAULT_SECTIONS,
  isSelectable,
  toggleSection,
  unmetRequirements,
  type TransferSectionName,
} from '../src/features/zev/transferSections'
import { de } from '../src/i18n/locales/de'
import { en } from '../src/i18n/locales/en'
import { fr } from '../src/i18n/locales/fr'
import { it as italian } from '../src/i18n/locales/it'

const all = DEFAULT_SECTIONS.map((section) => section.name)
const byName = (name: TransferSectionName) =>
  DEFAULT_SECTIONS.find((section) => section.name === name)!

describe('isSelectable', () => {
  it('blocks a section whose prerequisite is unselected', () => {
    expect(isSelectable(byName('readings'), ['zev'])).toBe(false)
    expect(isSelectable(byName('readings'), ['metering_points'])).toBe(true)
  })

  it('always allows a section with no prerequisites', () => {
    expect(isSelectable(byName('tariffs'), [])).toBe(true)
  })
})

describe('unmetRequirements', () => {
  it('names what is missing so the UI can say why a box is disabled', () => {
    expect(unmetRequirements(byName('metering_points'), [])).toEqual(['participants'])
    expect(unmetRequirements(byName('metering_points'), ['participants'])).toEqual([])
  })
})

describe('toggleSection', () => {
  it('pulls prerequisites in when a section is ticked', () => {
    const next = toggleSection(DEFAULT_SECTIONS, [], 'readings')
    expect(next).toEqual(['participants', 'metering_points', 'readings'])
  })

  it('follows the chain transitively rather than one level deep', () => {
    // readings -> metering_points -> participants
    expect(toggleSection(DEFAULT_SECTIONS, [], 'readings')).toContain('participants')
  })

  it('drops whatever depended on a section that is unticked', () => {
    const next = toggleSection(DEFAULT_SECTIONS, all, 'participants')
    expect(next).not.toContain('participants')
    expect(next).not.toContain('metering_points')
    expect(next).not.toContain('readings')
    expect(next).not.toContain('invoices')
    expect(next).toEqual(['zev', 'tariffs'])
  })

  it('leaves independent sections alone when one is unticked', () => {
    expect(toggleSection(DEFAULT_SECTIONS, all, 'tariffs')).not.toContain('tariffs')
    expect(toggleSection(DEFAULT_SECTIONS, all, 'tariffs')).toContain('readings')
  })

  it('keeps the canonical order regardless of the order things were ticked', () => {
    let selected: TransferSectionName[] = []
    for (const name of ['invoices', 'zev', 'readings'] as TransferSectionName[]) {
      selected = toggleSection(DEFAULT_SECTIONS, selected, name)
    }
    // tariffs is deliberately absent: nothing depends on it, so ticking
    // invoices does not drag pricing along with the billing history.
    expect(selected).toEqual(['zev', 'participants', 'metering_points', 'readings', 'invoices'])
  })

  it('never produces a selection the backend would reject', () => {
    // Every reachable selection must satisfy every dependency.
    let selected: TransferSectionName[] = [...all]
    for (const name of all) {
      selected = toggleSection(DEFAULT_SECTIONS, selected, name)
      for (const section of DEFAULT_SECTIONS) {
        if (selected.includes(section.name)) {
          expect(unmetRequirements(section, selected)).toEqual([])
        }
      }
    }
  })
})

describe('locale coverage', () => {
  const locales = { en, de, fr, it: italian } as Record<string, { zevTransfer: Record<string, unknown> }>

  it('defines zevTransfer in every language with the same keys', () => {
    const reference = Object.keys(en.zevTransfer).sort()
    for (const [name, locale] of Object.entries(locales)) {
      expect(Object.keys(locale.zevTransfer).sort(), name).toEqual(reference)
    }
  })

  it('names every section in every language', () => {
    for (const [name, locale] of Object.entries(locales)) {
      const sections = locale.zevTransfer.sections as Record<string, string>
      expect(Object.keys(sections).sort(), name).toEqual([...all].sort())
    }
  })
})
