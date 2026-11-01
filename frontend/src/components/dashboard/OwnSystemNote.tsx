import { Link } from 'react-router-dom'
import { useTranslation } from 'react-i18next'

/**
 * Where the own-system card used to be on Energy balance: the figures of a participant's own system
 * (Solar Manager, push) now live on "My energy system". Carries the page's period (and the selected
 * participant) over, so the link opens the same view.
 */
export function OwnSystemNote({ period, participantId }: { period?: { from: string; to: string }; participantId?: string }) {
    const { t } = useTranslation()
    const params = new URLSearchParams({ range: 'period' })
    if (period?.from && period.to) {
        params.set('period_start', period.from)
        params.set('period_end', period.to)
    }
    if (participantId) params.set('participant', participantId)
    return (
        <p className="muted">
            {t(participantId ? 'myEnergy.balanceNoteParticipant' : 'myEnergy.balanceNote')}{' '}
            <Link to={`/my-energy?${params.toString()}`}>{t('myEnergy.balanceNoteLink')}</Link>
        </p>
    )
}
