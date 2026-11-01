import { useState, type ReactNode } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { FormModal } from '../../components/FormModal'
import { FormModalCancelButton } from '../../components/FormModalFooter'
import { createSupplementarySource, updateSupplementarySource } from '../../lib/api/supplementary'
import { formatApiError, apiErrorPayload } from '../../lib/api/errors'
import { invalidateSourceQueries } from '../../lib/supplementary'
import { useToast } from '../../lib/toast'
import type { EligibleMeteringPoint, SupplementarySource, SupplementarySourceInput, SupplementarySourceUpdate } from '../../types/api'
import { PushEndpoints, PushTokenPanel } from './PushTokenPanel'

/** What a source can be connected for. Forecast is not offered yet. */
export type ConnectCapability = 'history' | 'live'

/** Whose source it is: a participant's own meter, a ZEV-operated meter (manager) or the grid connection point (manager). */
export type ConnectHolder = 'participant' | 'zev' | 'connection-point'

type ProviderChoice = 'existing' | 'solar_manager' | 'push'

interface Props {
    holder?: ConnectHolder
    /** The metering point; absent for the grid connection point. */
    point?: Pick<EligibleMeteringPoint, 'metering_point' | 'meter_id' | 'zev'>
    /** The ZEV, for the connection point. */
    zevId?: string
    /** What the point offers and does not have yet; a ZEV-operated meter and the connection point only offer live. */
    available?: ConnectCapability[]
    /** Preselected, when opened from one row's Connect. */
    initial?: ConnectCapability[]
    /** The visible sources, to find the point's push source that could take the missing capability. */
    sources?: SupplementarySource[]
    onClose: () => void
    /**
     * Where the dialog is drawn: a `FormModal` by default, or a host's own dialog whose content this
     * replaces (a host that is already a dialog must not open a second one over itself).
     */
    frame?: (title: string, body: ReactNode) => ReactNode
}

type FieldErrors = Partial<Record<(typeof FIELD_KEYS)[number], string>>

const FIELD_KEYS = ['external_id', 'api_key', 'consent', 'provider'] as const
/** Fields without an input of their own: their message goes to the banner. */
const BANNER_KEYS = ['provides_live', 'provides_history', 'held_by', 'target', 'zev', 'metering_point'] as const

const ZEV_HELD: ConnectHolder[] = ['zev', 'connection-point']

const CONSENT_ITEMS: Record<ConnectCapability, string[]> = {
    history: ['stored', 'visible', 'notBilling', 'revoke'],
    live: ['liveVisible', 'liveNotBilling', 'liveRevoke'],
}

/** The first message of a field error, whether the API sent a list or a string. */
function firstMessage(body: Record<string, unknown> | null | undefined, key: string): string | undefined {
    const value = body?.[key]
    const first = Array.isArray(value) ? value[0] : value
    return typeof first === 'string' ? first : undefined
}

/**
 * Connect energy data to a metering point in one flow: what (history, live or both), how (Solar
 * Manager, a new push source, or the push source the meter already has) and the consent for exactly
 * what was chosen. One source is created with all chosen capabilities in a single request.
 *
 * The consent text says what is stored, who can see it and what it is not used for. The API key is
 * write-only: it goes to the server once, never comes back, and is cleared from state on success.
 * A new push source ends on a one-time token screen; an existing one on its endpoints. A ZEV-operated
 * meter or the connection point is confirmed by the manager instead of consented to by a participant.
 */
