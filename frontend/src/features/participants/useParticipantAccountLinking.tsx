import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { linkableAccounts } from '../accounts/accountList'
import { fetchUsers } from '../../lib/api/auth'
import { formatApiError } from '../../lib/api/errors'
import { queryKeys } from '../../lib/api/queryKeys'
import { linkParticipantAccount, unlinkParticipantAccount } from '../../lib/api/zev'
import { useToast } from '../../lib/toast'
import type { Participant } from '../../types/api'
import { LinkAccountModal } from './LinkAccountModal'

type ConfirmOptions = {
    title: string
    message: string
    confirmText: string
    cancelText: string
    isDangerous?: boolean
    onConfirm: () => Promise<void> | void
}

/**
 * Linking an existing account to a participant, and unlinking it again —
 * admin-only server-side, so the accounts query only runs for admins.
 *
 * This lives with the participants, not on the accounts page: a membership is
 * a fact about one community's participant, and the community is where it gets
 * managed (the accounts page only lists where each account ended up).
 */
export function useParticipantAccountLinking({
    isAdmin,
    confirm,
}: {
    isAdmin: boolean
    confirm: (options: ConfirmOptions) => void
}) {
    const { t } = useTranslation()
    const queryClient = useQueryClient()
    const { pushToast } = useToast()
    const [target, setTarget] = useState<{ participant: Participant; name: string } | null>(null)
    const [error, setError] = useState<string | null>(null)

    const usersQuery = useQuery({ queryKey: queryKeys.auth.users(), queryFn: fetchUsers, enabled: isAdmin })

    function refresh() {
        void queryClient.invalidateQueries({ queryKey: ['zev', 'participants'] })
        void queryClient.invalidateQueries({ queryKey: queryKeys.auth.users() })
    }

    const linkMutation = useMutation({
        mutationFn: ({ participantId, userId }: { participantId: string; userId: number }) =>
            linkParticipantAccount(participantId, userId),
        onSuccess: () => {
            setTarget(null)
            setError(null)
            pushToast(t('pages.accounts.feedback.linkSuccess'), 'success')
            refresh()
        },
        onError: (err) => setError(formatApiError(err, t('pages.accounts.feedback.linkFailed'))),
    })

    const unlinkMutation = useMutation({
        mutationFn: (participantId: string) => unlinkParticipantAccount(participantId),
        onSuccess: () => {
            pushToast(t('pages.accounts.feedback.unlinkSuccess'), 'success')
            refresh()
        },
        onError: (err) => pushToast(formatApiError(err, t('pages.accounts.feedback.unlinkFailed')), 'error'),
    })

    const linkable = linkableAccounts(usersQuery.data ?? [])

    return {
        /** Link needs at least one account to pick from. */
        canLink: isAdmin && linkable.length > 0,
        canUnlink: isAdmin,
        pending: linkMutation.isPending || unlinkMutation.isPending,
        openLink(participant: Participant, name: string) {
            setError(null)
            setTarget({ participant, name })
        },
        confirmUnlink(participant: Participant, name: string, username: string) {
            confirm({
                title: t('pages.accounts.unlinkTitle'),
                message: t('pages.accounts.unlinkMessage', { username, name }),
                confirmText: t('pages.accounts.unlinkConfirm'),
                cancelText: t('common.cancel'),
                onConfirm: async () => {
                    await unlinkMutation.mutateAsync(participant.id)
                },
            })
        },
        linkModal: target ? (
            <LinkAccountModal
                participantName={target.name}
                accounts={linkable}
                error={error}
                pending={linkMutation.isPending}
                onSubmit={(userId) => linkMutation.mutate({ participantId: target.participant.id, userId })}
                onClose={() => setTarget(null)}
            />
        ) : null,
    }
}
