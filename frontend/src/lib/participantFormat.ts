import type { Participant } from '../types/api'

export function formatParticipantName(participant: Participant, titleLabel?: string): string {
    return [titleLabel, participant.first_name, participant.last_name].filter(Boolean).join(' ')
}
