import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'
import { FilterTabs } from '../../components/FilterTabs'
import { SecretReveal } from '../../components/SecretReveal'
import { PushTokenPanel } from '../supplementary/PushTokenPanel'
import { API_BASE_URL } from '../../lib/api/client'
import { createApiKey } from '../../lib/api/auth'
import { createAnalyticsToken, fetchMyCredentials, revokeCredential } from '../../lib/api/credentials'
import { formatApiError } from '../../lib/api/errors'
import { queryKeys } from '../../lib/api/queryKeys'
import { rotateSupplementaryPushToken } from '../../lib/api/supplementary'
import { fetchZevs } from '../../lib/api/zev'
import { formatDateTime, useAppSettings } from '../../lib/appSettings'
import { useAuth } from '../../lib/auth'
import { useToast } from '../../lib/toast'
import type { AccessCredential, ApiKeyWithSecret } from '../../types/api'
import { apiKeyStatus, expiryFromDays } from './apiKeyStatus'
import {
    analyticsScopeOptions,
    credentialCounts,
    filterCredentials,
    type CredentialFilter,
} from './credentials'

const EXPIRY_CHOICES: Array<{ days: number | null; labelKey: string }> = [
    { days: 30, labelKey: 'account.apiKeys.expiry30' },
    { days: 90, labelKey: 'account.apiKeys.expiry90' },
    { days: 365, labelKey: 'account.apiKeys.expiry365' },
    { days: null, labelKey: 'account.apiKeys.expiryNever' },
]

type Creating = null | 'api_key' | 'analytics'

type FreshSecret =
    | { kind: 'api_key'; secret: string }
    | { kind: 'analytics'; secret: string }
    | { kind: 'energy_push'; secret: string }

interface Props {
    onRevoke: (options: { name: string; kind: AccessCredential['kind']; onConfirm: () => void }) => void
    onRotate: (options: { name: string; onConfirm: () => void }) => void
}

function seriesUrl(): string {
    const origin = typeof window === 'undefined' ? '' : window.location.origin
    const base = /^https?:\/\//.test(API_BASE_URL) ? API_BASE_URL : `${origin}${API_BASE_URL}`
    return `${base.replace(/\/+$/, '')}/analytics/series/`
}

/**
 * Tokens & keys: the account's API keys, analytics tokens and energy data push
 * tokens in one list (SPEC-2026-tokens-and-keys). API keys and analytics tokens
 * are created here; an energy data token is created with its source, so it is
 * only listed (and rotated or revoked) here.
 */
