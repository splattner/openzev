import type { Participant } from '../../types/api'

export type ParticipantIssue = 'noEmail' | 'noAddress' | 'noMeteringPoint'

/** What a participant still lacks for billing and invoice delivery. */
export function participantIssues(participant: Participant): ParticipantIssue[] {
    const issues: ParticipantIssue[] = []
    if (!participant.email) issues.push('noEmail')
    if (!(participant.address_line1 && participant.postal_code && participant.city)) issues.push('noAddress')
    if (!participant.has_metering_point_assignment) issues.push('noMeteringPoint')
    return issues
}
