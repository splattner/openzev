import type { Participant } from '../types/api'

/** The name a participant is billed under: an organisation's name, or the person's (with title). */
export function formatParticipantName(participant: Participant, titleLabel?: string): string {
    if (participant.kind === 'organisation' && participant.organisation_name) return participant.organisation_name
    return [titleLabel, participant.first_name, participant.last_name].filter(Boolean).join(' ')
}
