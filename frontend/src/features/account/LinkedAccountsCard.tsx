import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Skeleton } from '@mantine/core'
import { useReducedMotion } from '@mantine/hooks'
import { useTranslation } from 'react-i18next'
import { deleteSocialAccount, fetchOAuthProviders, fetchSocialAccounts, oauthLinkInitiate } from '../../lib/api/auth'
import { queryKeys } from '../../lib/api/queryKeys'
import { useToast } from '../../lib/toast'

interface Props {
    /** Asks the page to confirm before unlinking (it owns the dialog). */
    onUnlink: (options: { provider: string; onConfirm: () => void }) => void
}

/** External sign-in providers (OAuth) linked to this account. */
export function LinkedAccountsCard({ onUnlink }: Props) {
    const { t } = useTranslation()
    const animate = !useReducedMotion()
    const { pushToast } = useToast()
    const queryClient = useQueryClient()
    const [linkingProvider, setLinkingProvider] = useState<string | null>(null)

    const socialAccountsQuery = useQuery({ queryKey: queryKeys.auth.socialAccounts(), queryFn: fetchSocialAccounts })
    const oauthProvidersQuery = useQuery({ queryKey: queryKeys.auth.oauthProviders(), queryFn: fetchOAuthProviders })

    const unlinkMutation = useMutation({
        mutationFn: (id: number) => deleteSocialAccount(id),
        onSuccess: () => {
            void queryClient.invalidateQueries({ queryKey: queryKeys.auth.socialAccounts() })
            pushToast(t('account.unlinkSuccess'), 'success')
        },
        onError: () => pushToast(t('common.error'), 'error'),
    })

    async function handleLink(providerSlug: string) {
        setLinkingProvider(providerSlug)
        try {
            const { redirect_url } = await oauthLinkInitiate(providerSlug)
            window.location.assign(redirect_url)
        } catch {
            pushToast(t('auth.oauth.errors.initFailed'), 'error')
            setLinkingProvider(null)
        }
    }

    return (
        <div className="card">
            <h2>{t('account.linkedAccountsSection')}</h2>
            <p className="muted" style={{ marginBottom: '1.5rem' }}>{t('account.linkedAccountsDescription')}</p>

            {oauthProvidersQuery.isLoading && (
                <div style={{ display: 'grid', gap: '0.5rem' }}>
                    <Skeleton className="skeleton-block" animate={animate} height={14} width="60%" />
                    <Skeleton className="skeleton-block" animate={animate} height={14} width="40%" />
                </div>
            )}

            {!oauthProvidersQuery.isLoading && (oauthProvidersQuery.data ?? []).length === 0 && (
                <p className="muted">{t('account.noProviders')}</p>
            )}

            {(oauthProvidersQuery.data ?? []).map((provider) => {
                const linked = (socialAccountsQuery.data ?? []).find((sa) => sa.provider_name === provider.name)
                return (
                    <div
                        key={provider.name}
                        style={{
                            display: 'flex',
                            alignItems: 'center',
                            justifyContent: 'space-between',
                            padding: '0.75rem 0',
                            borderBottom: '1px solid var(--border)',
                        }}
                    >
                        <div>
                            <strong>{provider.display_name}</strong>
                            {linked && (
                                <small className="muted" style={{ display: 'block' }}>
                                    {t('account.linkedSince', { date: new Date(linked.created_at).toLocaleDateString() })}
                                </small>
                            )}
                        </div>
                        {linked ? (
                            <button
                                type="button"
                                className="button button-danger button-compact"
                                disabled={unlinkMutation.isPending}
                                onClick={() =>
                                    onUnlink({ provider: provider.display_name, onConfirm: () => unlinkMutation.mutate(linked.id) })
                                }
                            >
                                {t('account.unlinkAccount')}
                            </button>
                        ) : (
                            <button
                                type="button"
                                className="button button-secondary button-compact"
                                disabled={linkingProvider !== null}
                                onClick={() => void handleLink(provider.name)}
                            >
                                {linkingProvider === provider.name
                                    ? t('common.loading')
                                    : t('account.linkAccount', { provider: provider.display_name })}
                            </button>
                        )}
                    </div>
                )
            })}
        </div>
    )
}
