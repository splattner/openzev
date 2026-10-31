import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { FormModal } from '../../components/FormModal'
import { FormModalFooter } from '../../components/FormModalFooter'
import { createSupplementarySource } from '../../lib/api/supplementary'
import { formatApiError, apiErrorPayload } from '../../lib/api/errors'
import { invalidateSourceQueries } from '../../lib/supplementary'
import { useToast } from '../../lib/toast'
import type { EligibleMeteringPoint, SupplementaryProvider, SupplementarySourceInput } from '../../types/api'
import { PushTokenPanel } from './PushTokenPanel'

/**
 * What is being connected: energy data history on a held meter (the default), live data on a held
 * meter, live data on a ZEV-operated meter (manager), or the grid connection point (manager).
 */
export type SourceModalMode = 'history' | 'live' | 'zev-live' | 'connection-point'

interface Props {
    mode?: SourceModalMode
    /** The metering point; absent for the grid connection point. */
    point?: Pick<EligibleMeteringPoint, 'metering_point' | 'meter_id' | 'zev'>
    /** The ZEV, for the connection point. */
    zevId?: string
    onClose: () => void
}

type FieldErrors = Partial<Record<(typeof FIELD_KEYS)[number], string>>

const FIELD_KEYS = ['external_id', 'api_key', 'consent', 'provider'] as const
/** Fields without an input of their own: their message goes to the banner. */
const BANNER_KEYS = ['provides_live', 'provides_history', 'held_by', 'target', 'zev', 'metering_point'] as const

const LIVE_MODES: SourceModalMode[] = ['live', 'zev-live', 'connection-point']

/**
 * Connect an energy data source to one of the participant's own flagged meters.
 *
 * The consent text says what is stored, who can see it and what it is not used for. The API key is
 * write-only: it goes to the server once, never comes back, and is cleared from state on success.
 * A push source ends on a one-time token screen. Live data is push only, and a ZEV-operated meter
 * or the connection point is confirmed by the manager instead of consented to by a participant.
 */
