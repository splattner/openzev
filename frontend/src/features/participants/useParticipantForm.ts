import { z } from 'zod'
import i18n from '../../i18n'
import { todayLocalIso } from '../../lib/dates'
import type { Participant, ParticipantInput } from '../../types/api'

export type ParticipantFormValues = {
  title: NonNullable<ParticipantInput['title']>
  first_name: string
  last_name: string
  email: string
  phone: string
  address_line1: string
  address_line2: string
  postal_code: string
  city: string
  notes: string
  valid_from: string
  valid_to: string
  allocation_weight: string
}

export const participantFormSchema = z
  .object({
    title: z.enum(['', 'mr', 'mrs', 'ms', 'dr', 'prof']),
    first_name: z.string().trim().min(1),
    last_name: z.string().trim().min(1),
    email: z.string().trim().email(),
    phone: z.string(),
    address_line1: z.string(),
    address_line2: z.string(),
    postal_code: z.string(),
    city: z.string(),
    notes: z.string(),
    valid_from: z.string().trim().min(1),
    valid_to: z.string(),
    allocation_weight: z.string(),
  })
  .superRefine((values, ctx) => {
    // Empty is valid — it lets the backend default to 1. A non-empty value
    // must be a plain positive decimal: this is a relative weight, never a
    // percentage, per-mille, or Wertquote (§5.2).
    if (values.allocation_weight && !(Number(values.allocation_weight) > 0)) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        path: ['allocation_weight'],
        message: i18n.t('pages.participants.validation.allocationWeightPositive'),
      })
    }
  })

export const defaultParticipantFormValues: ParticipantFormValues = {
  title: '',
  first_name: '',
  last_name: '',
  email: '',
  phone: '',
  address_line1: '',
  address_line2: '',
  postal_code: '',
  city: '',
  notes: '',
  valid_from: todayLocalIso(),
  valid_to: '',
  allocation_weight: '',
}

export function mapParticipantToFormValues(participant: Participant): ParticipantFormValues {
  return {
    title: participant.title || '',
    first_name: participant.first_name,
    last_name: participant.last_name,
    email: participant.email || '',
    phone: participant.phone || '',
    address_line1: participant.address_line1 || '',
    address_line2: participant.address_line2 || '',
    postal_code: participant.postal_code || '',
    city: participant.city || '',
    notes: participant.notes || '',
    valid_from: participant.valid_from,
    valid_to: participant.valid_to || '',
    allocation_weight: participant.allocation_weight || '',
  }
}

export function mapParticipantFormValuesToInput(values: ParticipantFormValues, zevId: string): ParticipantInput {
  return {
    zev: zevId,
    title: values.title,
    first_name: values.first_name.trim(),
    last_name: values.last_name.trim(),
    email: values.email.trim(),
    phone: values.phone,
    address_line1: values.address_line1,
    address_line2: values.address_line2,
    postal_code: values.postal_code,
    city: values.city,
    notes: values.notes,
    valid_from: values.valid_from,
    valid_to: values.valid_to || null,
    allocation_weight: values.allocation_weight || undefined,
  }
}
