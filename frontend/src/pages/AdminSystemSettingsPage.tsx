import { useEffect, useMemo, useState, type ChangeEvent, type FormEvent } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { FormControlLabel, Switch, Tab, Tabs } from '@mui/material'
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome'
import { faCheck, faPen, faPlus, faTrash, faXmark } from '@fortawesome/free-solid-svg-icons'
import { useSearchParams } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import {
    createOAuthProviderConfig,
    deleteOAuthProviderConfig,
    fetchFeatureFlags,
    fetchOAuthProviderConfigs,
    formatApiError,
    updateAppSettings,
    updateFeatureFlag,
    updateOAuthProviderConfig,
} from '../lib/api'
import {
    DATE_TIME_FORMAT_OPTIONS,
    LONG_DATE_FORMAT_OPTIONS,
    SHORT_DATE_FORMAT_OPTIONS,
    formatDateByPattern,
    formatDateTime,
    useAppSettings,
} from '../lib/appSettings'
import { useToast } from '../lib/toast'
import type { DateTimeFormat, LongDateFormat, OAuthProviderConfig, OAuthProviderConfigInput, ShortDateFormat } from '../types/api'
import { ConfirmDialog, useConfirmDialog } from '../components/ConfirmDialog'
import { FormModal } from '../components/FormModal'

type SystemSettingsTab = 'regional' | 'features' | 'oauth'

const EMPTY_OAUTH_FORM: OAuthProviderConfigInput = {
    name: '',
    display_name: '',
    client_id: '',
    client_secret: '',
    authorization_url: '',
    token_url: '',
    userinfo_url: '',
    redirect_url: '',
    scope: 'openid email profile',
    enabled: true,
}

const TAB_ORDER: SystemSettingsTab[] = ['regional', 'features', 'oauth']

function getValidTab(value: string | null): SystemSettingsTab {
    return TAB_ORDER.includes(value as SystemSettingsTab) ? (value as SystemSettingsTab) : 'regional'
}

