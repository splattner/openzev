import { useMutation, type QueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { createTariffVersion, duplicateTariff, renameTariffSeries } from '../../lib/api/tariffs'
import { formatApiError } from '../../lib/api/errors'
import { invalidateTariffQueries } from './invalidate'
import type { TariffSeries, TariffVersion, TariffVersionInput } from '../../types/api'

/** Which dialog the versioning flow currently has open, and against what. */
export type VersionDialog =
  | { kind: 'new-version', series: TariffSeries, source: TariffVersion }
  | { kind: 'duplicate', series: TariffSeries, source: TariffVersion }
  | { kind: 'rename', series: TariffSeries, source: TariffVersion }
  | null

type Params = {
  selectedZevId?: string
  queryClient: QueryClient
  pushToast: (message: string, tone?: 'success' | 'error') => void
  t: (key: string, options?: Record<string, unknown>) => string
}

export function useTariffVersions({ selectedZevId, queryClient, pushToast, t }: Params) {
  const [dialog, setDialog] = useState<VersionDialog>(null)

  const invalidate = () => invalidateTariffQueries(queryClient, selectedZevId)

  const newVersionMutation = useMutation({
    mutationFn: ({ id, payload }: { id: string, payload: TariffVersionInput }) =>
      createTariffVersion(id, payload),
    onSuccess: () => {
      setDialog(null)
      pushToast(t('pages.tariffs.messages.versionCreated'), 'success')
      invalidate()
    },
    onError: (error) => pushToast(formatApiError(error, t('pages.tariffs.messages.versionFailed')), 'error'),
  })

  const duplicateMutation = useMutation({
    mutationFn: ({ id, payload }: { id: string, payload: TariffVersionInput & { name: string } }) =>
      duplicateTariff(id, payload),
    onSuccess: () => {
      setDialog(null)
      pushToast(t('pages.tariffs.messages.duplicated'), 'success')
      invalidate()
    },
    onError: (error) => pushToast(formatApiError(error, t('pages.tariffs.messages.duplicateFailed')), 'error'),
  })

  const renameMutation = useMutation({
    mutationFn: ({ id, name }: { id: string, name: string }) => renameTariffSeries(id, name),
    onSuccess: () => {
      setDialog(null)
      pushToast(t('pages.tariffs.messages.renamed'), 'success')
      invalidate()
    },
    onError: (error) => pushToast(formatApiError(error, t('pages.tariffs.messages.renameFailed')), 'error'),
  })

  return {
    dialog,
    closeDialog: () => setDialog(null),
    openNewVersion: (series: TariffSeries, source: TariffVersion) =>
      setDialog({ kind: 'new-version', series, source }),
    openDuplicate: (series: TariffSeries, source: TariffVersion) =>
      setDialog({ kind: 'duplicate', series, source }),
    openRename: (series: TariffSeries, source: TariffVersion) =>
      setDialog({ kind: 'rename', series, source }),
    submitNewVersion: (id: string, payload: TariffVersionInput) =>
      newVersionMutation.mutate({ id, payload }),
    submitDuplicate: (id: string, payload: TariffVersionInput & { name: string }) =>
      duplicateMutation.mutate({ id, payload }),
    submitRename: (id: string, name: string) => renameMutation.mutate({ id, name }),
    isPending: newVersionMutation.isPending || duplicateMutation.isPending || renameMutation.isPending,
  }
}
