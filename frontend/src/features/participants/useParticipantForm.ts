import { z } from 'zod'
import i18n from '../../i18n'
import { todayBusinessIso } from '../../lib/dates'
import type { Participant, ParticipantInput, PartyKind } from '../../types/api'

/** The party fields: shared by every participation of a party (ADR 0028). */
const PARTY_FIELDS = [
  'kind', 'title', 'first_name', 'last_name', 'organisation_name', 'name_addition',
  'email', 'phone', 'address_line1', 'address_line2', 'postal_code', 'city',
] as const

export type ParticipantFormValues = {
  /** An existing party this participation belongs to ("same person as …"); '' for a new one. */
  party: string
  kind: PartyKind
  organisation_name: string
  name_addition: string
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
    party: z.string(),
    kind: z.enum(['person', 'organisation']),
    organisation_name: z.string(),
    name_addition: z.string(),
    title: z.enum(['', 'mr', 'mrs', 'ms', 'dr', 'prof']),
    first_name: z.string(),
    last_name: z.string(),
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
    // A person needs a name, an organisation its name (the party's own rule).
    if (!values.party && values.kind === 'person') {
      for (const field of ['first_name', 'last_name'] as const) {
        if (!values[field].trim()) {
          ctx.addIssue({ code: z.ZodIssueCode.custom, path: [field], message: i18n.t('pages.participants.validation.nameRequired') })
        }
      }
    }
    if (!values.party && values.kind === 'organisation' && !values.organisation_name.trim()) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        path: ['organisation_name'],
        message: i18n.t('pages.participants.validation.organisationNameRequired'),
      })
    }
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
  party: '',
  kind: 'person',
  organisation_name: '',
  name_addition: '',
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
  valid_from: todayBusinessIso(),
  valid_to: '',
  allocation_weight: '',
}

export function mapParticipantToFormValues(participant: Participant): ParticipantFormValues {
  return {
    party: '',
    kind: participant.kind ?? 'person',
    organisation_name: participant.organisation_name || '',
    name_addition: participant.name_addition || '',
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
  const input: ParticipantInput = {
    zev: zevId,
    kind: values.kind,
    organisation_name: values.kind === 'organisation' ? values.organisation_name.trim() : '',
    name_addition: values.name_addition.trim(),
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
  if (!values.party) return input
  // A second participation of an existing party keeps that party's name and
  // address: only the participation itself is sent.
  const participation: ParticipantInput = { ...input, party: values.party }
  for (const field of PARTY_FIELDS) delete participation[field]
  return participation
}
