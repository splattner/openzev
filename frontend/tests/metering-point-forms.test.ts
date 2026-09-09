import { describe, expect, it } from 'vitest'
import {
  assignmentStateBadgeClass,
  assignmentStateSortOrder,
  defaultAssignmentForm,
  defaultMeteringPointForm,
  getAssignmentState,
  getMeteringPointHealth,
  getMeteringPointHealthWindow,
  getNextAssignmentGuidance,
  isAssignmentCurrent,
  isMeteringPointHolderLess,
  meteringPointHealthBadgeClass,
  meteringPointNeedsAttention,
} from '../src/features/meteringPoints/useMeteringPointForms'
import type { MeteringPoint, MeteringPointAssignment, MeteringPointDataQuality } from '../src/types/api'

describe('metering point form helpers', () => {
  it('provides stable default metering point form values', () => {
    expect(defaultMeteringPointForm()).toEqual({
      zev: '',
      meter_id: '',
      meter_type: 'consumption',
      is_active: true,
      location_description: '',
    })
  })

  it('builds default assignment form with provided metering point', () => {
    const form = defaultAssignmentForm('mp-1')

    expect(form.metering_point).toBe('mp-1')
    expect(form.participant).toBe('')
    expect(form.valid_to).toBeNull()
    expect(form.valid_from).toMatch(/^\d{4}-\d{2}-\d{2}$/)
    expect(form.allocation_mode).toBe('personal')
  })

  it('classifies assignment state correctly', () => {
    const today = '2026-05-08'

    const current = {
      valid_from: '2026-05-01',
      valid_to: '2026-05-31',
    } as MeteringPointAssignment
    const upcoming = {
      valid_from: '2026-06-01',
      valid_to: null,
    } as MeteringPointAssignment
    const ended = {
      valid_from: '2026-04-01',
      valid_to: '2026-04-30',
    } as MeteringPointAssignment

    expect(getAssignmentState(current, today)).toBe('current')
    expect(getAssignmentState(upcoming, today)).toBe('upcoming')
    expect(getAssignmentState(ended, today)).toBe('ended')
  })

  it('maps assignment state to badge classes and sort order', () => {
    expect(assignmentStateBadgeClass('current')).toBe('badge badge-success')
    expect(assignmentStateBadgeClass('upcoming')).toBe('badge badge-info')
    expect(assignmentStateBadgeClass('ended')).toBe('badge badge-neutral')

    expect(assignmentStateSortOrder('current')).toBeLessThan(assignmentStateSortOrder('upcoming'))
    expect(assignmentStateSortOrder('upcoming')).toBeLessThan(assignmentStateSortOrder('ended'))
  })

  it('treats only a currently-in-force assignment as "current"', () => {
    const today = '2026-05-08'

    expect(isAssignmentCurrent({ valid_from: '2026-05-01', valid_to: null } as MeteringPointAssignment, today)).toBe(true)
    expect(isAssignmentCurrent({ valid_from: '2026-04-01', valid_to: '2026-04-30' } as MeteringPointAssignment, today)).toBe(false)
    expect(isAssignmentCurrent({ valid_from: '2026-06-01', valid_to: null } as MeteringPointAssignment, today)).toBe(false)
  })

  describe('getNextAssignmentGuidance', () => {
    const today = '2026-05-08'

    it('suggests today when the meter has no assignment history', () => {
      const guidance = getNextAssignmentGuidance([], today)
      expect(guidance.suggestedValidFrom).toBe(today)
      expect(guidance.hasOpenEndedAssignment).toBe(false)
    })

    it('suggests the day after the latest ended assignment (a tenant handover)', () => {
      const guidance = getNextAssignmentGuidance(
        [{ valid_from: '2025-01-01', valid_to: '2026-03-31' } as MeteringPointAssignment],
        today,
      )
      expect(guidance.suggestedValidFrom).toBe('2026-04-01')
      expect(guidance.hasOpenEndedAssignment).toBe(false)
    })

    it('picks the latest end date across multiple past assignments', () => {
      const guidance = getNextAssignmentGuidance(
        [
          { valid_from: '2024-01-01', valid_to: '2024-12-31' } as MeteringPointAssignment,
          { valid_from: '2025-01-01', valid_to: '2026-03-31' } as MeteringPointAssignment,
        ],
        today,
      )
      expect(guidance.suggestedValidFrom).toBe('2026-04-01')
    })

    it('flags an open-ended assignment so the caller can warn before it overlaps', () => {
      const guidance = getNextAssignmentGuidance(
        [{ valid_from: '2025-01-01', valid_to: null } as MeteringPointAssignment],
        today,
      )
      expect(guidance.hasOpenEndedAssignment).toBe(true)
    })

    it('crosses a month/year boundary correctly', () => {
      const guidance = getNextAssignmentGuidance(
        [{ valid_from: '2025-01-01', valid_to: '2025-12-31' } as MeteringPointAssignment],
        today,
      )
      expect(guidance.suggestedValidFrom).toBe('2026-01-01')
    })
  })

  describe('getMeteringPointHealthWindow', () => {
    it('spans 30 days ending today by default', () => {
      expect(getMeteringPointHealthWindow('2026-05-08')).toEqual({ from: '2026-04-08', to: '2026-05-08' })
    })

    it('crosses a year boundary', () => {
      expect(getMeteringPointHealthWindow('2026-01-05')).toEqual({ from: '2025-12-06', to: '2026-01-05' })
    })

    it('accepts a custom window length', () => {
      expect(getMeteringPointHealthWindow('2026-05-08', 7)).toEqual({ from: '2026-05-01', to: '2026-05-08' })
    })
  })

  describe('getMeteringPointHealth', () => {
    function quality(overrides: Partial<MeteringPointDataQuality>): MeteringPointDataQuality {
      return { severity: 'green', ...overrides } as MeteringPointDataQuality
    }

    it('is "no_data" for a meter that has never received a reading, even with a quality-status entry', () => {
      expect(getMeteringPointHealth({ reading_count: 0 }, quality({ severity: 'green' }))).toBe('no_data')
    })

    it('is "no_data" for a meter with readings but no matching quality-status entry (defensive fallback)', () => {
      expect(getMeteringPointHealth({ reading_count: 10 }, undefined)).toBe('no_data')
    })

    it('takes the severity from the quality-status entry once the meter has data', () => {
      expect(getMeteringPointHealth({ reading_count: 10 }, quality({ severity: 'yellow' }))).toBe('yellow')
      expect(getMeteringPointHealth({ reading_count: 10 }, quality({ severity: 'red' }))).toBe('red')
    })
  })

  describe('isMeteringPointHolderLess', () => {
    const today = '2026-05-08'

    function point(overrides: Partial<Pick<MeteringPoint, 'is_active' | 'reading_count'>>) {
      return { is_active: true, reading_count: 10, ...overrides }
    }

    it('flags a meter with readings and no assignment in force today', () => {
      expect(isMeteringPointHolderLess(point({}), [], today)).toBe(true)
    })

    it('does not flag a meter with a current assignment', () => {
      const assignments = [{ valid_from: '2026-01-01', valid_to: null } as MeteringPointAssignment]
      expect(isMeteringPointHolderLess(point({}), assignments, today)).toBe(false)
    })

    it('does not flag a meter whose only assignment already ended (that is #621\'s assignedCount, not this)', () => {
      const assignments = [{ valid_from: '2025-01-01', valid_to: '2025-12-31' } as MeteringPointAssignment]
      expect(isMeteringPointHolderLess(point({}), assignments, today)).toBe(true)
    })

    it('does not flag an inactive meter — it is out of billing scope', () => {
      expect(isMeteringPointHolderLess(point({ is_active: false }), [], today)).toBe(false)
    })

    it('does not flag a meter with no readings yet — nothing to attribute', () => {
      expect(isMeteringPointHolderLess(point({ reading_count: 0 }), [], today)).toBe(false)
    })
  })

  describe('meteringPointNeedsAttention', () => {
    it('flags an active meter whose health is not green', () => {
      expect(meteringPointNeedsAttention({ is_active: true }, 'yellow', false)).toBe(true)
      expect(meteringPointNeedsAttention({ is_active: true }, 'red', false)).toBe(true)
      expect(meteringPointNeedsAttention({ is_active: true }, 'no_data', false)).toBe(true)
    })

    it('flags an active, healthy meter that is holder-less', () => {
      expect(meteringPointNeedsAttention({ is_active: true }, 'green', true)).toBe(true)
    })

    it('does not flag a healthy, held, active meter', () => {
      expect(meteringPointNeedsAttention({ is_active: true }, 'green', false)).toBe(false)
    })

    it('never flags an inactive meter, regardless of health or holder status', () => {
      expect(meteringPointNeedsAttention({ is_active: false }, 'red', true)).toBe(false)
    })
  })

  it('maps health to badge classes', () => {
    expect(meteringPointHealthBadgeClass('green')).toBe('badge badge-success')
    expect(meteringPointHealthBadgeClass('yellow')).toBe('badge badge-warning')
    expect(meteringPointHealthBadgeClass('red')).toBe('badge badge-danger')
    expect(meteringPointHealthBadgeClass('no_data')).toBe('badge badge-neutral')
  })
})
