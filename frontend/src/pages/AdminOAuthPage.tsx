import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import {
    createOAuthProviderConfig,
    deleteOAuthProviderConfig,
    fetchOAuthProviderConfigs,
    formatApiError,
    updateOAuthProviderConfig,
} from '../lib/api'
import type { OAuthProviderConfig, OAuthProviderConfigInput } from '../types/api'
import { useToast } from '../lib/toast'
import { useConfirmDialog } from '../lib/confirmDialog'
import { ConfirmDialog } from '../components/ConfirmDialog'

const EMPTY_FORM: OAuthProviderConfigInput = {
    name: '',
    display_name: '',
    client_id: '',
    client_secret: '',
    authorization_url: '',
    token_url: '',
    userinfo_url: '',
    scope: 'openid email profile',
    enabled: true,
}

export function AdminOAuthPage() {
    const { t } = useTranslation()
    const queryClient = useQueryClient()
    const { pushToast } = useToast()
    const { confirm, dialogProps } = useConfirmDialog()

    const [showForm, setShowForm] = useState(false)
    const [editTarget, setEditTarget] = useState<OAuthProviderConfig | null>(null)
    const [form, setForm] = useState<OAuthProviderConfigInput>(EMPTY_FORM)
    const [formError, setFormError] = useState<string | null>(null)

    const providersQuery = useQuery({
        queryKey: ['oauth-provider-configs'],
        queryFn: fetchOAuthProviderConfigs,
    })

    const createMutation = useMutation({
        mutationFn: (payload: OAuthProviderConfigInput) => createOAuthProviderConfig(payload),
        onSuccess: () => {
            void queryClient.invalidateQueries({ queryKey: ['oauth-provider-configs'] })
            pushToast(t('adminOAuth.createSuccess'), 'success')
            closeForm()
        },
        onError: (error) => setFormError(formatApiError(error)),
    })

    const updateMutation = useMutation({
        mutationFn: ({ id, payload }: { id: number; payload: Partial<OAuthProviderConfigInput> }) =>
            updateOAuthProviderConfig(id, payload),
        onSuccess: () => {
            void queryClient.invalidateQueries({ queryKey: ['oauth-provider-configs'] })
            pushToast(t('adminOAuth.updateSuccess'), 'success')
            closeForm()
        },
        onError: (error) => setFormError(formatApiError(error)),
    })

    const deleteMutation = useMutation({
        mutationFn: (id: number) => deleteOAuthProviderConfig(id),
        onSuccess: () => {
            void queryClient.invalidateQueries({ queryKey: ['oauth-provider-configs'] })
            pushToast(t('adminOAuth.deleteSuccess'), 'success')
        },
        onError: (error) => pushToast(formatApiError(error), 'error'),
    })

    function openCreateForm() {
        setEditTarget(null)
        setForm(EMPTY_FORM)
        setFormError(null)
        setShowForm(true)
    }

    function openEditForm(provider: OAuthProviderConfig) {
        setEditTarget(provider)
        setForm({
            name: provider.name,
            display_name: provider.display_name,
            client_id: provider.client_id,
            client_secret: provider.client_secret,
            authorization_url: provider.authorization_url,
            token_url: provider.token_url,
            userinfo_url: provider.userinfo_url,
            scope: provider.scope,
            enabled: provider.enabled,
        })
        setFormError(null)
        setShowForm(true)
    }

    function closeForm() {
        setShowForm(false)
        setEditTarget(null)
        setForm(EMPTY_FORM)
        setFormError(null)
    }

    function handleChange(e: React.ChangeEvent<HTMLInputElement>) {
        const { name, value, type, checked } = e.target
        setForm((prev) => ({ ...prev, [name]: type === 'checkbox' ? checked : value }))
    }

    function handleSubmit(e: React.FormEvent) {
        e.preventDefault()
        setFormError(null)
        if (editTarget) {
            updateMutation.mutate({ id: editTarget.id, payload: form })
        } else {
            createMutation.mutate(form)
        }
    }

    async function handleDelete(provider: OAuthProviderConfig) {
        const confirmed = await confirm({
            title: t('adminOAuth.deleteConfirmTitle'),
            message: t('adminOAuth.deleteConfirmMessage', { name: provider.display_name }),
            confirmLabel: t('common.delete'),
            danger: true,
        })
        if (confirmed) {
            deleteMutation.mutate(provider.id)
        }
    }

    const isPending = createMutation.isPending || updateMutation.isPending
    const providers = providersQuery.data ?? []

    return (
        <div className="page-stack">
            <header>
                <p className="eyebrow">{t('adminOAuth.eyebrow')}</p>
                <h2>{t('adminOAuth.title')}</h2>
                <p className="muted">{t('adminOAuth.description')}</p>
            </header>

            <div className="table-card">
                <div className="table-card-header">
                    <h3>{t('adminOAuth.providersTitle')}</h3>
                    <button type="button" className="button" onClick={openCreateForm}>
                        {t('adminOAuth.addProvider')}
                    </button>
                </div>

                {providersQuery.isLoading && <p className="muted">{t('common.loading')}</p>}
                {providersQuery.isError && <p className="text-error">{t('common.error')}</p>}

                {!providersQuery.isLoading && providers.length === 0 && (
                    <p className="muted table-card-empty">{t('adminOAuth.noProviders')}</p>
                )}

                {providers.length > 0 && (
                    <table className="data-table">
                        <thead>
                            <tr>
                                <th>{t('adminOAuth.colName')}</th>
                                <th>{t('adminOAuth.colClientId')}</th>
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
                                    <td>
                                        <code style={{ fontSize: '0.8em' }}>{provider.client_id}</code>
                                    </td>
                                    <td style={{ fontSize: '0.85em' }}>{provider.scope}</td>
                                    <td style={{ textAlign: 'center' }}>
                                        <span className={`badge ${provider.enabled ? 'badge-success' : 'badge-neutral'}`}>
                                            {provider.enabled ? t('common.yes') : t('common.no')}
                                        </span>
                                    </td>
                                    <td className="action-cell">
                                        <button
                                            type="button"
                                            className="button button-sm button-secondary"
                                            onClick={() => openEditForm(provider)}
                                        >
                                            {t('common.edit')}
                                        </button>
                                        <button
                                            type="button"
                                            className="button button-sm button-danger"
                                            onClick={() => void handleDelete(provider)}
                                            disabled={deleteMutation.isPending}
                                        >
                                            {t('common.delete')}
                                        </button>
                                    </td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                )}
            </div>

            {/* Callback URL info */}
            <section className="card" style={{ maxWidth: 720 }}>
                <h3 style={{ marginTop: 0 }}>{t('adminOAuth.callbackUrlTitle')}</h3>
                <p className="muted">{t('adminOAuth.callbackUrlDescription')}</p>
                <code style={{ display: 'block', padding: '0.75rem', background: 'var(--bg-subtle)', borderRadius: '0.375rem', wordBreak: 'break-all' }}>
                    {window.location.origin.replace(/:\d+$/, ':8000')}/api/v1/auth/oauth/callback/&#123;provider-name&#125;/
                </code>
            </section>

            {/* Create / edit form modal */}
            {showForm && (
                <div className="modal-backdrop" onClick={closeForm}>
                    <div
                        className="modal-box card"
                        style={{ maxWidth: 560, width: '100%' }}
                        onClick={(e) => e.stopPropagation()}
                    >
                        <h2 style={{ marginTop: 0 }}>
                            {editTarget ? t('adminOAuth.editTitle') : t('adminOAuth.createTitle')}
                        </h2>

                        <form onSubmit={handleSubmit}>
                            <label>
                                <span>{t('adminOAuth.fieldName')}</span>
                                <input
                                    type="text"
                                    name="name"
                                    value={form.name}
                                    onChange={handleChange}
                                    placeholder="github"
                                    required
                                    disabled={!!editTarget}
                                />
                                <small className="muted">{t('adminOAuth.fieldNameHint')}</small>
                            </label>

                            <label>
                                <span>{t('adminOAuth.fieldDisplayName')}</span>
                                <input
                                    type="text"
                                    name="display_name"
                                    value={form.display_name}
                                    onChange={handleChange}
                                    placeholder="GitHub"
                                    required
                                />
                            </label>

                            <label>
                                <span>{t('adminOAuth.fieldClientId')}</span>
                                <input
                                    type="text"
                                    name="client_id"
                                    value={form.client_id}
                                    onChange={handleChange}
                                    required
                                    autoComplete="off"
                                />
                            </label>

                            <label>
                                <span>{t('adminOAuth.fieldClientSecret')}</span>
                                <input
                                    type="password"
                                    name="client_secret"
                                    value={form.client_secret}
                                    onChange={handleChange}
                                    required
                                    autoComplete="new-password"
                                />
                            </label>

                            <label>
                                <span>{t('adminOAuth.fieldAuthorizationUrl')}</span>
                                <input
                                    type="url"
                                    name="authorization_url"
                                    value={form.authorization_url}
                                    onChange={handleChange}
                                    placeholder="https://provider.example.com/oauth/authorize"
                                    required
                                />
                            </label>

                            <label>
                                <span>{t('adminOAuth.fieldTokenUrl')}</span>
                                <input
                                    type="url"
                                    name="token_url"
                                    value={form.token_url}
                                    onChange={handleChange}
                                    placeholder="https://provider.example.com/oauth/token"
                                    required
                                />
                            </label>

                            <label>
                                <span>{t('adminOAuth.fieldUserinfoUrl')}</span>
                                <input
                                    type="url"
                                    name="userinfo_url"
                                    value={form.userinfo_url}
                                    onChange={handleChange}
                                    placeholder="https://provider.example.com/oauth/userinfo"
                                    required
                                />
                            </label>

                            <label>
                                <span>{t('adminOAuth.fieldScope')}</span>
                                <input
                                    type="text"
                                    name="scope"
                                    value={form.scope}
                                    onChange={handleChange}
                                    required
                                />
                            </label>

                            <label className="checkbox-label">
                                <input
                                    type="checkbox"
                                    name="enabled"
                                    checked={form.enabled}
                                    onChange={handleChange}
                                />
                                <span>{t('adminOAuth.fieldEnabled')}</span>
                            </label>

                            {formError && <div className="error-banner">{formError}</div>}

                            <div className="modal-actions">
                                <button
                                    type="button"
                                    className="button button-ghost"
                                    onClick={closeForm}
                                    disabled={isPending}
                                >
                                    {t('common.cancel')}
                                </button>
                                <button type="submit" className="button" disabled={isPending}>
                                    {isPending
                                        ? t('common.saving')
                                        : editTarget
                                          ? t('common.save')
                                          : t('common.create')}
                                </button>
                            </div>
                        </form>
                    </div>
                </div>
            )}

            {dialogProps && <ConfirmDialog {...dialogProps} />}
        </div>
    )
}
