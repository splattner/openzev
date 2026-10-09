import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { FormModal } from '../../components/FormModal'
import { FormModalFooter } from '../../components/FormModalFooter'
import { createSupplementarySource } from '../../lib/api/supplementary'
import { formatApiError, apiErrorPayload } from '../../lib/api/errors'
import { queryKeys } from '../../lib/api/queryKeys'
import { useToast } from '../../lib/toast'
import type { EligibleMeteringPoint, SupplementaryProvider } from '../../types/api'
import { PushTokenPanel } from '../supplementary/PushTokenPanel'

interface Props {
    point: EligibleMeteringPoint
    onClose: () => void
}

type FieldErrors = Partial<Record<'external_id' | 'api_key' | 'consent' | 'provider', string>>

const FIELD_KEYS = ['external_id', 'api_key', 'consent', 'provider'] as const

/**
 * Connect an energy data source to one of the participant's own flagged meters.
 *
 * The consent text says what is stored, who can see it and what it is not used for. The API key is
 * write-only: it goes to the server once, never comes back, and is cleared from state on success.
 * A push source ends on a one-time token screen.
 */
export function SupplementarySourceModal({ point, onClose }: Props) {
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

    const create = useMutation({
        mutationFn: () =>
            createSupplementarySource({
                metering_point: point.metering_point,
                provider,
                label: label.trim() || undefined,
                external_id: provider === 'solar_manager' ? externalId.trim() : undefined,
                api_key: provider === 'solar_manager' ? apiKey.trim() : undefined,
                consent,
            }),
        onSuccess: (created) => {
            setApiKey('')
            void queryClient.invalidateQueries({ queryKey: queryKeys.metering.supplementarySources() })
            void queryClient.invalidateQueries({ queryKey: queryKeys.metering.supplementaryEligible() })
            void queryClient.invalidateQueries({ queryKey: ['metering', 'dashboard-summary'] })
            if (created.push_token) {
                setToken(created.push_token)
                return
            }
            pushToast(t('supplementary.modal.connected'), 'success')
            onClose()
        },
        onError: (error) => {
            const payload = apiErrorPayload(error)
            const next: FieldErrors = {}
            for (const key of FIELD_KEYS) {
                const value = payload?.[key]
                const first = Array.isArray(value) ? value[0] : value
                if (typeof first === 'string') next[key] = first
            }
            setErrors(next)
            setFormError(Object.keys(next).length ? null : formatApiError(error, t('common.error')))
        },
    })

    if (token) {
        return (
            <FormModal isOpen title={t('supplementary.modal.pushReadyTitle')} onClose={onClose}>
                <PushTokenPanel token={token} onDismiss={onClose} />
            </FormModal>
        )
    }

    const needsCredentials = provider === 'solar_manager'
    const ready = consent && (!needsCredentials || (externalId.trim() !== '' && apiKey.trim() !== ''))

    return (
        <FormModal isOpen title={t('supplementary.modal.title', { meter: point.meter_id })} onClose={onClose}>
            <form
                className="form-grid"
                onSubmit={(event) => {
                    event.preventDefault()
                    setErrors({})
                    setFormError(null)
                    create.mutate()
                }}
            >
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
                    <strong>{t('supplementary.consent.title')}</strong>
                    <ul className="muted" style={{ margin: 0, paddingLeft: '1.25rem' }}>
                        <li>{t('supplementary.consent.stored')}</li>
                        <li>{t('supplementary.consent.visible')}</li>
                        <li>{t('supplementary.consent.notBilling')}</li>
                        <li>{t('supplementary.consent.revoke')}</li>
                    </ul>
                    <label style={{ display: 'flex', alignItems: 'flex-start', gap: '0.5rem' }}>
                        <input type="checkbox" checked={consent} onChange={(event) => setConsent(event.target.checked)} />
                        <span>{t('supplementary.consent.agree')}</span>
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
