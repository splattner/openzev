import { useMutation, type QueryClient } from '@tanstack/react-query'
import { useMemo, useState } from 'react'
import {
  createTariff,
  createTariffPeriod,
  deleteTariff,
  deleteTariffPeriod,
  updateTariff,
  updateTariffPeriod,
} from '../../lib/api/tariffs'
import { formatApiError } from '../../lib/api/errors'
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
  tariffs: Tariff[]
  periods: TariffPeriod[]
  energyTariffs: Tariff[]
  tariffNameById: Map<string, string>
  queryClient: QueryClient
  pushToast: (message: string, tone?: 'success' | 'error') => void
  confirm: (options: ConfirmOptions) => void
  t: (key: string, options?: Record<string, unknown>) => string
}

export function resolvePeriodModalTariffId(energyTariffs: Tariff[], tariffId?: string): string | undefined {
  return tariffId ?? energyTariffs[0]?.id
}

export function useTariffCrud({
  selectedZevId,
  tariffs,
  periods,
  energyTariffs,
  tariffNameById,
  queryClient,
  pushToast,
  confirm,
  t,
}: TariffCrudParams) {
  const [editingTariffId, setEditingTariffId] = useState<string | null>(null)
  const [editingPeriodId, setEditingPeriodId] = useState<string | null>(null)
  const [periodModalTariffId, setPeriodModalTariffId] = useState<string | undefined>(undefined)
  const [showTariffModal, setShowTariffModal] = useState(false)
  const [showPeriodModal, setShowPeriodModal] = useState(false)

  const editingTariff = useMemo(
    () => tariffs.find((tariff) => tariff.id === editingTariffId),
    [tariffs, editingTariffId],
  )

  const editingPeriod = useMemo(
    () => periods.find((period) => period.id === editingPeriodId),
    [periods, editingPeriodId],
  )

  const tariffMutation = useMutation({
    mutationFn: ({ id, payload }: { id?: string; payload: TariffInput }) => {
      if (id) {
        return updateTariff(id, payload)
      }
      return createTariff(payload)
    },
    onSuccess: (_, variables) => {
      setEditingTariffId(null)
      setShowTariffModal(false)
      pushToast(
        variables.id ? t('pages.tariffs.messages.updated') : t('pages.tariffs.messages.created'),
        'success',
      )
      invalidateTariffQueries(queryClient, selectedZevId)
    },
    onError: (error) => pushToast(formatApiError(error, t('pages.tariffs.messages.saveFailed')), 'error'),
  })

  const deleteTariffMutation = useMutation({
    mutationFn: deleteTariff,
    onSuccess: () => {
      pushToast(t('pages.tariffs.messages.deleted'), 'success')
      invalidateTariffQueries(queryClient, selectedZevId)
    },
    onError: (error) => pushToast(formatApiError(error, t('pages.tariffs.messages.deleteFailed')), 'error'),
  })

  const periodMutation = useMutation({
    mutationFn: ({ id, payload }: { id?: string; payload: TariffPeriodInput }) => {
      if (id) {
        return updateTariffPeriod(id, payload)
      }
      return createTariffPeriod(payload)
    },
    onSuccess: (_, variables) => {
      setEditingPeriodId(null)
      setPeriodModalTariffId(undefined)
      setShowPeriodModal(false)
      pushToast(
        variables.id ? t('pages.tariffs.messages.periodUpdated') : t('pages.tariffs.messages.periodCreated'),
        'success',
      )
      invalidateTariffQueries(queryClient, selectedZevId)
    },
    onError: (error) => pushToast(formatApiError(error, t('pages.tariffs.messages.periodSaveFailed')), 'error'),
  })

  const deletePeriodMutation = useMutation({
    mutationFn: deleteTariffPeriod,
    onSuccess: () => {
      pushToast(t('pages.tariffs.messages.periodDeleted'), 'success')
      invalidateTariffQueries(queryClient, selectedZevId)
    },
    onError: (error) => pushToast(formatApiError(error, t('pages.tariffs.messages.periodDeleteFailed')), 'error'),
  })

  function submitTariff(payload: TariffInput) {
    if (!selectedZevId) {
      pushToast(t('pages.tariffs.messages.selectZevBeforeSave'), 'error')
      return
    }
    tariffMutation.mutate({ id: editingTariffId || undefined, payload: { ...payload, zev: selectedZevId } })
  }

  function submitPeriod(payload: TariffPeriodInput) {
    periodMutation.mutate({ id: editingPeriodId || undefined, payload })
  }

  function startTariffEdit(tariff: Tariff) {
    setEditingTariffId(tariff.id)
    setShowTariffModal(true)
  }

  function startPeriodEdit(period: TariffPeriod) {
    setEditingPeriodId(period.id)
    setPeriodModalTariffId(period.tariff)
    setShowPeriodModal(true)
  }

  function openCreateTariffModal() {
    if (!selectedZevId) {
      pushToast(t('pages.tariffs.messages.selectZevBeforeCreate'), 'error')
      return
    }
    setEditingTariffId(null)
    setShowTariffModal(true)
  }

  function closeTariffModal() {
    setShowTariffModal(false)
    setEditingTariffId(null)
  }

  function openCreatePeriodModal(tariffId?: string) {
    const defaultTariffId = resolvePeriodModalTariffId(energyTariffs, tariffId)

    if (!defaultTariffId) {
      pushToast(t('pages.tariffs.messages.createEnergyTariffFirst'), 'error')
      return
    }
    setEditingPeriodId(null)
    setPeriodModalTariffId(defaultTariffId)
    setShowPeriodModal(true)
  }

  function closePeriodModal() {
    setShowPeriodModal(false)
    setEditingPeriodId(null)
    setPeriodModalTariffId(undefined)
  }

  function confirmDeleteTariff(tariff: Tariff) {
    confirm({
      title: t('pages.tariffs.deleteTitle'),
      message: t('pages.tariffs.deleteMessage', { name: tariff.name }),
      confirmText: t('pages.tariffs.deleteConfirm'),
      isDangerous: true,
      onConfirm: () => deleteTariffMutation.mutate(tariff.id),
    })
  }

  function confirmDeletePeriod(period: TariffPeriod) {
    confirm({
      title: t('pages.tariffs.deletePeriodTitle'),
      message: t('pages.tariffs.deletePeriodMessage', { name: tariffNameById.get(period.tariff) ?? period.tariff }),
      confirmText: t('pages.tariffs.deletePeriodConfirm'),
      isDangerous: true,
      onConfirm: () => deletePeriodMutation.mutate(period.id),
    })
  }

  return {
    showTariffModal,
    showPeriodModal,
    editingTariffId,
    editingPeriodId,
    periodModalTariffId,
    editingTariff,
    editingPeriod,
    tariffPending: tariffMutation.isPending,
    periodPending: periodMutation.isPending,
    deleteTariffPending: deleteTariffMutation.isPending,
    deletePeriodPending: deletePeriodMutation.isPending,
    submitTariff,
    submitPeriod,
    startTariffEdit,
    startPeriodEdit,
    openCreateTariffModal,
    closeTariffModal,
    openCreatePeriodModal,
    closePeriodModal,
    confirmDeleteTariff,
    confirmDeletePeriod,
  }
}
