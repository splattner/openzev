import { useCallback, useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome'
import { faArrowsRotate, faChartLine, faClockRotateLeft, faEllipsis, faEraser, faMagnifyingGlass, faPen, faPlus, faTrash } from '@fortawesome/free-solid-svg-icons'
import { useTranslation } from 'react-i18next'
import { ActionMenu } from '../components/ActionMenu'
import { DataTable, type ColumnDef } from '../components/DataTable'
import { ConfirmDialog } from '../components/ConfirmDialog'
import { EmptyState } from '../components/EmptyState'
import { FormModal } from '../components/FormModal'
import { StatCard } from '../components/StatCard'
import { PageSkeleton } from '../components/PageSkeleton'
import { DynamicPriceHistoryModal } from '../features/tariffs/DynamicPriceHistoryModal'
import { DynamicSourceFormModal } from '../features/tariffs/DynamicSourceFormModal'
import { fetchAuditEvents } from '../lib/api/audit'
import {
  clearDynamicSourcePrices,
  deleteDynamicTariffSource,
  fetchDynamicTariffSources,
  queueDynamicSourceFetch,
  recheckDynamicTariffSource,
} from '../lib/api/tariffs'
import { formatApiError } from '../lib/api/errors'
import { formatDateTime, useAppSettings } from '../lib/appSettings'
import { queryKeys } from '../lib/api/queryKeys'
import { useToast } from '../lib/toast'
import type { AuditEvent, DynamicTariffSource } from '../types/api'

function statusClass(status: DynamicTariffSource['last_fetch_status']): string {
  if (status === 'ok') return 'badge badge-success'
  if (status === 'failed') return 'badge badge-danger'
  return 'badge badge-neutral'
}

export function AdminDynamicSourcesPanel() {
  const { t } = useTranslation()
  const { settings } = useAppSettings()
  const { pushToast } = useToast()
  const queryClient = useQueryClient()
  const [formSource, setFormSource] = useState<DynamicTariffSource | null | undefined>(undefined)
  const [historySource, setHistorySource] = useState<DynamicTariffSource | null>(null)
  const [activitySource, setActivitySource] = useState<DynamicTariffSource | null>(null)
  // One dialog shape for both destructive actions: they differ only in what
  // they destroy, and typing the source's own label back is the guard on
  // either. No reason field — a free-text box in front of an irreversible
  // action invites a keystroke, while the label has to be read off the row
  // that is about to go.
  const [destructive, setDestructive] = useState<
    { mode: 'clear' | 'delete'; source: DynamicTariffSource } | null
  >(null)
  const [confirmation, setConfirmation] = useState('')

  const openDestructiveDialog = useCallback(
    (mode: 'clear' | 'delete', source: DynamicTariffSource) => {
      setConfirmation('')
      setDestructive({ mode, source })
    },
    [],
  )

  const closeDestructiveDialog = useCallback(() => {
    setDestructive(null)
    setConfirmation('')
  }, [])

  const sourcesQuery = useQuery({
    queryKey: queryKeys.tariffs.dynamicSources(),
    queryFn: fetchDynamicTariffSources,
    refetchInterval: 30_000,
  })

  const fetchMutation = useMutation({
    mutationFn: ({ source, backfill }: { source: DynamicTariffSource; backfill: boolean }) =>
      queueDynamicSourceFetch(source.id, backfill),
    onSuccess: async () => {
      pushToast(t('pages.dynamicSources.fetchQueued'), 'success')
      await queryClient.invalidateQueries({ queryKey: queryKeys.tariffs.dynamicSources() })
      await queryClient.invalidateQueries({ queryKey: ['admin', 'audit-events'] })
    },
    onError: (error) => pushToast(formatApiError(error, t('pages.dynamicSources.fetchError')), 'error'),
  })

  const recheckMutation = useMutation({
    mutationFn: (source: DynamicTariffSource) => recheckDynamicTariffSource(source.id),
    onSuccess: async (saved) => {
      pushToast(t('pages.dynamicSources.recheckSuccess'), 'success')
      for (const warning of saved.warnings) {
        pushToast(warning, 'info')
      }
      await queryClient.invalidateQueries({ queryKey: queryKeys.tariffs.dynamicSources() })
      await queryClient.invalidateQueries({ queryKey: ['admin', 'audit-events'] })
    },
    onError: (error) => pushToast(formatApiError(error, t('pages.dynamicSources.recheckError')), 'error'),
  })

  const clearMutation = useMutation({
    mutationFn: (source: DynamicTariffSource) => clearDynamicSourcePrices(source.id, confirmation),
    onSuccess: async (result) => {
      pushToast(t('pages.dynamicSources.cleared', { count: result.deleted_points }), 'success')
      closeDestructiveDialog()
      await queryClient.invalidateQueries({ queryKey: queryKeys.tariffs.dynamicSources() })
      await queryClient.invalidateQueries({ queryKey: ['admin', 'audit-events'] })
    },
    onError: (error) => pushToast(formatApiError(error, t('pages.dynamicSources.clearError')), 'error'),
  })

  const deleteMutation = useMutation({
    mutationFn: (source: DynamicTariffSource) => deleteDynamicTariffSource(source.id, confirmation),
    onSuccess: async () => {
      pushToast(t('pages.dynamicSources.deleted'), 'success')
      closeDestructiveDialog()
      await queryClient.invalidateQueries({ queryKey: queryKeys.tariffs.dynamicSources() })
      await queryClient.invalidateQueries({ queryKey: ['admin', 'audit-events'] })
    },
    onError: (error) => pushToast(formatApiError(error, t('pages.dynamicSources.deleteError')), 'error'),
  })

  const activityQuery = useQuery({
    queryKey: queryKeys.admin.auditEvents({ target: activitySource?.id }),
    queryFn: () => fetchAuditEvents({
      target_type: 'tariffs.DynamicTariffSource',
      target_id: activitySource!.id,
    }),
    enabled: Boolean(activitySource),
  })

  const columns = useMemo<ColumnDef<DynamicTariffSource, unknown>[]>(() => [
    {
      accessorKey: 'label',
      header: t('pages.dynamicSources.columns.source'),
      cell: ({ row }) => (
        <div>
          <strong>{row.original.label}</strong>
          <div className="muted">{row.original.url}</div>
          <div className="muted">
            {t(`pages.dynamicSources.versions.${row.original.api_version}` as Parameters<typeof t>[0])}
            {' · '}
            {t(`pages.dynamicSources.types.${row.original.tariff_type}` as Parameters<typeof t>[0])}
            {row.original.tariff_name ? ` · ${row.original.tariff_name}` : ''}
          </div>
        </div>
      ),
    },
    {
      accessorKey: 'last_fetch_status',
      header: t('pages.dynamicSources.columns.status'),
      cell: ({ row }) => (
        <div>
          <span className={statusClass(row.original.last_fetch_status)}>
            {t(`pages.dynamicSources.status.${row.original.last_fetch_status}` as Parameters<typeof t>[0])}
          </span>
          {row.original.last_fetch_error && <div className="text-danger">{row.original.last_fetch_error}</div>}
        </div>
      ),
    },
    {
      accessorKey: 'last_fetch_at',
      header: t('pages.dynamicSources.columns.lastFetch'),
      cell: ({ row }) => formatDateTime(row.original.last_fetch_at, settings),
    },
    {
      accessorKey: 'point_count',
      header: t('pages.dynamicSources.columns.points'),
      meta: { numeric: true },
    },
    {
      id: 'reuse',
      header: t('pages.dynamicSources.columns.reuse'),
      cell: ({ row }) => t('pages.dynamicSources.reuseSummary', {
        tariffs: row.original.linked_tariff_count,
        zevs: row.original.linked_zev_count,
      }),
    },
    {
      id: 'actions',
      header: '',
      enableSorting: false,
      cell: ({ row }) => {
        const source = row.original
        return (
          <ActionMenu
            label={t('common.actions')}
            icon={<FontAwesomeIcon icon={faEllipsis} fixedWidth />}
            items={[
              {
                key: 'history', label: t('pages.dynamicSources.history.open'),
                icon: <FontAwesomeIcon icon={faChartLine} fixedWidth />,
                onClick: () => setHistorySource(source),
              },
              {
                key: 'activity', label: t('pages.dynamicSources.activity.open'),
                icon: <FontAwesomeIcon icon={faClockRotateLeft} fixedWidth />,
                onClick: () => setActivitySource(source),
              },
              {
                key: 'fetch', label: t('pages.dynamicSources.fetchNow'), section: t('pages.dynamicSources.actions.fetch'),
                icon: <FontAwesomeIcon icon={faArrowsRotate} fixedWidth />,
                onClick: () => fetchMutation.mutate({ source, backfill: false }),
              },
              {
                key: 'backfill', label: t('pages.dynamicSources.fetchBackfill'),
                icon: <FontAwesomeIcon icon={faClockRotateLeft} fixedWidth />,
                disabled: !source.supports_backfill,
                onClick: () => fetchMutation.mutate({ source, backfill: true }),
              },
              {
                key: 'edit', label: t('common.edit'), section: t('pages.dynamicSources.actions.manage'),
                icon: <FontAwesomeIcon icon={faPen} fixedWidth />,
                onClick: () => setFormSource(source),
              },
              {
                // The initial probe can under-detect supports_range (a
                // transient blip, or nothing published yet at that moment),
                // and identity fields cannot be edited afterwards — this is
                // the only way back short of deleting and recreating the
                // source.
                key: 'recheck', label: t('pages.dynamicSources.recheckAction'),
                icon: <FontAwesomeIcon icon={faMagnifyingGlass} fixedWidth />,
                onClick: () => recheckMutation.mutate(source),
              },
              {
                key: 'clear', label: t('pages.dynamicSources.clearAction'), danger: true,
                icon: <FontAwesomeIcon icon={faEraser} fixedWidth />,
                onClick: () => openDestructiveDialog('clear', source),
              },
              {
                // A source still pricing a tariff cannot be deleted — the FK
                // is PROTECT, and the server refuses with a 409 naming what
                // uses it. Disabling here says so before the round trip, and
                // the label says *why*: a greyed-out item with no reason
                // reads as broken rather than as blocked.
                key: 'delete',
                label: source.linked_tariff_count > 0
                  ? t('pages.dynamicSources.deleteActionInUse')
                  : t('pages.dynamicSources.deleteAction'),
                danger: true,
                icon: <FontAwesomeIcon icon={faTrash} fixedWidth />,
                disabled: source.linked_tariff_count > 0,
                onClick: () => openDestructiveDialog('delete', source),
              },
            ]}
          />
        )
      },
    },
  ], [fetchMutation, openDestructiveDialog, recheckMutation, settings, t])

  const sources = sourcesQuery.data ?? []
  const failed = sources.filter((source) => source.last_fetch_status === 'failed').length
  const reused = sources.filter((source) => source.linked_zev_count > 1).length
  const points = sources.reduce((sum, source) => sum + source.point_count, 0)

  const activityColumns = useMemo<ColumnDef<AuditEvent, unknown>[]>(() => [
    { accessorKey: 'created_at', header: t('pages.dynamicSources.activity.time'), cell: ({ row }) => formatDateTime(row.original.created_at, settings) },
    { accessorKey: 'status', header: t('pages.dynamicSources.columns.status'), cell: ({ row }) => <span className={row.original.status === 'failed' ? 'badge badge-danger' : row.original.status === 'success' ? 'badge badge-success' : 'badge badge-info'}>{t(`pages.auditLogs.statuses.${row.original.status}`)}</span> },
    { accessorKey: 'summary', header: t('pages.dynamicSources.activity.event') },
  ], [settings, t])

  return (
    <div className="page-stack">
      <section className="card tariff-toolbar">
        <div className="tariff-toolbar-header">
          <div>
            <h3>{t('pages.dynamicSources.title')}</h3>
            <p className="muted">{t('pages.dynamicSources.description')}</p>
          </div>
          <button className="button button-primary" type="button" onClick={() => setFormSource(null)}>
            <FontAwesomeIcon icon={faPlus} fixedWidth />
            {t('pages.dynamicSources.createAction')}
          </button>
        </div>
      </section>

      {sourcesQuery.isLoading ? <PageSkeleton variant="kpiRow" /> : (
        <div className="kpi-row">
          <StatCard label={t('pages.dynamicSources.stats.sources')} value={sources.length} />
          <StatCard label={t('pages.dynamicSources.stats.points')} value={points} />
          <StatCard label={t('pages.dynamicSources.stats.reused')} value={reused} />
          <StatCard label={t('pages.dynamicSources.stats.failed')} value={failed} tone={failed ? 'danger' : 'success'} />
        </div>
      )}

      {sourcesQuery.isError && <div className="error-banner">{t('pages.dynamicSources.loadError')}</div>}
      {sourcesQuery.isLoading ? <PageSkeleton variant="table" /> : sources.length === 0 ? (
        <EmptyState
          titleKey="pages.dynamicSources.empty"
          descriptionKey="pages.dynamicSources.description"
          actions={[{
            labelKey: 'pages.dynamicSources.createAction',
            icon: faPlus,
            onClick: () => setFormSource(null),
          }]}
        />
      ) : (
        <DataTable
          data={sources}
          columns={columns}
          getRowId={(source) => source.id}
        />
      )}

      <DynamicSourceFormModal
        isOpen={formSource !== undefined}
        source={formSource ?? null}
        onClose={() => setFormSource(undefined)}
      />
      <DynamicPriceHistoryModal source={historySource} onClose={() => setHistorySource(null)} />

      <FormModal
        isOpen={Boolean(activitySource)}
        title={t('pages.dynamicSources.activity.title', { label: activitySource?.label ?? '' })}
        onClose={() => setActivitySource(null)}
        maxWidth="900px"
      >
        <DataTable
          data={activityQuery.data?.results ?? []}
          columns={activityColumns}
          getRowId={(event) => event.id}
          loading={activityQuery.isLoading}
          emptyMessage={t('pages.dynamicSources.activity.empty')}
        />
      </FormModal>

      {destructive && (
        <ConfirmDialog
          title={t(destructive.mode === 'delete'
            ? 'pages.dynamicSources.deleteTitle'
            : 'pages.dynamicSources.clearTitle')}
          message={t(destructive.mode === 'delete'
            ? 'pages.dynamicSources.deleteWarning'
            : 'pages.dynamicSources.clearWarning')}
          isDangerous
          isLoading={clearMutation.isPending || deleteMutation.isPending}
          confirmText={t(destructive.mode === 'delete'
            ? 'pages.dynamicSources.deleteAction'
            : 'pages.dynamicSources.clearAction')}
          confirmDisabled={confirmation.trim() !== destructive.source.label.trim()}
          onCancel={closeDestructiveDialog}
          onConfirm={() => (destructive.mode === 'delete' ? deleteMutation : clearMutation)
            .mutate(destructive.source)}
        >
          <label style={{ gridColumn: '1 / -1' }}>
            <span>{t('pages.dynamicSources.confirmLabel', { label: destructive.source.label })}</span>
            <input value={confirmation} onChange={(event) => setConfirmation(event.target.value)} required />
          </label>
        </ConfirmDialog>
      )}
    </div>
  )
}