export function TokensSection({ onRevoke, onRotate }: Props) {
    const { t } = useTranslation()
    const { settings } = useAppSettings()
    const { pushToast } = useToast()
    const { user } = useAuth()
    const queryClient = useQueryClient()

    const [filter, setFilter] = useState<CredentialFilter>('all')
    const [creating, setCreating] = useState<Creating>(null)
    // Held in component state only, and only until dismissed: the backend stores a hash.
    const [fresh, setFresh] = useState<FreshSecret | null>(null)

    const query = useQuery({ queryKey: queryKeys.auth.credentials(), queryFn: fetchMyCredentials })
    const credentials = query.data?.credentials ?? []
    const canCreateAnalytics = query.data?.can_create.analytics ?? false
    const counts = credentialCounts(credentials)
    const visible = filterCredentials(credentials, filter)

    function refresh() {
        void queryClient.invalidateQueries({ queryKey: queryKeys.auth.credentials() })
        void queryClient.invalidateQueries({ queryKey: queryKeys.auth.apiKeys() })
        void queryClient.invalidateQueries({ queryKey: queryKeys.metering.supplementarySources() })
    }

    const revoke = useMutation({
        mutationFn: (credential: AccessCredential) => revokeCredential(credential),
        onSuccess: () => {
            refresh()
            pushToast(t('account.tokens.revokeSuccess'), 'success')
        },
        onError: (error) => pushToast(formatApiError(error, t('common.error')), 'error'),
    })

    const rotate = useMutation({
        mutationFn: (credential: AccessCredential) => rotateSupplementaryPushToken(credential.id),
        onSuccess: (data) => {
            refresh()
            setFresh({ kind: 'energy_push', secret: data.push_token })
        },
        onError: (error) => pushToast(formatApiError(error, t('common.error')), 'error'),
    })

    const tabs = [
        { value: 'all' as const, label: t('account.tokens.filterAll'), count: counts.all },
        { value: 'api_key' as const, label: t('account.tokens.kind.api_key'), count: counts.api_key },
        { value: 'analytics' as const, label: t('account.tokens.kind.analytics'), count: counts.analytics },
        { value: 'energy_push' as const, label: t('account.tokens.kind.energy_push'), count: counts.energy_push },
    ]

    function scopeLine(credential: AccessCredential): string | null {
        const { scope } = credential
        const parts = [
            scope.zev_name,
            scope.participant ? t('account.tokens.scopeOnlyMine') : scope.zev ? t('account.tokens.scopeWholeZev') : null,
            scope.meter_id,
        ].filter(Boolean)
        return parts.length ? parts.join(' · ') : null
    }

    return (
        <div className="card">
            <h2>{t('account.tokens.section')}</h2>
            <p className="muted" style={{ marginBottom: '1.5rem' }}>{t('account.tokens.description')}</p>

            {fresh?.kind === 'api_key' && (
                <SecretReveal
                    secret={fresh.secret}
                    testId="api-key-secret"
                    onDismiss={() => setFresh(null)}
                    title={t('account.apiKeys.secretShownOnceTitle')}
                    body={t('account.apiKeys.secretShownOnceBody')}
                    labels={{
                        copy: t('account.apiKeys.copy'),
                        copied: t('account.apiKeys.copied'),
                        dismiss: t('account.apiKeys.dismissSecret'),
                        copyFailed: t('account.apiKeys.copyFailed'),
                    }}
                />
            )}
            {fresh?.kind === 'analytics' && (
                <SecretReveal
                    secret={fresh.secret}
                    testId="analytics-token-secret"
                    onDismiss={() => setFresh(null)}
                    title={t('account.tokens.analytics.shownOnceTitle')}
                    body={t('account.tokens.analytics.shownOnceBody')}
                >
                    <div style={{ display: 'grid', gap: '0.35rem' }}>
                        <strong>{t('account.tokens.analytics.usage')}</strong>
                        <code style={{ wordBreak: 'break-all' }}>
                            {`curl -H "Authorization: Bearer ${fresh.secret}" "${seriesUrl()}?from=2026-01-01&to=2026-01-31"`}
                        </code>
                        <small className="muted">{t('account.tokens.analytics.usageHint')}</small>
                    </div>
                </SecretReveal>
            )}
            {fresh?.kind === 'energy_push' && <PushTokenPanel token={fresh.secret} onDismiss={() => setFresh(null)} />}

            {creating === 'api_key' && (
                <CreateApiKeyForm
                    onCancel={() => setCreating(null)}
                    onCreated={(created) => {
                        setCreating(null)
                        setFresh({ kind: 'api_key', secret: created.key })
                        refresh()
                    }}
                />
            )}
            {creating === 'analytics' && (
                <CreateAnalyticsTokenForm
                    onCancel={() => setCreating(null)}
                    onCreated={(secret) => {
                        setCreating(null)
                        setFresh({ kind: 'analytics', secret })
                        refresh()
                    }}
                    memberships={user?.memberships}
                    user={user}
                />
            )}

            {creating === null && (
                <div className="actions-row actions-row-wrap" style={{ marginBottom: '1.5rem' }}>
                    <button type="button" className="button button-primary" onClick={() => setCreating('api_key')}>
                        {t('account.tokens.newApiKey')}
                    </button>
                    {canCreateAnalytics && (
                        <button type="button" className="button button-secondary" onClick={() => setCreating('analytics')}>
                            {t('account.tokens.newAnalytics')}
                        </button>
                    )}
                    <Link className="button button-secondary" style={{ textDecoration: 'none' }} to="/me/metering-points">
                        {t('account.tokens.energyDataLink')}
                    </Link>
                </div>
            )}
            {creating === null && <small className="muted" style={{ display: 'block', marginBottom: '1rem' }}>{t('account.tokens.energyDataHint')}</small>}

            <FilterTabs label={t('account.tokens.filterLabel')} tabs={tabs} value={filter} onChange={setFilter} />

            {query.isLoading && <p className="muted">{t('common.loading')}</p>}
            {query.isError && <p className="muted" role="alert">{t('common.error')}</p>}
            {!query.isLoading && !query.isError && credentials.length === 0 && (
                <p className="muted">{t('account.tokens.empty')}</p>
            )}

            <ul style={{ listStyle: 'none', margin: 0, padding: 0 }}>
                {visible.map((credential) => {
                    const status = credential.expires_at ? apiKeyStatus(credential) : 'active'
                    const scope = scopeLine(credential)
                    return (
                        <li
                            key={`${credential.kind}:${credential.id}`}
                            data-testid={`credential-${credential.kind}`}
                            style={{
                                display: 'flex',
                                flexWrap: 'wrap',
                                alignItems: 'center',
                                justifyContent: 'space-between',
                                gap: '0.75rem 1rem',
                                padding: '0.75rem 0',
                                borderBottom: '1px solid var(--border)',
                            }}
                        >
                            <div style={{ minWidth: 0, flex: '1 1 16rem' }}>
                                <strong>{credential.name}</strong>
                                <span className="badge" style={{ marginLeft: '0.5rem' }}>
                                    {t(`account.tokens.kind.${credential.kind}`)}
                                </span>
                                <span className="badge" style={{ marginLeft: '0.5rem' }}>
                                    {t(`account.tokens.access.${credential.access}`)}
                                </span>
                                {status !== 'active' && (
                                    <span
                                        className="badge"
                                        style={{ marginLeft: '0.5rem', background: 'var(--warning-100)', color: 'var(--warning-800)' }}
                                    >
                                        {t(status === 'expired' ? 'account.apiKeys.expiredBadge' : 'account.apiKeys.expiringBadge')}
                                    </span>
                                )}
                                {scope && <small className="muted" style={{ display: 'block' }}>{scope}</small>}
                                <small className="muted" style={{ display: 'block' }}>
                                    <code>{credential.prefix}…</code>
                                    {' · '}
                                    {credential.created_at
                                        ? t('account.apiKeys.createdOn', { date: formatDateTime(credential.created_at, settings) })
                                        : t('account.tokens.createdUnknown')}
                                    {' · '}
                                    {credential.last_used_at
                                        ? t('account.apiKeys.lastUsed', { date: formatDateTime(credential.last_used_at, settings) })
                                        : t('account.apiKeys.neverUsed')}
                                    {' · '}
                                    {credential.expires_at
                                        ? t('account.apiKeys.expiresOn', { date: formatDateTime(credential.expires_at, settings) })
                                        : t('account.apiKeys.noExpiry')}
                                </small>
                            </div>
                            <div className="actions-row actions-row-wrap">
                                {credential.manage_url && (
                                    <Link
                                        className="button button-secondary button-compact"
                                        style={{ textDecoration: 'none' }}
                                        to={credential.manage_url}
                                    >
                                        {t('account.tokens.manageSource')}
                                    </Link>
                                )}
                                {credential.actions.includes('rotate') && (
                                    <button
                                        type="button"
                                        className="button button-secondary button-compact"
                                        disabled={rotate.isPending}
                                        onClick={() => onRotate({ name: credential.name, onConfirm: () => rotate.mutate(credential) })}
                                    >
                                        {t('account.tokens.rotate')}
                                    </button>
                                )}
                                {credential.actions.includes('revoke') && (
                                    <button
                                        type="button"
                                        className="button button-danger button-compact"
                                        disabled={revoke.isPending}
                                        aria-label={t('account.tokens.revokeNamed', { name: credential.name })}
                                        onClick={() =>
                                            onRevoke({
                                                name: credential.name,
                                                kind: credential.kind,
                                                onConfirm: () => revoke.mutate(credential),
                                            })
                                        }
                                    >
                                        {t('account.apiKeys.revoke')}
                                    </button>
                                )}
                            </div>
                        </li>
                    )
                })}
            </ul>
        </div>
    )
}

