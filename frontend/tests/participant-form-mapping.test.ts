import { describe, expect, it } from 'vitest'
import {
  defaultParticipantFormValues,
  mapParticipantFormValuesToInput,
  mapParticipantToFormValues,
  participantFormSchema,
} from '../src/features/participants/useParticipantForm'
import type { Participant } from '../src/types/api'

describe('participant form mapping', () => {
  it('maps participant api model into form values with safe defaults', () => {
    const participant = {
      id: 'p-1',
      zev: 'z-1',
      user: 123,
      title: null,
      first_name: 'Anna',
      last_name: 'Muster',
      email: null,
      phone: null,
      address_line1: null,
      address_line2: null,
      postal_code: null,
      city: null,
      notes: null,
      valid_from: '2026-01-01',
      valid_to: null,
      has_metering_point_assignment: false,
      account_username: null,
      initial_password: null,
      created_at: '2026-01-01T00:00:00Z',
      updated_at: '2026-01-01T00:00:00Z',
    } as unknown as Participant

    expect(mapParticipantToFormValues(participant)).toEqual({
      ...defaultParticipantFormValues,
      first_name: 'Anna',
      last_name: 'Muster',
      valid_from: '2026-01-01',
    })
  })

  it('maps form values into participant input payload and trims required names/email', () => {
    const input = mapParticipantFormValuesToInput(
      {
        ...defaultParticipantFormValues,
        title: 'dr',
        first_name: '  Anna  ',
        last_name: '  Muster ',
        email: ' anna@example.com ',
        phone: '044 111 22 33',
        address_line1: 'Street 1',
        address_line2: 'Top 2',
        postal_code: '8000',
        city: 'Zurich',
        notes: 'note',
        valid_from: '2026-01-01',
        valid_to: '',
      },
      'z-1',
    )

    expect(input).toEqual({
      zev: 'z-1',
      title: 'dr',
      first_name: 'Anna',
      last_name: 'Muster',
      email: 'anna@example.com',
      phone: '044 111 22 33',
      address_line1: 'Street 1',
      address_line2: 'Top 2',
      postal_code: '8000',
      city: 'Zurich',
      notes: 'note',
      valid_from: '2026-01-01',
      valid_to: null,
    })
  })

  it('preserves an existing allocation_weight when mapping into form values', () => {
    const participant = {
      id: 'p-1',
      zev: 'z-1',
      first_name: 'Anna',
      last_name: 'Muster',
      valid_from: '2026-01-01',
      allocation_weight: '2.5000',
    } as unknown as Participant

    expect(mapParticipantToFormValues(participant).allocation_weight).toBe('2.5000')
  })

  it('omits allocation_weight from the payload when left empty, so the backend default applies', () => {
    const input = mapParticipantFormValuesToInput(
      { ...defaultParticipantFormValues, first_name: 'Anna', last_name: 'Muster', email: 'a@example.com' },
      'z-1',
    )

    expect(input.allocation_weight).toBeUndefined()
  })

  it('sends a non-empty allocation_weight through unchanged', () => {
    const input = mapParticipantFormValuesToInput(
      {
        ...defaultParticipantFormValues,
        first_name: 'Anna',
        last_name: 'Muster',
        email: 'a@example.com',
        allocation_weight: '3.0000',
      },
      'z-1',
    )

    expect(input.allocation_weight).toBe('3.0000')
  })

  it('accepts an empty allocation_weight (the backend default applies)', () => {
    const result = participantFormSchema.safeParse({
      ...defaultParticipantFormValues,
      first_name: 'Anna',
      last_name: 'Muster',
      email: 'a@example.com',
    })
    expect(result.success).toBe(true)
  })

  it('accepts a positive allocation_weight', () => {
    const result = participantFormSchema.safeParse({
      ...defaultParticipantFormValues,
      first_name: 'Anna',
      last_name: 'Muster',
      email: 'a@example.com',
      allocation_weight: '0.5',
    })
    expect(result.success).toBe(true)
  })

  it.each(['0', '-1', 'abc'])('rejects a non-positive or non-numeric allocation_weight (%s)', (value) => {
    const result = participantFormSchema.safeParse({
      ...defaultParticipantFormValues,
      first_name: 'Anna',
      last_name: 'Muster',
      email: 'a@example.com',
      allocation_weight: value,
    })
    expect(result.success).toBe(false)
  })
})
