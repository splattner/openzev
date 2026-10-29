import { useMutation, type QueryClient } from '@tanstack/react-query'
import { useLayoutEffect, useMemo, useRef, useState } from 'react'
import {
  createTariff,
  createTariffPeriod,
  deleteTariff,
  deleteTariffPeriod,
  updateTariff,
  updateTariffPeriod,
} from '../../lib/api/tariffs'
import { useAuth } from '../../lib/auth'
import { useWriteScope } from '../../lib/useWriteScope'
import { formatApiError, formatApiErrorRest, splitIndexedErrors, type ItemFieldErrors } from '../../lib/api/errors'
import { invalidateTariffQueries } from './invalidate'
import type { Tariff, TariffInput, TariffPeriod, TariffPeriodInput } from '../../types/api'

type ConfirmOptions = {
  title: string
  message: string
  confirmText: string
  isDangerous: boolean
  onConfirm: () => void
}

type TariffCrudParams = {
  selectedZevId?: string
  canWrite?: boolean
  tariffs: Tariff[]
  periods: TariffPeriod[]
  bandableTariffs: Tariff[]
  tariffNameById: Map<string, string>
  queryClient: QueryClient
  pushToast: (message: string, tone?: 'success' | 'error') => void
  confirm: (options: ConfirmOptions) => void
  t: (key: string, options?: Record<string, unknown>) => string
  /** A tariff was created or changed and its form closed: select what was saved. */
  onTariffSaved?: (saved: Tariff, kind: 'created' | 'updated') => void
  /** A band was saved and its form closed. */
  onPeriodSaved?: () => void
}

export function resolvePeriodTariffId(bandableTariffs: Tariff[], tariffId?: string): string | undefined {
  return tariffId ?? bandableTariffs[0]?.id
}

/**
 * Tariff and band writes: the form state the detail pane shows while one is
 * open, and the requests behind them. Saving closes the form only for the
 * community, account and editing session that asked.
 */