export function AdminSystemSettingsPage() {
    const { t } = useTranslation()
    const [searchParams, setSearchParams] = useSearchParams()
    const queryClient = useQueryClient()
    const { pushToast } = useToast()
    const { settings, isLoading: appSettingsLoading } = useAppSettings()
    const { dialog, confirm, handleConfirm, handleCancel, isLoading: dialogLoading } = useConfirmDialog()

    const activeTab = getValidTab(searchParams.get('tab'))

    const [regionalForm, setRegionalForm] = useState({
        date_format_short: settings.date_format_short,
        date_format_long: settings.date_format_long,
        date_time_format: settings.date_time_format,
    })

    const [showOAuthForm, setShowOAuthForm] = useState(false)
    const [oauthEditTarget, setOauthEditTarget] = useState<OAuthProviderConfig | null>(null)
    const [oauthForm, setOauthForm] = useState<OAuthProviderConfigInput>(EMPTY_OAUTH_FORM)
    const [oauthFormError, setOauthFormError] = useState<string | null>(null)

    useEffect(() => {
        setRegionalForm({
            date_format_short: settings.date_format_short,
            date_format_long: settings.date_format_long,
            date_time_format: settings.date_time_format,
        })
    }, [settings.date_format_long, settings.date_format_short, settings.date_time_format])

    const featureFlagsQuery = useQuery({
        queryKey: ['feature-flags'],
        queryFn: fetchFeatureFlags,
    })

    const oauthProvidersQuery = useQuery({
        queryKey: ['oauth-provider-configs'],
        queryFn: fetchOAuthProviderConfigs,
    })

    const saveRegionalMutation = useMutation({
        mutationFn: updateAppSettings,
        onSuccess: (data) => {
            queryClient.setQueryData(['app-settings'], data)
            pushToast(t('adminSystemSettings.regional.updated'), 'success')
        },
        onError: () => pushToast(t('adminSystemSettings.regional.updateFailed'), 'error'),
    })

    const featureToggleMutation = useMutation({
        mutationFn: ({ id, enabled }: { id: number; enabled: boolean }) => updateFeatureFlag(id, { enabled }),
        onSuccess: () => {
            void queryClient.invalidateQueries({ queryKey: ['feature-flags'] })
            pushToast(t('features.updated'), 'success')
        },
        onError: (error) => pushToast(formatApiError(error), 'error'),
    })

    const createOAuthMutation = useMutation({
        mutationFn: (payload: OAuthProviderConfigInput) => createOAuthProviderConfig(payload),
        onSuccess: () => {
            void queryClient.invalidateQueries({ queryKey: ['oauth-provider-configs'] })
            pushToast(t('adminOAuth.createSuccess'), 'success')
            closeOAuthForm()
        },
        onError: (error) => setOauthFormError(formatApiError(error)),
    })

    const updateOAuthMutation = useMutation({
        mutationFn: ({ id, payload }: { id: number; payload: Partial<OAuthProviderConfigInput> }) => updateOAuthProviderConfig(id, payload),
        onSuccess: () => {
            void queryClient.invalidateQueries({ queryKey: ['oauth-provider-configs'] })
            pushToast(t('adminOAuth.updateSuccess'), 'success')
            closeOAuthForm()
        },
        onError: (error) => setOauthFormError(formatApiError(error)),
    })

    const deleteOAuthMutation = useMutation({
        mutationFn: (id: number) => deleteOAuthProviderConfig(id),
        onSuccess: () => {
            void queryClient.invalidateQueries({ queryKey: ['oauth-provider-configs'] })
            pushToast(t('adminOAuth.deleteSuccess'), 'success')
        },
        onError: (error) => pushToast(formatApiError(error), 'error'),
    })

    const previewDate = '2026-03-18'
    const previewDateTime = '2026-03-18T14:35:00Z'
    const flags = featureFlagsQuery.data ?? []
    const providers = oauthProvidersQuery.data ?? []
    const oauthMutationPending = createOAuthMutation.isPending || updateOAuthMutation.isPending

    const tabDescription = useMemo(() => {
        switch (activeTab) {
            case 'features':
                return t('adminSystemSettings.tabs.features.description')
            case 'oauth':
                return t('adminSystemSettings.tabs.oauth.description')
            default:
                return t('adminSystemSettings.tabs.regional.description')
        }
    }, [activeTab, t])

    function setActiveTab(tab: SystemSettingsTab) {
        setSearchParams(tab === 'regional' ? {} : { tab })
    }

    function openCreateOAuthForm() {
        setOauthEditTarget(null)
        setOauthForm(EMPTY_OAUTH_FORM)
        setOauthFormError(null)
        setShowOAuthForm(true)
    }

    function openEditOAuthForm(provider: OAuthProviderConfig) {
        setOauthEditTarget(provider)
        setOauthForm({
            name: provider.name,
            display_name: provider.display_name,
            client_id: provider.client_id,
            client_secret: provider.client_secret,
            authorization_url: provider.authorization_url,
            token_url: provider.token_url,
            userinfo_url: provider.userinfo_url,
            redirect_url: provider.redirect_url,
            scope: provider.scope,
            enabled: provider.enabled,
        })
        setOauthFormError(null)
        setShowOAuthForm(true)
    }

    function closeOAuthForm() {
        setShowOAuthForm(false)
        setOauthEditTarget(null)
        setOauthForm(EMPTY_OAUTH_FORM)
        setOauthFormError(null)
    }

    function handleOAuthChange(event: ChangeEvent<HTMLInputElement>) {
        const { name, value, type, checked } = event.target
        setOauthForm((previous) => ({
            ...previous,
            [name]: type === 'checkbox' ? checked : value,
        }))
    }

    function submitRegionalSettings(event: FormEvent<HTMLFormElement>) {
        event.preventDefault()
        saveRegionalMutation.mutate(regionalForm)
    }

    function submitOAuthForm(event: FormEvent<HTMLFormElement>) {
        event.preventDefault()
        setOauthFormError(null)
        if (oauthEditTarget) {
            updateOAuthMutation.mutate({ id: oauthEditTarget.id, payload: oauthForm })
            return
        }
        createOAuthMutation.mutate(oauthForm)
    }

    function confirmDeleteOAuthProvider(provider: OAuthProviderConfig) {
        confirm({
            title: t('adminOAuth.deleteConfirmTitle'),
            message: t('adminOAuth.deleteConfirmMessage', { name: provider.display_name }),
            confirmText: t('common.delete'),
            cancelText: t('common.cancel'),
            isDangerous: true,
            onConfirm: async () => {
                await deleteOAuthMutation.mutateAsync(provider.id)
            },
        })
    }

    return (
        <div className="page-stack">
            <header>
                <p className="eyebrow">{t('adminSystemSettings.eyebrow')}</p>
                <h2>{t('adminSystemSettings.title')}</h2>
                <p className="muted">{t('adminSystemSettings.description')}</p>
            </header>

            <section className="card" style={{ paddingBottom: '0.5rem' }}>
                <Tabs
                    value={activeTab}
                    onChange={(_, value) => setActiveTab(value as SystemSettingsTab)}
                    variant="scrollable"
                    allowScrollButtonsMobile
                    sx={{
                        minHeight: 0,
                        '& .MuiTab-root': {
                            alignItems: 'flex-start',
                            minHeight: 0,
                            paddingInline: 0,
                            marginRight: '1.5rem',
                            textTransform: 'none',
                            fontSize: '0.95rem',
                            fontWeight: 700,
                        },
                        '& .MuiTabs-indicator': {
                            backgroundColor: '#0f172a',
                            height: '3px',
                            borderRadius: '999px',
                        },
                    }}
                >
                    <Tab value="regional" label={t('adminSystemSettings.tabs.regional.label')} />
                    <Tab value="features" label={t('adminSystemSettings.tabs.features.label')} />
                    <Tab value="oauth" label={t('adminSystemSettings.tabs.oauth.label')} />
                </Tabs>
                <p className="muted" style={{ marginBottom: 0 }}>{tabDescription}</p>
            </section>

            {activeTab === 'regional' && (
                <section className="card" style={{ maxWidth: 760 }}>
                    <div style={{ marginBottom: '1rem' }}>
                        <h3 style={{ marginTop: 0, marginBottom: '0.35rem' }}>{t('adminSystemSettings.regional.title')}</h3>
                        <p className="muted" style={{ margin: 0 }}>{t('adminSystemSettings.regional.description')}</p>
                    </div>
                    {appSettingsLoading ? (
                        <p className="muted" style={{ margin: 0 }}>{t('adminSystemSettings.regional.loading')}</p>
                    ) : (
                        <form onSubmit={submitRegionalSettings} className="page-stack">
                            <label>
                                <span>{t('adminSystemSettings.regional.shortDate')}</span>
                                <select
                                    value={regionalForm.date_format_short}
                                    onChange={(event) => setRegionalForm((previous) => ({
                                        ...previous,
                                        date_format_short: event.target.value as ShortDateFormat,
                                    }))}
                                >
                                    {SHORT_DATE_FORMAT_OPTIONS.map((option) => (
                                        <option key={option.value} value={option.value}>{option.label}</option>
                                    ))}
                                </select>
                            </label>

                            <label>
                                <span>{t('adminSystemSettings.regional.longDate')}</span>
                                <select
                                    value={regionalForm.date_format_long}
                                    onChange={(event) => setRegionalForm((previous) => ({
                                        ...previous,
                                        date_format_long: event.target.value as LongDateFormat,
                                    }))}
                                >
                                    {LONG_DATE_FORMAT_OPTIONS.map((option) => (
                                        <option key={option.value} value={option.value}>{option.label}</option>
                                    ))}
                                </select>
                            </label>

                            <label>
                                <span>{t('adminSystemSettings.regional.dateTime')}</span>
                                <select
                                    value={regionalForm.date_time_format}
                                    onChange={(event) => setRegionalForm((previous) => ({
                                        ...previous,
                                        date_time_format: event.target.value as DateTimeFormat,
                                    }))}
                                >
                                    {DATE_TIME_FORMAT_OPTIONS.map((option) => (
                                        <option key={option.value} value={option.value}>{option.label}</option>
                                    ))}
                                </select>
                            </label>

                            <div className="card" style={{ background: 'var(--color-bg-soft, #f8fafc)' }}>
                                <h3 style={{ marginTop: 0 }}>{t('adminSystemSettings.regional.previewTitle')}</h3>
                                <p style={{ marginBottom: '0.35rem' }}>
                                    <strong>{t('adminSystemSettings.regional.previewShort')}</strong> {formatDateByPattern(previewDate, regionalForm.date_format_short)}
                                </p>
                                <p style={{ marginBottom: '0.35rem' }}>
                                    <strong>{t('adminSystemSettings.regional.previewLong')}</strong> {formatDateByPattern(previewDate, regionalForm.date_format_long)}
                                </p>
                                <p style={{ marginBottom: 0 }}>
                                    <strong>{t('adminSystemSettings.regional.previewDateTime')}</strong> {formatDateTime(previewDateTime, {
                                        ...settings,
                                        date_format_short: regionalForm.date_format_short,
                                        date_format_long: regionalForm.date_format_long,
                                        date_time_format: regionalForm.date_time_format,
                                    })}
                                </p>
                            </div>

                            <div className="actions-row actions-row-end actions-row-wrap">
                                <button className="button button-primary" type="submit" disabled={saveRegionalMutation.isPending}>
                                    <FontAwesomeIcon icon={faCheck} fixedWidth />
                                    {t('adminSystemSettings.regional.save')}
                                </button>
                            </div>
                        </form>
                    )}
                </section>
            )}

            {activeTab === 'features' && (
                <section className="card" style={{ maxWidth: 880 }}>
                    <div style={{ marginBottom: '1rem' }}>
                        <h3 style={{ marginTop: 0, marginBottom: '0.35rem' }}>{t('features.title')}</h3>
                        <p className="muted" style={{ margin: 0 }}>{t('features.description')}</p>
                    </div>

                    {featureFlagsQuery.isLoading && <p className="muted">{t('features.loading')}</p>}
                    {featureFlagsQuery.isError && <p className="error-banner">{t('features.loadError')}</p>}
                    {!featureFlagsQuery.isLoading && flags.length === 0 && <p className="muted">{t('features.empty')}</p>}

                    {flags.length > 0 && (
                        <table className="data-table">
                            <thead>
                                <tr>
                                    <th>{t('features.name')}</th>
                                    <th>{t('features.descriptionCol')}</th>
                                    <th style={{ width: 80, textAlign: 'center' }}>{t('features.enabled')}</th>
                                </tr>
                            </thead>
                            <tbody>
                                {flags.map((flag) => (
                                    <tr key={flag.id}>
                                        <td><code>{flag.name}</code></td>
                                        <td>{flag.description || <span className="muted">—</span>}</td>
                                        <td className="feature-toggle-cell">
                                            <div className="feature-toggle-wrap">
                                                <button
                                                    type="button"
                                                    className={`feature-toggle${flag.enabled ? ' is-on' : ''}`}
                                                    role="switch"
                                                    aria-checked={flag.enabled}
                                                    aria-label={`${flag.name}: ${flag.enabled ? t('features.on') : t('features.off')}`}
                                                    disabled={featureToggleMutation.isPending}
                                                    onClick={() => featureToggleMutation.mutate({ id: flag.id, enabled: !flag.enabled })}
                                                >
                                                    <span className="feature-toggle-track" aria-hidden="true">
                                                        <span className="feature-toggle-thumb" />
                                                    </span>
                                                </button>
                                                <span className={`feature-toggle-state ${flag.enabled ? 'is-on' : 'is-off'}`}>
                                                    {flag.enabled ? t('features.on') : t('features.off')}
                                                </span>
                                            </div>
                                        </td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    )}
                </section>
            )}

            {activeTab === 'oauth' && (
                <div className="table-card">
                    <div style={{ display: 'flex', justifyContent: 'space-between', gap: '1rem', alignItems: 'flex-start', flexWrap: 'wrap', marginBottom: '1rem' }}>
                        <div>
                            <h3 style={{ marginTop: 0, marginBottom: '0.35rem' }}>{t('adminOAuth.providersTitle')}</h3>
                            <p className="muted" style={{ margin: 0 }}>{t('adminOAuth.description')}</p>
                        </div>
                        <button type="button" className="button button-primary" onClick={openCreateOAuthForm}>
                            <FontAwesomeIcon icon={faPlus} fixedWidth />
                            {t('adminOAuth.addProvider')}
                        </button>
                    </div>

                    {oauthProvidersQuery.isLoading && <p className="muted">{t('common.loading')}</p>}
                    {oauthProvidersQuery.isError && <p className="error-banner">{t('adminSystemSettings.oauth.loadError')}</p>}
                    {!oauthProvidersQuery.isLoading && providers.length === 0 && <p className="muted">{t('adminOAuth.noProviders')}</p>}

                    {providers.length > 0 && (
                        <table className="data-table">
                            <thead>
                                <tr>
                                    <th>{t('adminOAuth.colName')}</th>
                                    <th>{t('adminOAuth.colClientId')}</th>
                                    <th>{t('adminOAuth.colRedirectUrl')}</th>
                                    <th>{t('adminOAuth.colScope')}</th>
                                    <th style={{ textAlign: 'center' }}>{t('adminOAuth.colEnabled')}</th>
                                    <th>{t('common.actions')}</th>
                                </tr>
                            </thead>
                            <tbody>
                                {providers.map((provider) => (
                                    <tr key={provider.id}>
                                        <td>
                                            <strong>{provider.display_name}</strong>
                                            <br />
                                            <code style={{ fontSize: '0.8em' }}>{provider.name}</code>
                                        </td>
                                        <td><code style={{ fontSize: '0.8em' }}>{provider.client_id}</code></td>
                                        <td>
                                            <code style={{ fontSize: '0.8em', wordBreak: 'break-all' }}>{provider.redirect_url}</code>
                                        </td>
                                        <td style={{ fontSize: '0.85em' }}>{provider.scope}</td>
                                        <td style={{ textAlign: 'center' }}>
                                            <span className={`badge ${provider.enabled ? 'badge-success' : 'badge-neutral'}`}>
                                                {provider.enabled ? t('common.yes') : t('common.no')}
                                            </span>
                                        </td>
                                        <td className="actions-cell">
                                            <div className="actions-cell-content">
                                                <button
                                                    type="button"
                                                    className="button button-primary button-compact"
                                                    onClick={() => openEditOAuthForm(provider)}
                                                >
                                                    <FontAwesomeIcon icon={faPen} fixedWidth />
                                                    {t('common.edit')}
                                                </button>
                                                <button
                                                    type="button"
                                                    className="button button-danger button-compact"
                                                    onClick={() => confirmDeleteOAuthProvider(provider)}
                                                    disabled={deleteOAuthMutation.isPending || dialogLoading}
                                                >
                                                    <FontAwesomeIcon icon={faTrash} fixedWidth />
                                                    {t('common.delete')}
                                                </button>
                                            </div>
                                        </td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    )}
                </div>
            )}

            <FormModal
                isOpen={showOAuthForm}
                title={oauthEditTarget ? t('adminOAuth.editTitle') : t('adminOAuth.createTitle')}
                onClose={closeOAuthForm}
                maxWidth="640px"
            >
                <form onSubmit={submitOAuthForm} className="page-stack">
                    <label>
                        <span>{t('adminOAuth.fieldName')}</span>
                        <input
                            type="text"
                            name="name"
                            value={oauthForm.name}
                            onChange={handleOAuthChange}
                            placeholder="github"
                            required
                            disabled={!!oauthEditTarget}
                        />
                        <small className="muted">{t('adminOAuth.fieldNameHint')}</small>
                    </label>

                    <label>
                        <span>{t('adminOAuth.fieldDisplayName')}</span>
                        <input type="text" name="display_name" value={oauthForm.display_name} onChange={handleOAuthChange} placeholder="GitHub" required />
                    </label>

                    <label>
                        <span>{t('adminOAuth.fieldClientId')}</span>
                        <input type="text" name="client_id" value={oauthForm.client_id} onChange={handleOAuthChange} required autoComplete="off" />
                    </label>

                    <label>
                        <span>{t('adminOAuth.fieldClientSecret')}</span>
                        <input type="password" name="client_secret" value={oauthForm.client_secret} onChange={handleOAuthChange} required autoComplete="new-password" />
                    </label>

                    <label>
                        <span>{t('adminOAuth.fieldAuthorizationUrl')}</span>
                        <input
                            type="url"
                            name="authorization_url"
                            value={oauthForm.authorization_url}
                            onChange={handleOAuthChange}
                            placeholder="https://provider.example.com/oauth/authorize"
                            required
                        />
                    </label>

                    <label>
                        <span>{t('adminOAuth.fieldTokenUrl')}</span>
                        <input
                            type="url"
                            name="token_url"
                            value={oauthForm.token_url}
                            onChange={handleOAuthChange}
                            placeholder="https://provider.example.com/oauth/token"
                            required
                        />
                    </label>

                    <label>
                        <span>{t('adminOAuth.fieldUserinfoUrl')}</span>
                        <input
                            type="url"
                            name="userinfo_url"
                            value={oauthForm.userinfo_url}
                            onChange={handleOAuthChange}
                            placeholder="https://provider.example.com/oauth/userinfo"
                            required
                        />
                    </label>

                    <label>
                        <span>{t('adminOAuth.fieldRedirectUrl')}</span>
                        <input
                            type="url"
                            name="redirect_url"
                            value={oauthForm.redirect_url}
                            onChange={handleOAuthChange}
                            placeholder="https://app.example.com/api/v1/auth/oauth/callback/github/"
                        />
                        <small className="muted">{t('adminOAuth.fieldRedirectUrlHint')}</small>
                    </label>

                    <label>
                        <span>{t('adminOAuth.fieldScope')}</span>
                        <input type="text" name="scope" value={oauthForm.scope} onChange={handleOAuthChange} required />
                    </label>

                    <FormControlLabel
                        control={<Switch name="enabled" checked={oauthForm.enabled} onChange={handleOAuthChange} />}
                        label={t('adminOAuth.fieldEnabled')}
                    />

                    {oauthFormError && <div className="error-banner">{oauthFormError}</div>}

                    <div className="actions-row actions-row-end actions-row-wrap">
                        <button type="button" className="button button-secondary" onClick={closeOAuthForm} disabled={oauthMutationPending}>
                            <FontAwesomeIcon icon={faXmark} fixedWidth />
                            {t('common.cancel')}
                        </button>
                        <button type="submit" className="button button-primary" disabled={oauthMutationPending}>
                            <FontAwesomeIcon icon={faCheck} fixedWidth />
                            {oauthMutationPending ? t('common.saving') : oauthEditTarget ? t('common.save') : t('common.create')}
                        </button>
                    </div>
                </form>
            </FormModal>

            {dialog && (
                <ConfirmDialog
                    {...dialog}
                    isLoading={dialogLoading}
                    onConfirm={handleConfirm}
                    onCancel={handleCancel}
                />
            )}
        </div>
    )
}