export function SupplementarySourceModal({ mode = 'history', point, zevId, onClose }: Props) {
    const { t } = useTranslation()
    const { pushToast } = useToast()
    const queryClient = useQueryClient()

    const [provider, setProvider] = useState<SupplementaryProvider>('solar_manager')
    const [label, setLabel] = useState('')
    const [externalId, setExternalId] = useState('')
    const [apiKey, setApiKey] = useState('')
    const [consent, setConsent] = useState(false)
    const [errors, setErrors] = useState<FieldErrors>({})
    const [formError, setFormError] = useState<string | null>(null)
    const [token, setToken] = useState<string | null>(null)

    const isLive = LIVE_MODES.includes(mode)
    const zevHeld = mode === 'zev-live' || mode === 'connection-point'

    function payload(): SupplementarySourceInput {
        const base = { label: label.trim() || undefined, consent }
        if (!isLive) {
            return {
                ...base,
                metering_point: point?.metering_point,
                provider,
                external_id: provider === 'solar_manager' ? externalId.trim() : undefined,
                api_key: provider === 'solar_manager' ? apiKey.trim() : undefined,
            }
        }
        // Live is push only until Solar Manager's stream arrives; a live source provides no history.
        const live = { ...base, provider: 'push' as const, provides_history: false, provides_live: true }
        if (mode === 'live') return { ...live, metering_point: point?.metering_point, target: 'metering_point', held_by: 'participant' }
        if (mode === 'zev-live') {
            return { ...live, metering_point: point?.metering_point, target: 'metering_point', held_by: 'zev', zev: point?.zev }
        }
        return { ...live, target: 'connection_point', held_by: 'zev', zev: zevId }
    }

    const create = useMutation({
        mutationFn: () => createSupplementarySource(payload()),
        onSuccess: (created) => {
            setApiKey('')
            invalidateSourceQueries(queryClient)
            if (created.push_token) {
                setToken(created.push_token)
                return
            }
            pushToast(t(isLive ? 'supplementary.modal.liveConnected' : 'supplementary.modal.connected'), 'success')
            onClose()
        },
        onError: (error) => {
            const body = apiErrorPayload(error)
            const next: FieldErrors = {}
            for (const key of FIELD_KEYS) {
                const value = body?.[key]
                const first = Array.isArray(value) ? value[0] : value
                if (typeof first === 'string') next[key] = first
            }
            const banner: string[] = []
            for (const key of BANNER_KEYS) {
                const value = body?.[key]
                const first = Array.isArray(value) ? value[0] : value
                if (typeof first === 'string') banner.push(first)
            }
            setErrors(next)
            setFormError(banner.length ? banner.join(' ') : Object.keys(next).length ? null : formatApiError(error, t('common.error')))
        },
    })

    if (token) {
        return (
            <FormModal isOpen title={t('supplementary.modal.pushReadyTitle')} onClose={onClose}>
                <PushTokenPanel token={token} onDismiss={onClose} capabilities={{ history: !isLive, live: isLive }} />
            </FormModal>
        )
    }

    const needsCredentials = !isLive && provider === 'solar_manager'
    const ready = consent && (!needsCredentials || (externalId.trim() !== '' && apiKey.trim() !== ''))

    const modalTitle =
        mode === 'connection-point'
            ? t('supplementary.modal.connectionTitle')
            : t(mode === 'history' ? 'supplementary.modal.title' : mode === 'live' ? 'supplementary.modal.liveTitle' : 'supplementary.modal.zevLiveTitle', {
                  meter: point?.meter_id,
              })

    return (
        <FormModal isOpen title={modalTitle} onClose={onClose}>
            <form
                className="form-grid"
                onSubmit={(event) => {
                    event.preventDefault()
                    setErrors({})
                    setFormError(null)
                    create.mutate()
                }}
            >
                {isLive && (
                    <p className="muted grid-span-full m-0">
                        {t(mode === 'connection-point' ? 'supplementary.modal.connectionHint' : 'supplementary.modal.livePushHint')}
                    </p>
                )}
                {!isLive && (
                <fieldset className="grid-span-full" style={{ border: 0, padding: 0, margin: 0, display: 'grid', gap: '0.5rem' }}>
                    <legend>{t('supplementary.modal.provider')}</legend>
                    {(['solar_manager', 'push'] as const).map((choice) => (
                        <label key={choice} style={{ display: 'flex', gap: '0.6rem', alignItems: 'flex-start' }}>
                            <input
                                type="radio"
                                name="supplementary-provider"
                                checked={provider === choice}
                                onChange={() => setProvider(choice)}
                            />
                            <span>
                                <strong>{t(`supplementary.provider.${choice}`)}</strong>
                                <small className="muted" style={{ display: 'block' }}>
                                    {t(`supplementary.modal.providerHint.${choice}`)}
                                </small>
                            </span>
                        </label>
                    ))}
                    {errors.provider && <small className="field-error">{errors.provider}</small>}
                </fieldset>
                )}

                {needsCredentials && (
                    <>
                        <label>
                            <span>{t('supplementary.modal.smId')}</span>
                            <input
                                type="text"
                                value={externalId}
                                onChange={(event) => setExternalId(event.target.value)}
                                autoComplete="off"
                                maxLength={24}
                                required
                            />
                            <small className="muted">{t('supplementary.modal.smIdHint')}</small>
                            {errors.external_id && <small className="field-error">{errors.external_id}</small>}
                        </label>
                        <label>
                            <span>{t('supplementary.modal.apiKey')}</span>
                            <input
                                type="password"
                                value={apiKey}
                                onChange={(event) => setApiKey(event.target.value)}
                                autoComplete="new-password"
                                spellCheck={false}
                                required
                            />
                            <small className="muted">{t('supplementary.modal.apiKeyHint')}</small>
                            {errors.api_key && <small className="field-error">{errors.api_key}</small>}
                        </label>
                    </>
                )}

                <label className="grid-span-full">
                    <span>{t('supplementary.modal.label')}</span>
                    <input type="text" value={label} onChange={(event) => setLabel(event.target.value)} maxLength={100} />
                </label>

                <div className="grid-span-full" style={{ display: 'grid', gap: '0.5rem' }}>
                    <strong>{t(zevHeld ? 'supplementary.consent.zevTitle' : 'supplementary.consent.title')}</strong>
                    {zevHeld ? (
                        <ul className="muted" style={{ margin: 0, paddingLeft: '1.25rem' }}>
                            <li>{t('supplementary.consent.zevHeld')}</li>
                            {mode === 'connection-point' && <li>{t('supplementary.consent.connectionPoint')}</li>}
                            <li>{t('supplementary.consent.liveNotBilling')}</li>
                            <li>{t('supplementary.consent.zevRevoke')}</li>
                        </ul>
                    ) : isLive ? (
                        <ul className="muted" style={{ margin: 0, paddingLeft: '1.25rem' }}>
                            <li>{t('supplementary.consent.liveVisible')}</li>
                            <li>{t('supplementary.consent.liveNotBilling')}</li>
                            <li>{t('supplementary.consent.liveRevoke')}</li>
                        </ul>
                    ) : (
                        <ul className="muted" style={{ margin: 0, paddingLeft: '1.25rem' }}>
                            <li>{t('supplementary.consent.stored')}</li>
                            <li>{t('supplementary.consent.visible')}</li>
                            <li>{t('supplementary.consent.notBilling')}</li>
                            <li>{t('supplementary.consent.revoke')}</li>
                        </ul>
                    )}
                    <label style={{ display: 'flex', alignItems: 'flex-start', gap: '0.5rem' }}>
                        <input type="checkbox" checked={consent} onChange={(event) => setConsent(event.target.checked)} />
                        <span>{t(zevHeld ? 'supplementary.consent.zevAgree' : isLive ? 'supplementary.consent.liveAgree' : 'supplementary.consent.agree')}</span>
                    </label>
                    {errors.consent && <small className="field-error">{errors.consent}</small>}
                </div>

                {formError && (
                    <div className="error-banner grid-span-full" role="alert">
                        {formError}
                    </div>
                )}

                <FormModalFooter
                    onCancel={onClose}
                    isPending={create.isPending || !ready}
                    submitLabel={create.isPending ? t('common.saving') : t('supplementary.modal.connect')}
                />
            </form>
        </FormModal>
    )
}