function ExpirySelect({ value, onChange }: { value: number | null; onChange: (days: number | null) => void }) {
    const { t } = useTranslation()
    return (
        <label>
            <span>{t('account.apiKeys.expiryLabel')}</span>
            <select
                value={value === null ? 'never' : String(value)}
                onChange={(event) => onChange(event.target.value === 'never' ? null : Number(event.target.value))}
            >
                {EXPIRY_CHOICES.map((choice) => (
                    <option key={choice.labelKey} value={choice.days === null ? 'never' : String(choice.days)}>
                        {t(choice.labelKey)}
                    </option>
                ))}
            </select>
        </label>
    )
}

function CreateApiKeyForm({ onCancel, onCreated }: { onCancel: () => void; onCreated: (key: ApiKeyWithSecret) => void }) {
    const { t } = useTranslation()
    const { pushToast } = useToast()
    const [name, setName] = useState('')
    const [readOnly, setReadOnly] = useState(false)
    const [expiryDays, setExpiryDays] = useState<number | null>(365)

    const create = useMutation({
        mutationFn: () => createApiKey({ name: name.trim(), read_only: readOnly, expires_at: expiryFromDays(expiryDays) }),
        onSuccess: onCreated,
        onError: (error: any) => {
            const data = error.response?.data
            pushToast(data?.detail ?? data?.name?.[0] ?? data?.expires_at?.[0] ?? t('common.error'), 'error')
        },
    })

    return (
        <form
            onSubmit={(event) => {
                event.preventDefault()
                if (!name.trim()) {
                    pushToast(t('account.apiKeys.nameRequired'), 'error')
                    return
                }
                create.mutate()
            }}
            style={{ marginBottom: '1.5rem' }}
        >
            <h3>{t('account.tokens.newApiKey')}</h3>
            <p className="muted">{t('account.apiKeys.description')}</p>
            <label>
                <span>{t('account.apiKeys.nameLabel')}</span>
                <input
                    type="text"
                    value={name}
                    onChange={(event) => setName(event.target.value)}
                    placeholder={t('account.apiKeys.namePlaceholder')}
                />
            </label>
            <ExpirySelect value={expiryDays} onChange={setExpiryDays} />
            <label style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                <input type="checkbox" checked={readOnly} onChange={(event) => setReadOnly(event.target.checked)} />
                <span>{t('account.apiKeys.readOnlyLabel')}</span>
            </label>
            <small className="muted" style={{ marginTop: '0.25rem', display: 'block' }}>{t('account.apiKeys.readOnlyHint')}</small>
            <div className="actions-row">
                <button type="submit" className="button button-primary" disabled={create.isPending}>
                    {create.isPending ? t('common.saving') : t('account.apiKeys.create')}
                </button>
                <button type="button" className="button button-secondary" onClick={onCancel}>{t('common.cancel')}</button>
            </div>
        </form>
    )
}