export function useTariffCrud({
  selectedZevId,
  canWrite = true,
  tariffs,
  periods,
  bandableTariffs,
  tariffNameById,
  queryClient,
  pushToast,
  confirm,
  t,
  onTariffSaved,
  onPeriodSaved,
}: TariffCrudParams) {
  const { user } = useAuth()
  const { scope, isCurrent, assertWritable } = useWriteScope({ selectedZevId, canWrite, accountId: user?.id }, t('common.error'))
  const [editingTariffId, setEditingTariffId] = useState<string | null>(null)
  const [editingPeriodId, setEditingPeriodId] = useState<string | null>(null)
  const [periodTariffId, setPeriodTariffId] = useState<string | undefined>(undefined)
  const [tariffFormOpen, setTariffFormOpen] = useState(false)
  const [periodFormOpen, setPeriodFormOpen] = useState(false)
  // A failure that belongs to the open form: shown in it, not only as a toast.
  const [saveError, setSaveError] = useState<string | null>(null)
  // What the server rejected on the bands sent with a new tariff, by position.
  const [saveBandErrors, setSaveBandErrors] = useState<ItemFieldErrors[] | null>(null)
  // Which editing session a request belongs to. A save that completes after
  // its form was closed, or after another one opened, must not close, select
  // or overwrite anything in the newer session.
  const session = useRef(0)

  function startSession() {
    session.current += 1
    setSaveError(null)
    setSaveBandErrors(null)
  }

  useLayoutEffect(() => {
    startSession()
    setTariffFormOpen(false)
    setPeriodFormOpen(false)
    setEditingTariffId(null)
    setEditingPeriodId(null)
    setPeriodTariffId(undefined)
  }, [scope])

  const editingTariff = useMemo(
    () => tariffs.find((tariff) => tariff.id === editingTariffId),
    [tariffs, editingTariffId],
  )

  const editingPeriod = useMemo(
    () => periods.find((period) => period.id === editingPeriodId),
    [periods, editingPeriodId],
  )

  const tariffMutation = useMutation({
    mutationFn: ({ id, payload, scope: submittingScope }: { id?: string; payload: TariffInput; scope: typeof scope; session: number }) => {
      assertWritable(submittingScope)
      if (id) {
        return updateTariff(id, payload)
      }
      return createTariff(payload)
    },
    onSuccess: async (saved, variables) => {
      // Selecting what was saved needs the series to contain it.
      await invalidateTariffQueries(queryClient, variables.scope.selectedZevId)
      if (!isCurrent(variables.scope)) return
      pushToast(
        variables.id ? t('pages.tariffs.messages.updated') : t('pages.tariffs.messages.created'),
        'success',
      )
      if (variables.session !== session.current) return
      startSession()
      setEditingTariffId(null)
      setTariffFormOpen(false)
      onTariffSaved?.(saved, variables.id ? 'updated' : 'created')
    },
    onError: (error, variables) => {
      if (isCurrent(variables.scope) && variables.session === session.current) {
        // A band the server refused is marked on its own row; the notice only
        // carries what is left (or says that bands were refused).
        const { items, rest } = splitIndexedErrors(error, 'initial_periods')
        if (items) {
          setSaveBandErrors(items)
          setSaveError(formatApiErrorRest(rest, t('pages.tariffs.messages.bandsRejected')))
        } else {
          setSaveError(formatApiError(error, t('pages.tariffs.messages.saveFailed')))
        }
      }
    },
  })

  const deleteTariffMutation = useMutation({
    mutationFn: ({ id, scope: submittingScope }: { id: string; scope: typeof scope }) => {
      assertWritable(submittingScope)
      return deleteTariff(id)
    },
    onSuccess: (_, variables) => {
      void invalidateTariffQueries(queryClient, variables.scope.selectedZevId)
      if (!isCurrent(variables.scope)) return
      pushToast(t('pages.tariffs.messages.deleted'), 'success')
      // Deleted from its own form: nothing left to edit.
      if (variables.id === editingTariffId) closeTariffForm()
    },
    onError: (error, variables) => {
      if (isCurrent(variables.scope)) pushToast(formatApiError(error, t('pages.tariffs.messages.deleteFailed')), 'error')
    },
  })

  const periodMutation = useMutation({
    mutationFn: ({ id, payload, scope: submittingScope }: { id?: string; payload: TariffPeriodInput; scope: typeof scope; session: number }) => {
      assertWritable(submittingScope)
      if (id) {
        return updateTariffPeriod(id, payload)
      }
      return createTariffPeriod(payload)
    },
    onSuccess: async (_, variables) => {
      await invalidateTariffQueries(queryClient, variables.scope.selectedZevId)
      if (!isCurrent(variables.scope)) return
      pushToast(
        variables.id ? t('pages.tariffs.messages.periodUpdated') : t('pages.tariffs.messages.periodCreated'),
        'success',
      )
      if (variables.session !== session.current) return
      startSession()
      setEditingPeriodId(null)
      setPeriodTariffId(undefined)
      setPeriodFormOpen(false)
      onPeriodSaved?.()
    },
    onError: (error, variables) => {
      if (isCurrent(variables.scope) && variables.session === session.current) {
        setSaveError(formatApiError(error, t('pages.tariffs.messages.periodSaveFailed')))
      }
    },
  })

  const deletePeriodMutation = useMutation({
    mutationFn: ({ id, scope: submittingScope }: { id: string; scope: typeof scope }) => {
      assertWritable(submittingScope)
      return deleteTariffPeriod(id)
    },
    onSuccess: (_, variables) => {
      void invalidateTariffQueries(queryClient, variables.scope.selectedZevId)
      if (!isCurrent(variables.scope)) return
      pushToast(t('pages.tariffs.messages.periodDeleted'), 'success')
      if (variables.id === editingPeriodId) closePeriodForm()
    },
    onError: (error, variables) => {
      if (isCurrent(variables.scope)) pushToast(formatApiError(error, t('pages.tariffs.messages.periodDeleteFailed')), 'error')
    },
  })

  function submitTariff(payload: TariffInput) {
    if (!isCurrent(scope)) return
    if (!selectedZevId || !canWrite) {
      pushToast(t('pages.tariffs.messages.selectZevBeforeSave'), 'error')
      return
    }
    setSaveError(null)
    setSaveBandErrors(null)
    tariffMutation.mutate({ id: editingTariffId || undefined, payload: { ...payload, zev: selectedZevId }, scope, session: session.current })
  }

  function submitPeriod(payload: TariffPeriodInput) {
    if (!isCurrent(scope)) return
    if (!selectedZevId || !canWrite) {
      pushToast(t('pages.tariffs.messages.periodSaveFailed'), 'error')
      return
    }
    setSaveError(null)
    periodMutation.mutate({ id: editingPeriodId || undefined, payload, scope, session: session.current })
  }

  function startTariffEdit(tariff: Tariff) {
    startSession()
    setEditingTariffId(tariff.id)
    setTariffFormOpen(true)
  }

  function startPeriodEdit(period: TariffPeriod) {
    startSession()
    setEditingPeriodId(period.id)
    setPeriodTariffId(period.tariff)
    setPeriodFormOpen(true)
  }

  function openCreateTariff() {
    if (!selectedZevId) {
      pushToast(t('pages.tariffs.messages.selectZevBeforeCreate'), 'error')
      return
    }
    startSession()
    setEditingTariffId(null)
    setTariffFormOpen(true)
  }

  function closeTariffForm() {
    startSession()
    setTariffFormOpen(false)
    setEditingTariffId(null)
  }

  function openCreatePeriod(tariffId?: string) {
    const defaultTariffId = resolvePeriodTariffId(bandableTariffs, tariffId)

    if (!defaultTariffId) {
      pushToast(t('pages.tariffs.messages.createEnergyTariffFirst'), 'error')
      return
    }
    startSession()
    setEditingPeriodId(null)
    setPeriodTariffId(defaultTariffId)
    setPeriodFormOpen(true)
  }

  function closePeriodForm() {
    startSession()
    setPeriodFormOpen(false)
    setEditingPeriodId(null)
    setPeriodTariffId(undefined)
  }

  /** `window` is the version's validity as the pane writes it: the message names which one goes. */
  function confirmDeleteTariff(tariff: Pick<Tariff, 'id' | 'name'>, window: string) {
    confirm({
      title: t('pages.tariffs.deleteTitle'),
      message: t('pages.tariffs.deleteMessage', { name: tariff.name, window }),
      confirmText: t('pages.tariffs.deleteConfirm'),
      isDangerous: true,
      onConfirm: () => {
        if (scope.canWrite && isCurrent(scope)) deleteTariffMutation.mutate({ id: tariff.id, scope })
      },
    })
  }

  function confirmDeletePeriod(period: TariffPeriod) {
    confirm({
      title: t('pages.tariffs.deletePeriodTitle'),
      message: t('pages.tariffs.deletePeriodMessage', { name: tariffNameById.get(period.tariff) ?? period.tariff }),
      confirmText: t('pages.tariffs.deletePeriodConfirm'),
      isDangerous: true,
      onConfirm: () => {
        if (scope.canWrite && isCurrent(scope)) deletePeriodMutation.mutate({ id: period.id, scope })
      },
    })
  }

  return {
    tariffFormOpen,
    periodFormOpen,
    editingTariffId,
    editingPeriodId,
    periodTariffId,
    editingTariff,
    editingPeriod,
    saveError,
    saveBandErrors,
    tariffPending: tariffMutation.isPending,
    periodPending: periodMutation.isPending,
    deleteTariffPending: deleteTariffMutation.isPending,
    deletePeriodPending: deletePeriodMutation.isPending,
    submitTariff,
    submitPeriod,
    startTariffEdit,
    startPeriodEdit,
    openCreateTariff,
    closeTariffForm,
    openCreatePeriod,
    closePeriodForm,
    confirmDeleteTariff,
    confirmDeletePeriod,
  }
}
