import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import {
    deleteSupplementarySource,
    disconnectSupplementarySource,
    purgeSupplementaryReadings,
    revokeSupplementaryPushToken,
    rotateSupplementaryPushToken,
    syncSupplementarySource,
    testSupplementarySource,
    updateSupplementarySource,
} from '../../lib/api/supplementary'
import { formatApiError } from '../../lib/api/errors'
import { invalidateSourceQueries } from '../../lib/supplementary'
import { useToast } from '../../lib/toast'
import type { SupplementarySource, SupplementarySourceUpdate } from '../../types/api'

export type ConfirmOptions = {
    title: string
    message: string
    confirmText: string
    isDangerous: boolean
    onConfirm: () => void | Promise<void>
}

interface Options {
    /** A new push token was issued; the caller shows it once. */
    onToken: (token: string) => void
    /** The source is gone (deleted). */
    onGone?: () => void
    /** The Solar Manager key was replaced. */
    onKeyReplaced?: () => void
}

/** Every change its owner can make to one source; the credential never comes back through any of them. */
export function useSourceActions(source: SupplementarySource, { onToken, onGone, onKeyReplaced }: Options) {
    const { t } = useTranslation()
    const { pushToast } = useToast()
    const queryClient = useQueryClient()

    const refresh = () => invalidateSourceQueries(queryClient)
    const onError = (error: unknown) => pushToast(formatApiError(error, t('common.error')), 'error')

    const test = useMutation({
        mutationFn: () => testSupplementarySource(source.id),
        onSuccess: () => pushToast(t('supplementary.actions.testOk'), 'success'),
        onError,
        onSettled: refresh,
    })
    const sync = useMutation({
        mutationFn: () => syncSupplementarySource(source.id),
        onSuccess: () => pushToast(t('supplementary.actions.syncQueued'), 'success'),
        onError: (error: any) =>
            pushToast(
                error?.response?.status === 429 ? t('supplementary.actions.syncCooldown') : formatApiError(error, t('common.error')),
                error?.response?.status === 429 ? 'info' : 'error',
            ),
        onSettled: refresh,
    })
    const replaceKey = useMutation({
        mutationFn: ({ apiKey, externalId }: { apiKey: string; externalId: string }) =>
            updateSupplementarySource(source.id, { api_key: apiKey.trim(), external_id: externalId.trim(), enabled: true }),
        onSuccess: () => {
            onKeyReplaced?.()
            pushToast(t('supplementary.actions.keyReplaced'), 'success')
        },
        onError,
        onSettled: refresh,
    })
    const disconnect = useMutation({
        mutationFn: () => disconnectSupplementarySource(source.id),
        onSuccess: () => pushToast(t('supplementary.actions.disconnected'), 'success'),
        onError,
        onSettled: refresh,
    })
    const purge = useMutation({
        mutationFn: () => purgeSupplementaryReadings(source.id),
        onSuccess: (data) => pushToast(t('supplementary.actions.dataDeleted', { count: data.deleted }), 'success'),
        onError,
        onSettled: refresh,
    })
    const remove = useMutation({
        mutationFn: () => deleteSupplementarySource(source.id),
        onSuccess: () => {
            pushToast(t('supplementary.actions.removed'), 'success')
            onGone?.()
        },
        onError,
        onSettled: refresh,
    })
    const rotate = useMutation({
        mutationFn: () => rotateSupplementaryPushToken(source.id),
        onSuccess: (data) => onToken(data.push_token),
        onError,
        onSettled: refresh,
    })
    const revoke = useMutation({
        mutationFn: () => revokeSupplementaryPushToken(source.id),
        onSuccess: () => pushToast(t('supplementary.live.revoked'), 'success'),
        onError,
        onSettled: refresh,
    })
    /** Switch a capability on or off on the same connection (live needs the consent). */
    const capability = useMutation({
        mutationFn: (input: SupplementarySourceUpdate) => updateSupplementarySource(source.id, input),
        onSuccess: (_data, input) => {
            const key =
                input.provides_live !== undefined
                    ? input.provides_live ? 'supplementary.live.alsoSendDone' : 'supplementary.live.stopped'
                    : input.provides_history ? 'supplementary.source.historyOn' : 'supplementary.source.historyStopped'
            pushToast(t(key), 'success')
        },
        onError,
        onSettled: refresh,
    })

    const busy = [test, sync, replaceKey, disconnect, purge, remove, rotate, revoke, capability].some((mutation) => mutation.isPending)
    return { test, sync, replaceKey, disconnect, purge, remove, rotate, revoke, capability, busy }
}