function CreateAnalyticsTokenForm({
    onCancel,
    onCreated,
    memberships,
    user,
}: {
    onCancel: () => void
    onCreated: (secret: string) => void
    memberships: Parameters<typeof analyticsScopeOptions>[0]
    user: { role?: string } | null | undefined
}) {
    const { t } = useTranslation()
    const { pushToast } = useToast()
    const isAdmin = user?.role === 'admin'
    // An admin reads any community, so the list is not limited to their own memberships.
    const zevsQuery = useQuery({ queryKey: queryKeys.zev.list(), queryFn: fetchZevs, enabled: isAdmin })
    const options = analyticsScopeOptions(memberships, isAdmin ? zevsQuery.data : undefined)
    const [name, setName] = useState('')
    const [scopeValue, setScopeValue] = useState('')
    // Derived, so a list that grows after it first rendered (the admin's communities) still has a choice.
    const selected = options.find((option) => option.value === scopeValue) ?? options[0]
    const [expiryDays, setExpiryDays] = useState<number | null>(365)

    const create = useMutation({
        mutationFn: () => {
            const scope = selected
            if (!scope) throw new Error('no scope')
            return createAnalyticsToken({
                name: name.trim(),
                zev: scope.zev,
                participant: scope.participant ?? null,
                expires_at: expiryFromDays(expiryDays),
            })
        },
        onSuccess: (created) => onCreated(created.token),
        onError: (error) => pushToast(formatApiError(error, t('common.error')), 'error'),
    })

    function optionLabel(option: (typeof options)[number]) {
        return option.kind === 'zev'
            ? t('account.tokens.analytics.scopeZev', { zev: option.zevName })
            : t('account.tokens.analytics.scopeMine', { zev: option.zevName })
    }

    return (
        <form
            onSubmit={(event) => {
                event.preventDefault()
                if (!name.trim()) {
                    pushToast(t('account.tokens.analytics.nameRequired'), 'error')
                    return
                }
                create.mutate()
            }}
            style={{ marginBottom: '1.5rem' }}
        >
            <h3>{t('account.tokens.newAnalytics')}</h3>
            <p className="muted">{t('account.tokens.analytics.description')}</p>
            <label>
                <span>{t('account.apiKeys.nameLabel')}</span>
                <input
                    type="text"
                    value={name}
                    onChange={(event) => setName(event.target.value)}
                    placeholder={t('account.tokens.analytics.namePlaceholder')}
                />
            </label>
            <label>
                <span>{t('account.tokens.analytics.scopeLabel')}</span>
                <select value={selected?.value ?? ''} onChange={(event) => setScopeValue(event.target.value)}>
                    {options.map((option) => (
                        <option key={option.value} value={option.value}>{optionLabel(option)}</option>
                    ))}
                </select>
            </label>
            <ExpirySelect value={expiryDays} onChange={setExpiryDays} />
            <div className="actions-row">
                <button type="submit" className="button button-primary" disabled={create.isPending || options.length === 0}>
                    {create.isPending ? t('common.saving') : t('account.tokens.analytics.create')}
                </button>
                <button type="button" className="button button-secondary" onClick={onCancel}>{t('common.cancel')}</button>
            </div>
        </form>
    )
}
