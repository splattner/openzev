import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useState, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { FormModal } from '../../components/FormModal'
import { FormModalCancelButton } from '../../components/FormModalFooter'
import { apiErrorPayload, formatApiError } from '../../lib/api/errors'
import { createSupplementarySource, updateSupplementarySource } from '../../lib/api/supplementary'
import { invalidateSourceQueries } from '../../lib/supplementary'
import { useToast } from '../../lib/toast'
import type { ConnectHolder } from './SupplementarySourceModal'
import type { EligibleMeteringPoint, SupplementarySource } from '../../types/api'

interface Props {
    holder: Extract<ConnectHolder, 'participant' | 'zev'>
    point: Pick<EligibleMeteringPoint, 'metering_point' | 'meter_id' | 'zev'>
    /** The visible sources: a holder's Solar Manager connection on this meter can provide the forecast too. */
    sources?: SupplementarySource[]
    onClose: () => void
    /** A host that already is a dialog draws the flow in its own frame instead of opening a second one. */
    frame?: (title: string, body: ReactNode) => ReactNode
}

/** The first message under any of the keys the API may put a forecast problem on. */
function firstProblem(error: unknown): string | undefined {
    const body = apiErrorPayload(error)
    for (const key of ['provides_forecast', 'consent', 'metering_point', 'provider', 'held_by', 'detail']) {
        const value = body?.[key]
        const first = Array.isArray(value) ? value[0] : value
        if (typeof first === 'string') return first
    }
    return undefined
}

/**
 * Connect the free forecast.solar forecast to a producing metering point. There is nothing to sign in
 * to and nothing personal to consent to: only the plant's roof planes and the building's location,
 * rounded to about a kilometre, leave the instance. A plant without planes or location is refused
 * by the server with a message that says what to add first.
 */
export function ForecastConnectDialog({ holder, point, sources, onClose, frame }: Props) {
    const { t } = useTranslation()
    const { pushToast } = useToast()
    const queryClient = useQueryClient()
    const [error, setError] = useState<string | null>(null)
    const [consent, setConsent] = useState(false)

    // A holder's Solar Manager connection that still works can read its own forecast with the stored key.
    const existing =
        holder === 'participant'
            ? sources?.find(
                  (source) =>
                      source.metering_point === point.metering_point && source.provider === 'solar_manager' && source.held_by === 'participant' &&
                      source.enabled && source.has_credential && source.status !== 'reconnect_required' && !source.provides_forecast,
              )
            : undefined
    const [choice, setChoice] = useState<'solar_manager' | 'forecast_solar'>('solar_manager')
    const useExisting = !!existing && choice === 'solar_manager'

    const connect = useMutation({
        mutationFn: () =>
            useExisting
                ? updateSupplementarySource(existing.id, { provides_forecast: true, consent: true })
                : createSupplementarySource({
                provider: 'forecast_solar',
                metering_point: point.metering_point,
                provides_history: false,
                provides_live: false,
                provides_forecast: true,
                target: 'metering_point',
                held_by: holder,
                zev: holder === 'zev' ? point.zev : undefined,
                consent: false,
            }),
        onSuccess: () => {
            pushToast(t(useExisting ? 'supplementary.forecast.alsoUseDone' : 'supplementary.forecast.connected'), 'success')
            invalidateSourceQueries(queryClient)
            onClose()
        },
        onError: (failure) => setError(firstProblem(failure) ?? formatApiError(failure, t('common.error'))),
    })

    const title = t('supplementary.forecast.connectTitle', { meter: point.meter_id })
    const body = (
        <div style={{ display: 'grid', gap: '1rem' }}>
            {existing && (
                <fieldset style={{ border: 0, padding: 0, margin: 0, display: 'grid', gap: '0.5rem' }}>
                    <legend className="muted" style={{ padding: 0 }}>{t('supplementary.forecast.source')}</legend>
                    <label className="actions-row">
                        <input type="radio" name="forecast-source" checked={choice === 'solar_manager'} onChange={() => setChoice('solar_manager')} />
                        <span>{t('supplementary.forecast.choiceSolarManager')}</span>
                    </label>
                    <label className="actions-row">
                        <input type="radio" name="forecast-source" checked={choice === 'forecast_solar'} onChange={() => setChoice('forecast_solar')} />
                        <span>{t('supplementary.forecast.choiceForecastSolar')}</span>
                    </label>
                </fieldset>
            )}
            {useExisting ? (
                <>
                    <p className="m-0">{t('supplementary.forecast.confirm.alsoMessage')}</p>
                    <label className="actions-row">
                        <input type="checkbox" checked={consent} onChange={(event) => setConsent(event.target.checked)} />
                        <span>{t('supplementary.forecast.consentAgree')}</span>
                    </label>
                </>
            ) : (
                <>
                    <p className="m-0">{t('supplementary.forecast.intro')}</p>
                    <p className="muted m-0">{t('supplementary.forecast.privacy')}</p>
                    <p className="muted m-0">{t(holder === 'zev' ? 'supplementary.forecast.needsManager' : 'supplementary.forecast.needsParticipant')}</p>
                    {holder === 'participant' && !existing && <p className="muted m-0">{t('supplementary.forecast.solarManagerHint')}</p>}
                </>
            )}
            {error && <div className="error-banner" role="alert">{error}</div>}
            <div className="actions-row actions-row-wrap">
                <button type="button" className="button button-primary" disabled={connect.isPending || (useExisting && !consent)} onClick={() => connect.mutate()}>
                    {connect.isPending ? t('common.saving') : t('supplementary.forecast.connect')}
                </button>
                <FormModalCancelButton onCancel={onClose} disabled={connect.isPending} />
            </div>
        </div>
    )
    if (frame) return <>{frame(title, body)}</>
    return (
        <FormModal isOpen size="md" title={title} onClose={onClose}>
            {body}
        </FormModal>
    )
}
