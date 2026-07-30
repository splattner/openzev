import { useMutation, type QueryClient } from '@tanstack/react-query'
import { useState, type ChangeEvent } from 'react'
import { exportTariffs, importTariffs } from '../../lib/api/tariffs'
import { formatApiError } from '../../lib/api/errors'
import { invalidateTariffQueries } from './invalidate'
import type { TariffPreset } from '../../types/api'

type TariffTransferParams = {
  selectedZevId?: string
  queryClient: QueryClient
  pushToast: (message: string, tone?: 'success' | 'error') => void
  t: (key: string, options?: Record<string, unknown>) => string
}

const INVALID_IMPORT_FORMAT_ERROR = 'INVALID_IMPORT_FORMAT_ERROR'

export function parseTariffImportContent(content: string): TariffPreset[] {
  const tariffs = JSON.parse(content) as TariffPreset[]
  if (!Array.isArray(tariffs)) {
    throw new Error(INVALID_IMPORT_FORMAT_ERROR)
  }
  return tariffs
}

export function useTariffTransfer({ selectedZevId, queryClient, pushToast, t }: TariffTransferParams) {
  const [showExportModal, setShowExportModal] = useState(false)
  const [showImportModal, setShowImportModal] = useState(false)

  const exportMutation = useMutation({
    mutationFn: exportTariffs,
    onSuccess: (data) => {
      const jsonString = JSON.stringify(data, null, 2)
      const blob = new Blob([jsonString], { type: 'application/json' })
      const url = URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = url
      link.download = `tariffs-${selectedZevId}.json`
      document.body.appendChild(link)
      link.click()
      document.body.removeChild(link)
      URL.revokeObjectURL(url)
      setShowExportModal(false)
      pushToast(t('pages.tariffs.messages.exported'), 'success')
    },
    onError: (error) => pushToast(formatApiError(error, t('pages.tariffs.messages.exportFailed')), 'error'),
  })

  const importMutation = useMutation({
    mutationFn: ({ zevId, tariffs }: { zevId: string; tariffs: TariffPreset[] }) => importTariffs(zevId, tariffs),
    onSuccess: (result) => {
      setShowImportModal(false)
      invalidateTariffQueries(queryClient, selectedZevId)
      pushToast(t('pages.tariffs.messages.imported', { count: result.created }), 'success')
    },
    onError: (error) => pushToast(formatApiError(error, t('pages.tariffs.messages.importFailed')), 'error'),
  })

  function openExportModal() {
    setShowExportModal(true)
  }

  function closeExportModal() {
    setShowExportModal(false)
  }

  function handleExport() {
    if (!selectedZevId) {
      pushToast(t('pages.tariffs.messages.selectZevToExport'), 'error')
      return
    }
    exportMutation.mutate(selectedZevId)
  }

  function openImportModal() {
    setShowImportModal(true)
  }

  function closeImportModal() {
    setShowImportModal(false)
  }

  function handleImportFile(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0]
    if (!file) return

    const reader = new FileReader()
    reader.onload = (e) => {
      try {
        const content = e.target?.result as string
        const tariffs = parseTariffImportContent(content)
        if (!selectedZevId) {
          pushToast(t('pages.tariffs.messages.selectZevToImport'), 'error')
          return
        }
        importMutation.mutate({ zevId: selectedZevId, tariffs })
      } catch (error) {
        if (error instanceof Error && error.message === INVALID_IMPORT_FORMAT_ERROR) {
          pushToast(t('pages.tariffs.messages.invalidImportFormat'), 'error')
          return
        }
        pushToast(
          t('pages.tariffs.messages.parseFailed', {
            message: error instanceof Error ? error.message : t('pages.tariffs.messages.unknownError'),
          }),
          'error',
        )
      }
    }
    reader.readAsText(file)
  }

  return {
    showExportModal,
    showImportModal,
    exportPending: exportMutation.isPending,
    openExportModal,
    closeExportModal,
    handleExport,
    openImportModal,
    closeImportModal,
    handleImportFile,
  }
}