export function SupplementarySourceModal({ holder = 'participant', point, zevId, available, initial, sources, onClose, frame }: Props) {
    const { t } = useTranslation()
    const { pushToast } = useToast()
    const queryClient = useQueryClient()

    const zevHeld = ZEV_HELD.includes(holder)
    const offered: ConnectCapability[] = zevHeld ? ['live'] : available?.length ? available : ['history']
    const [chosen, setChosen] = useState<ConnectCapability[]>(() => (zevHeld ? ['live'] : (initial?.length ? initial : offered)))
    const [step, setStep] = useState<'what' | 'how'>(offered.length > 1 ? 'what' : 'how')
    const [provider, setProvider] = useState<ProviderChoice | null>(null)
    const [label, setLabel] = useState('')
    const [externalId, setExternalId] = useState('')
    const [apiKey, setApiKey] = useState('')
    const [consent, setConsent] = useState(false)
    const [errors, setErrors] = useState<FieldErrors>({})
    const [formError, setFormError] = useState<string | null>(null)
    const [token, setToken] = useState<string | null>(null)
    const [reused, setReused] = useState<SupplementarySource | null>(null)

    const history = chosen.includes('history')
    const live = chosen.includes('live')
    const existing =
        holder === 'participant' && point
            ? sources?.find((s) => s.metering_point === point.metering_point && s.provider === 'push' && s.enabled && s.held_by === 'participant')
            : undefined
    // Solar Manager only provides history until its stream arrives; a push source can provide any.
    const providers: ProviderChoice[] = zevHeld
        ? ['push']
        : [...(existing && chosen.length ? (['existing'] as const) : []), ...(!live ? (['solar_manager'] as const) : []), 'push']
    const chosenProvider: ProviderChoice = provider && providers.includes(provider) ? provider : providers[0]
    const useExisting = chosenProvider === 'existing'
    const needsCredentials = chosenProvider === 'solar_manager'

    function toggle(capability: ConnectCapability) {
        setChosen((current) => (current.includes(capability) ? current.filter((c) => c !== capability) : [...current, capability]))
    }

    function createPayload(): SupplementarySourceInput {
        const base = { label: label.trim() || undefined, consent }
        if (holder === 'connection-point') {
            return { ...base, provider: 'push', provides_history: false, provides_live: true, target: 'connection_point', held_by: 'zev', zev: zevId }
        }
        if (holder === 'zev') {
            return { ...base, provider: 'push', provides_history: false, provides_live: true, metering_point: point?.metering_point, target: 'metering_point', held_by: 'zev', zev: point?.zev }
        }
        return {
            ...base,
            metering_point: point?.metering_point,
            target: 'metering_point',
            held_by: 'participant',
            provider: chosenProvider === 'solar_manager' ? 'solar_manager' : 'push',
            provides_history: history,
            provides_live: live,
            external_id: needsCredentials ? externalId.trim() : undefined,
            api_key: needsCredentials ? apiKey.trim() : undefined,
        }
    }

    function showErrors(error: unknown) {
        const body = apiErrorPayload(error)
        const next: FieldErrors = {}
        for (const key of FIELD_KEYS) {
            const message = firstMessage(body, key)
            if (message) next[key] = message
        }
        const banner = BANNER_KEYS.map((key) => firstMessage(body, key)).filter((message): message is string => !!message)
        setErrors(next)
        setFormError(banner.length ? banner.join(' ') : Object.keys(next).length ? null : formatApiError(error, t('common.error')))
    }

    const create = useMutation({
        mutationFn: () => createSupplementarySource(createPayload()),
        onSuccess: (created) => {
            setApiKey('')
            invalidateSourceQueries(queryClient)
            if (created.push_token) {
                setToken(created.push_token)
                return
            }
            pushToast(t(live && !history ? 'supplementary.modal.liveConnected' : 'supplementary.modal.connected'), 'success')
            onClose()
        },
        onError: showErrors,
    })

    // The point's own push source takes the new capability: no new token, the same one keeps working.
    const extend = useMutation({
        mutationFn: () => {
            const update: SupplementarySourceUpdate = { consent }
            if (history) update.provides_history = true
            if (live) update.provides_live = true
            return updateSupplementarySource(existing!.id, update)
        },
        onSuccess: (updated) => {
            invalidateSourceQueries(queryClient)
            setReused(updated)
        },
        onError: showErrors,
    })

    const wrap = (title: string, body: ReactNode) =>
        frame ? frame(title, body) : (
            <FormModal isOpen size="md" title={title} onClose={onClose}>
                {body}
            </FormModal>
        )

    if (token) {
        return wrap(
            t('supplementary.modal.pushReadyTitle'),
            <PushTokenPanel token={token} onDismiss={onClose} capabilities={{ history, live }} />,
        )
    }
    if (reused) {
        return wrap(
            t('supplementary.modal.existingReadyTitle'),
            <div style={{ display: 'grid', gap: '0.75rem' }}>
                <p className="m-0">{t('supplementary.modal.existingReadyBody', { token: `ozs_${reused.push_token_prefix}_…` })}</p>
                <PushEndpoints capabilities={{ history: reused.provides_history, live: reused.provides_live }} />
                <div className="dialog-actions">
                    <button type="button" className="button button-primary" onClick={onClose}>
                        {t('common.close')}
                    </button>
                </div>
            </div>,
        )
    }

    const title =
        holder === 'connection-point'
            ? t('supplementary.modal.connectionTitle')
            : t(holder === 'zev' ? 'supplementary.modal.zevLiveTitle' : 'supplementary.modal.title', { meter: point?.meter_id })

    if (step === 'what') {
        return wrap(
            title,
            <form
                className="form-grid"
                onSubmit={(event) => {
                    event.preventDefault()
                    setStep('how')
                }}
            >
                <fieldset className="grid-span-full" style={{ border: 0, padding: 0, margin: 0, display: 'grid', gap: '0.5rem' }}>
                    <legend>{t('supplementary.modal.what')}</legend>
                    {offered.map((capability) => (
                        <label key={capability} style={{ display: 'flex', gap: '0.6rem', alignItems: 'flex-start' }}>
                            <input type="checkbox" name="supplementary-capability" checked={chosen.includes(capability)} onChange={() => toggle(capability)} />
                            <span>
                                <strong>{t(`supplementary.capability.${capability}`)}</strong>
                                <small className="muted" style={{ display: 'block' }}>
                                    {t(`supplementary.modal.capabilityHint.${capability}`)}
                                </small>
                            </span>
                        </label>
                    ))}
                </fieldset>
                <div className="dialog-actions grid-span-full mt-1">
                    <FormModalCancelButton onCancel={onClose} />
                    <button className="button button-primary" type="submit" disabled={chosen.length === 0}>
                        {t('supplementary.modal.next')}
                    </button>
                </div>
            </form>,
        )
    }

    const consentKeys = (['history', 'live'] as const).filter((capability) => chosen.includes(capability)).flatMap((capability) => CONSENT_ITEMS[capability])
    const agreeKey = zevHeld
        ? 'supplementary.consent.zevAgree'
        : history && live ? 'supplementary.consent.bothAgree' : live ? 'supplementary.consent.liveAgree' : 'supplementary.consent.agree'
    const pending = create.isPending || extend.isPending
    const ready = consent && chosen.length > 0 && (!needsCredentials || (externalId.trim() !== '' && apiKey.trim() !== ''))

    return wrap(
        title,
        <form
            className="form-grid"
            onSubmit={(event) => {
                event.preventDefault()
                setErrors({})
                setFormError(null)
                if (useExisting) extend.mutate()
                else create.mutate()
            }}
        >
            {zevHeld && (
                <p className="muted grid-span-full m-0">
                    {t(holder === 'connection-point' ? 'supplementary.modal.connectionHint' : 'supplementary.modal.livePushHint')}
                </p>
            )}
            {!zevHeld && (
                <fieldset className="grid-span-full" style={{ border: 0, padding: 0, margin: 0, display: 'grid', gap: '0.5rem' }}>
                    <legend>{t('supplementary.modal.provider')}</legend>
                    {providers.map((choice) => (
                        <label key={choice} style={{ display: 'flex', gap: '0.6rem', alignItems: 'flex-start' }}>
                            <input type="radio" name="supplementary-provider" checked={chosenProvider === choice} onChange={() => setProvider(choice)} />
                            <span>
                                <strong>{choice === 'existing' ? t('supplementary.modal.existingPush') : t(`supplementary.provider.${choice}`)}</strong>
                                <small className="muted" style={{ display: 'block' }}>
                                    {choice === 'existing' ? t('supplementary.modal.existingPushHint') : t(`supplementary.modal.providerHint.${choice}`)}
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
                        <input type="text" value={externalId} onChange={(event) => setExternalId(event.target.value)} autoComplete="off" maxLength={24} required />
                        <small className="muted">{t('supplementary.modal.smIdHint')}</small>
                        {errors.external_id && <small className="field-error">{errors.external_id}</small>}
                    </label>
                    <label>
                        <span>{t('supplementary.modal.apiKey')}</span>
                        <input type="password" value={apiKey} onChange={(event) => setApiKey(event.target.value)} autoComplete="new-password" spellCheck={false} required />
                        <small className="muted">{t('supplementary.modal.apiKeyHint')}</small>
                        {errors.api_key && <small className="field-error">{errors.api_key}</small>}
                    </label>
                </>
            )}

            {!useExisting && (
                <label className="grid-span-full">
                    <span>{t('supplementary.modal.label')}</span>
                    <input type="text" value={label} onChange={(event) => setLabel(event.target.value)} maxLength={100} />
                </label>
            )}

            <div className="grid-span-full" style={{ display: 'grid', gap: '0.5rem' }}>
                <strong>{t(zevHeld ? 'supplementary.consent.zevTitle' : 'supplementary.consent.title')}</strong>
                <ul className="muted" style={{ margin: 0, paddingLeft: '1.25rem' }}>
                    {zevHeld ? (
                        <>
                            <li>{t('supplementary.consent.zevHeld')}</li>
                            {holder === 'connection-point' && <li>{t('supplementary.consent.connectionPoint')}</li>}
                            <li>{t('supplementary.consent.liveNotBilling')}</li>
                            <li>{t('supplementary.consent.zevRevoke')}</li>
                        </>
                    ) : (
                        consentKeys.map((key) => <li key={key}>{t(`supplementary.consent.${key}`)}</li>)
                    )}
                </ul>
                <label style={{ display: 'flex', alignItems: 'flex-start', gap: '0.5rem' }}>
                    <input type="checkbox" checked={consent} onChange={(event) => setConsent(event.target.checked)} />
                    <span>{t(agreeKey)}</span>
                </label>
                {errors.consent && <small className="field-error">{errors.consent}</small>}
            </div>

            {formError && (
                <div className="error-banner grid-span-full" role="alert">
                    {formError}
                </div>
            )}

            <div className="dialog-actions grid-span-full mt-1">
                <FormModalCancelButton onCancel={onClose} />
                {offered.length > 1 && (
                    <button type="button" className="button button-secondary" onClick={() => setStep('what')}>
                        {t('supplementary.modal.back')}
                    </button>
                )}
                <button className="button button-primary" type="submit" disabled={pending || !ready}>
                    {pending ? t('common.saving') : t('supplementary.modal.connect')}
                </button>
            </div>
        </form>,
    )
}
