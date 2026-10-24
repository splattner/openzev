import { useMutation, type QueryClient } from '@tanstack/react-query'
import { useLayoutEffect, useRef, useState } from 'react'
import { createTariffVersion, duplicateTariff, renameTariffSeries } from '../../lib/api/tariffs'
import { useAuth } from '../../lib/auth'
import { useWriteScope } from '../../lib/useWriteScope'
import { formatApiError } from '../../lib/api/errors'
import { invalidateTariffQueries } from './invalidate'
import type { Tariff, TariffSeries, TariffVersion, TariffVersionInput } from '../../types/api'

/** Which task the versioning flow currently has open in the pane, and against what. */
export type VersionDialog =
  | { kind: 'new-version', series: TariffSeries, source: TariffVersion }
  | { kind: 'duplicate', series: TariffSeries, source: TariffVersion }
  | { kind: 'rename', series: TariffSeries, source: TariffVersion }
  | null

type Params = {
  selectedZevId?: string
  canWrite?: boolean
  queryClient: QueryClient
  pushToast: (message: string, tone?: 'success' | 'error') => void
  t: (key: string, options?: Record<string, unknown>) => string
  /** The task finished and its form closed: select the version or tariff it produced. */
  onSaved?: (saved: Tariff, kind: 'new-version' | 'duplicate' | 'rename') => void
}

export function useTariffVersions({ selectedZevId, canWrite = true, queryClient, pushToast, t, onSaved }: Params) {
  const { user } = useAuth()
  const { scope, isCurrent, assertWritable } = useWriteScope({ selectedZevId, canWrite, accountId: user?.id }, t('common.error'))
  const [dialog, setDialog] = useState<VersionDialog>(null)
  // A failure that belongs to the open form: shown in it, not only as a toast.
  const [saveError, setSaveError] = useState<string | null>(null)
  // Which editing session a request belongs to: a save completing after its
  // form was closed, or another opened, must not close or select anything.
  const session = useRef(0)

  function startSession() {
    session.current += 1
    setSaveError(null)
  }

  useLayoutEffect(() => {
    startSession()
    setDialog(null)
  }, [scope])

  type Submitted = { scope: typeof scope; session: number }

  async function complete(kind: 'new-version' | 'duplicate' | 'rename', message: string, saved: Tariff, variables: Submitted) {
    // Selecting what was saved needs the series to contain it.
    await invalidateTariffQueries(queryClient, variables.scope.selectedZevId)
    if (!isCurrent(variables.scope)) return
    pushToast(message, 'success')
    if (variables.session !== session.current) return
    startSession()
    setDialog(null)
    onSaved?.(saved, kind)
  }

  function failed(message: string, error: unknown, variables: Submitted) {
    if (isCurrent(variables.scope) && variables.session === session.current) {
      setSaveError(formatApiError(error, message))
    }
  }

  const newVersionMutation = useMutation({
    mutationFn: ({ id, payload, scope: submittingScope }: { id: string, payload: TariffVersionInput; scope: typeof scope; session: number }) => {
      assertWritable(submittingScope)
      return createTariffVersion(id, payload)
    },
    onSuccess: (saved, variables) => complete('new-version', t('pages.tariffs.messages.versionCreated'), saved, variables),
    onError: (error, variables) => failed(t('pages.tariffs.messages.versionFailed'), error, variables),
  })

  const duplicateMutation = useMutation({
    mutationFn: ({ id, payload, scope: submittingScope }: { id: string, payload: TariffVersionInput & { name: string }; scope: typeof scope; session: number }) => {
      assertWritable(submittingScope)
      return duplicateTariff(id, payload)
    },
    onSuccess: (saved, variables) => complete('duplicate', t('pages.tariffs.messages.duplicated'), saved, variables),
    onError: (error, variables) => failed(t('pages.tariffs.messages.duplicateFailed'), error, variables),
  })

  const renameMutation = useMutation({
    mutationFn: ({ id, name, scope: submittingScope }: { id: string, name: string; scope: typeof scope; session: number }) => {
      assertWritable(submittingScope)
      return renameTariffSeries(id, name)
    },
    onSuccess: (saved, variables) => complete('rename', t('pages.tariffs.messages.renamed'), saved, variables),
    onError: (error, variables) => failed(t('pages.tariffs.messages.renameFailed'), error, variables),
  })

  function open(next: NonNullable<VersionDialog>) {
    startSession()
    setDialog(next)
  }

  return {
    dialog,
    saveError,
    closeDialog: () => {
      startSession()
      setDialog(null)
    },
    openNewVersion: (series: TariffSeries, source: TariffVersion) => open({ kind: 'new-version', series, source }),
    openDuplicate: (series: TariffSeries, source: TariffVersion) => open({ kind: 'duplicate', series, source }),
    openRename: (series: TariffSeries, source: TariffVersion) => open({ kind: 'rename', series, source }),
    submitNewVersion: (id: string, payload: TariffVersionInput) => {
      if (canWrite && selectedZevId && isCurrent(scope)) {
        setSaveError(null)
        newVersionMutation.mutate({ id, payload, scope, session: session.current })
      }
    },
    submitDuplicate: (id: string, payload: TariffVersionInput & { name: string }) => {
      if (canWrite && selectedZevId && isCurrent(scope)) {
        setSaveError(null)
        duplicateMutation.mutate({ id, payload, scope, session: session.current })
      }
    },
    submitRename: (id: string, name: string) => {
      if (canWrite && selectedZevId && isCurrent(scope)) {
        setSaveError(null)
        renameMutation.mutate({ id, name, scope, session: session.current })
      }
    },
    isPending: newVersionMutation.isPending || duplicateMutation.isPending || renameMutation.isPending,
  }
}
