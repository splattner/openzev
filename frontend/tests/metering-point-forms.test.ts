import { describe, expect, it } from 'vitest'
import {
  assignmentStateBadgeClass,
  assignmentStateSortOrder,
  defaultAssignmentForm,
  defaultMeteringPointForm,
  getAssignmentState,
  getNextAssignmentGuidance,
  isAssignmentCurrent,
} from '../src/features/meteringPoints/useMeteringPointForms'
import type { MeteringPointAssignment } from '../src/types/api'

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
})
