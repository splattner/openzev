import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useEffectEvent, useLayoutEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { useLocation, useNavigate, useSearchParams } from 'react-router-dom'
import { ConfirmDialog, useConfirmDialog } from '../components/ConfirmDialog'
import { TariffOverview } from '../features/tariffs/TariffOverview'
import { TariffDetailPane, TariffPaneFrame } from '../features/tariffs/TariffDetailPane'
import { useTariffCrud } from '../features/tariffs/useTariffCrud'
import { TariffEmptyState } from '../features/tariffs/TariffEmptyState'
import { TariffForm } from '../features/tariffs/TariffForm'
import { VseTariffImportModal } from '../features/tariffs/VseTariffImportModal'
import { TariffPeriodForm } from '../features/tariffs/TariffPeriodForm'
import { TariffActions } from '../features/tariffs/TariffActions'
import { TariffVersionForm } from '../features/tariffs/TariffVersionForm'
import { useTariffVersions } from '../features/tariffs/useTariffVersions'
import { useDraftGuard, allowNavigation } from '../features/tariffs/useDraftGuard'
import { listedVersion, tariffOverview } from '../features/tariffs/validity'
import { seriesKeyOf } from '../features/tariffs/useTariffDisplay'
import { tariffOverviewFilename, tariffOverviewParams, type TariffValidityFilter } from '../features/tariffs/tariffOverview'
import { fetchTariffSeries } from '../lib/api/tariffs'
import { downloadTariffOverview } from '../lib/api/invoices'
import { formatApiError } from '../lib/api/errors'
import { queryKeys } from '../lib/api/queryKeys'
import { todayBusinessIso } from '../lib/dates'
import { downloadBlob } from '../lib/downloadBlob'
import { useAppSettings } from '../lib/appSettings'
import { useAuth } from '../lib/auth'
import { useMinWidth } from '../lib/useMinWidth'
import { useManagedZev } from '../lib/managedZev'
import { useCommunityAccess, useScopeNote } from '../lib/communityAccess'
import { PageSkeleton } from '../components/PageSkeleton'
import { useTranslation } from 'react-i18next'
import { useToast } from '../lib/toast'
import type { Tariff, TariffSeries } from '../types/api'
import { PageHeader } from '../components/PageHeader'
import { Notice } from '../components/Notice'
import { ScopeGuard } from '../components/ScopeGuard'

const TARIFF_PARAM = 'tariff'
const VERSION_PARAM = 'version'

/** Content width from which the list and the pane sit side by side; below it
 * the pane takes the whole area (SPEC-2026-10-tariff-split-view §5.1). */
const SPLIT_MIN_REM = 62

/** Marks the history entry that opening a tariff from the list added, so X
 * can take it back instead of leaving a Back step behind. */
const PANE_STATE = { tariffPane: true }

type EditorKind = 'create' | 'edit' | 'period' | 'new-version' | 'duplicate' | 'rename'

export function TariffsPage() {
    const queryClient = useQueryClient()
    const { pushToast } = useToast()
    const { dialog, confirm, handleConfirm, handleCancel, isLoading: dialogLoading } = useConfirmDialog()
    const { user } = useAuth()
    const cancelConfirmation = useEffectEvent(handleCancel)
    const { settings } = useAppSettings()
    const { selectedZevId, selectedZev } = useManagedZev()
    const { t } = useTranslation()
    const scopeNote = useScopeNote()
    const { isZevScope, canWriteSelectedCommunity } = useCommunityAccess()
    const isManagedScope = isZevScope
    const readOnly = !canWriteSelectedCommunity
    const [showImportModal, setShowImportModal] = useState(false)
    const [searchParams, setSearchParams] = useSearchParams()
    const location = useLocation()
    const navigate = useNavigate()
    // Which group a tariff is in and what its row says both follow today's date.
    const today = todayBusinessIso()

    // One query, not three: the series endpoint already groups versions, names
    // the active one, detects gaps, and nests each version's price bands. The
    // flat lists below are derived from it so nothing can drift out of step
    // after a mutation.
    const seriesQuery = useQuery({
        queryKey: queryKeys.tariffs.series(selectedZevId || undefined),
        queryFn: () => fetchTariffSeries(isManagedScope ? selectedZevId || undefined : undefined),
        enabled: !!selectedZevId && selectedZev?.id === selectedZevId,
    })

    const allSeries = useMemo(
        () => (seriesQuery.data ?? []).filter(
            (series) => !isManagedScope || series.zev === selectedZevId,
        ),
        [seriesQuery.data, isManagedScope, selectedZevId],
    )

    const tariffs = useMemo<Tariff[]>(
        () => allSeries.flatMap((series) => series.versions),
        [allSeries],
    )

    // The pane's open tariff (and, within it, which version) lives in the URL
    // rather than component state: a reload, the back button, or a shared
    // link all reopen the same view instead of dropping back to the bare
    // list (#728). A renamed tariff is still found by its version, so a link
    // or a rename in flight does not close the pane.
    const tariffParam = searchParams.get(TARIFF_PARAM)
    const shownVersionId = searchParams.get(VERSION_PARAM)
    const openSeries = useMemo<TariffSeries | null>(() => {
        if (!tariffParam) return null
        return allSeries.find((series) => seriesKeyOf(series) === tariffParam)
            ?? (shownVersionId ? allSeries.find((series) => series.versions.some((version) => version.id === shownVersionId)) : undefined)
            ?? null
    }, [allSeries, tariffParam, shownVersionId])
    const openSeriesKey = openSeries ? seriesKeyOf(openSeries) : null

    // The version the pane shows: the linked one, else the one in force. The
    // list highlights that row, so it reads the same as the pane.
    const selected = useMemo(() => {
        if (!openSeries) return null
        const version = openSeries.versions.find((candidate) => candidate.id === shownVersionId)
            ?? listedVersion(openSeries.versions, today)
        return { seriesKey: seriesKeyOf(openSeries), versionId: version.id }
    }, [openSeries, shownVersionId, today])

    const [splitRef, fitsTwoPanes] = useMinWidth<HTMLDivElement>(SPLIT_MIN_REM)
    const paneTitleRef = useRef<HTMLHeadingElement>(null)
    // Where the list was scrolled to when the pane took its place.
    const listScroll = useRef<number | null>(null)
    // Opening or saving moves focus to the pane's title; closing moves it back
    // to the control or row that opened it.
    const focusPaneTitle = useRef(false)
    const returnFocusTo = useRef<string | null>(null)
    const returnFocusAction = useRef<string | null>(null)
    // Raised while the page navigates on its own account, which the unsaved-
    // input guard must not ask about.
    const bypassGuard = useRef(false)

    function withParams(change: (params: URLSearchParams) => void) {
        return (previous: URLSearchParams) => {
            const next = new URLSearchParams(previous)
            change(next)
            return next
        }
    }

    // Opening from the list adds one history step; switching tariff or
    // version while the pane is open replaces it, so Back returns to the
    // list rather than stepping through every tariff looked at.
    function select(series: Pick<TariffSeries, 'zev' | 'name'>, versionId: string) {
        const fromList = !searchParams.get(TARIFF_PARAM)
        if (fromList && !fitsTwoPanes) listScroll.current = window.scrollY
        focusPaneTitle.current = true
        allowNavigation(bypassGuard, () => setSearchParams(withParams((params) => {
            params.set(TARIFF_PARAM, seriesKeyOf(series))
            params.set(VERSION_PARAM, versionId)
        }), { replace: !fromList, state: fromList ? PANE_STATE : location.state }))
    }

    // X takes back the step opening added; a pane reached by a link has no
    // step of ours behind it, so it returns to the list in place.
    function deselect() {
        if (selected) returnFocusTo.current = `${selected.seriesKey}:${selected.versionId}`
        allowNavigation(bypassGuard, () => {
            if (location.state?.tariffPane) {
                navigate(-1)
                return
            }
            setSearchParams(withParams((params) => {
                params.delete(TARIFF_PARAM)
                params.delete(VERSION_PARAM)
            }), { replace: true })
        })
    }

    const periods = useMemo(
        () => allSeries.flatMap((series) => series.versions.flatMap((version) => version.periods)),
        [allSeries],
    )

    const tariffNameById = useMemo(() => {
        return new Map((tariffs || []).map((tariff) => [tariff.id, tariff.name]))
    }, [tariffs])

    // Energy and percentage-of-energy tariffs are the two modes that take
    // bands (§4.1); the band form's owner lookup needs the broader list.
    const bandableTariffs = useMemo(() => {
        return tariffs.filter((tariff) => tariff.billing_mode === 'energy' || tariff.billing_mode === 'percentage_of_energy')
    }, [tariffs])

    const overview = useMemo(() => tariffOverview(allSeries, today), [allSeries, today])

    const {
        tariffFormOpen,
        periodFormOpen,
        editingTariffId,
        editingPeriodId,
        periodTariffId,
        editingTariff,
        editingPeriod,
        saveError: crudSaveError,
        tariffPending,
        periodPending,
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
    } = useTariffCrud({
        selectedZevId,
        canWrite: !readOnly,
        tariffs,
        periods,
        bandableTariffs,
        tariffNameById,
        queryClient,
        pushToast,
        confirm,
        t,
        // A new tariff is a new selection; a changed version stays in view.
        onTariffSaved: (saved) => select(saved, saved.id),
        onPeriodSaved: () => { focusPaneTitle.current = true },
    })

    const versions = useTariffVersions({
        selectedZevId,
        canWrite: !readOnly,
        queryClient,
        pushToast,
        t,
        // A new version, a copy or a new name: the pane shows what was saved.
        onSaved: (saved) => select(saved, saved.id),
    })

    // What the pane is for right now: viewing, or one of the forms.
    const editor: EditorKind | null = versions.dialog?.kind
        ?? (tariffFormOpen ? (editingTariffId ? 'edit' : 'create') : periodFormOpen ? 'period' : null)
    const [formDirty, setFormDirty] = useState(false)
    const saving = editor !== null && (tariffPending || periodPending || versions.isPending)
    const guard = useDraftGuard({
        dirty: editor !== null && formDirty,
        saving,
        confirm,
        bypass: bypassGuard,
    })

    function resetEditing() {
        closeTariffForm()
        closePeriodForm()
        versions.closeDialog()
    }

    function beginEditing(actionKey: string, open: () => void) {
        returnFocusAction.current = actionKey
        open()
    }

    // Creating from the header, over whatever is shown: the selection waits behind it.
    const createTariff = () => guard.run(() => {
        resetEditing()
        beginEditing('new-tariff', openCreateTariff)
    })

    // Switching tariff or version, or leaving the pane, asks first when a form has unsaved input.
    const showVersion = (series: Pick<TariffSeries, 'zev' | 'name'>, versionId: string) => guard.run(() => {
        resetEditing()
        select(series, versionId)
    })
    const closePane = () => guard.run(() => {
        resetEditing()
        if (openSeries) deselect()
    })
    // Cancel, and Escape while a form is open: back to viewing.
    const cancelEditing = () => guard.run(resetEditing)
    const escapePane = () => (editor ? cancelEditing() : closePane())

    // A change of community, permission or account drops the selection and
    // whatever is open on top of it, drafts included. The first resolved
    // scope is not a change: a link to a tariff must survive the page finding
    // out which community it is in.
    const scopeKey = `${selectedZevId ?? ''}|${readOnly}|${user?.id ?? ''}`
    const lastScopeKey = useRef(scopeKey)
    useEffect(() => {
        setShowImportModal(false)
        cancelConfirmation()
        const previous = lastScopeKey.current
        lastScopeKey.current = scopeKey
        if (previous === scopeKey || previous.startsWith('|')) return
        allowNavigation(bypassGuard, () => setSearchParams(withParams((params) => {
            params.delete(TARIFF_PARAM)
            params.delete(VERSION_PARAM)
        }), { replace: true }))
        // eslint-disable-next-line react-hooks/exhaustive-deps -- the scope is the trigger; the rest is stable
    }, [scopeKey])

    // A selection that moves on its own (Back, a link) leaves any open form behind.
    useEffect(() => {
        resetEditing()
        // eslint-disable-next-line react-hooks/exhaustive-deps -- the selected tariff is the trigger
    }, [openSeriesKey])

    // A rename or a link by version leaves the old name in the URL; say the current one.
    useEffect(() => {
        if (openSeriesKey && tariffParam !== openSeriesKey) {
            setSearchParams(withParams((params) => params.set(TARIFF_PARAM, openSeriesKey)), { replace: true, state: location.state })
        }
        // eslint-disable-next-line react-hooks/exhaustive-deps -- only when the name and the link disagree
    }, [openSeriesKey, tariffParam])

    // A link to a tariff that is gone (deleted here or elsewhere, or another
    // community's) opens the list, not an empty pane.
    useEffect(() => {
        if (!seriesQuery.isSuccess || seriesQuery.isFetching || !tariffParam || openSeries) return
        allowNavigation(bypassGuard, () => setSearchParams(withParams((params) => {
            params.delete(TARIFF_PARAM)
            params.delete(VERSION_PARAM)
        }), { replace: true }))
        // eslint-disable-next-line react-hooks/exhaustive-deps -- when the data has settled and the link points nowhere
    }, [seriesQuery.isSuccess, seriesQuery.isFetching, tariffParam, openSeries])

    const paneOpen = openSeries !== null || editor === 'create'
    // Two panes that cannot both be useful become one: the pane, and the list
    // out of sight and out of the tab order until it is closed.
    const listHidden = paneOpen && !fitsTwoPanes

    // Where focus goes as the pane changes: to its title when it opens or a
    // save has landed; back to the control that opened a form when it is
    // cancelled; back to the row, or the list's first heading, when it closes.
    useEffect(() => {
        if (paneOpen && focusPaneTitle.current) {
            focusPaneTitle.current = false
            returnFocusAction.current = null
            paneTitleRef.current?.focus()
            return
        }
        if (!paneOpen && returnFocusTo.current) {
            const row = document.querySelector<HTMLElement>(`[data-row-key="${CSS.escape(returnFocusTo.current)}"] .tariff-select`)
            returnFocusTo.current = null
            ;(row ?? document.getElementById('tariff-overview-current'))?.focus()
            return
        }
        if (editor === null && returnFocusAction.current) {
            const control = document.querySelector<HTMLElement>(`[data-action-key="${CSS.escape(returnFocusAction.current)}"]`)
            returnFocusAction.current = null
            ;(control ?? paneTitleRef.current)?.focus()
        }
    }, [paneOpen, openSeries, editor])

    // The list comes back where the user left it.
    useLayoutEffect(() => {
        if (!listHidden && listScroll.current !== null) {
            window.scrollTo(0, listScroll.current)
            listScroll.current = null
        }
    }, [listHidden])

    // The scope is chosen at the download, not by the list: the overview
    // groups series by validity, and "all" is what also adds every
    // superseded version to the PDF.
    const overviewMutation = useMutation({
        mutationFn: (scope: TariffValidityFilter) => downloadTariffOverview(tariffOverviewParams(selectedZevId ?? '', scope)),
        onSuccess: (blob) => downloadBlob(blob, tariffOverviewFilename(today)),
        onError: (error) => pushToast(formatApiError(error, t('pages.tariffs.overviewPdf.error')), 'error'),
    })

    const header = (
        <PageHeader
            eyebrow={selectedZev?.name}
            communitySwitch
            scopeNote={scopeNote}
            title={t('pages.tariffs.title')}
            description={t('pages.tariffs.description')}
            actions={selectedZevId && seriesQuery.isSuccess ? (
                <TariffActions
                    onOpenCreateTariff={createTariff}
                    onOpenImportModal={!readOnly ? () => setShowImportModal(true) : undefined}
                    readOnly={readOnly}
                    onDownloadOverview={(scope) => overviewMutation.mutate(scope)}
                    overviewBusy={overviewMutation.isPending}
                />
            ) : undefined}
        />
    )

    // The form for the task in hand, and what to call it under the tariff's name.
    function renderEditor(): { label: string, content: ReactNode } | null {
        const task = versions.dialog
        if (task) {
            return {
                label: t(`pages.tariffs.pane.task.${task.kind}` as Parameters<typeof t>[0]),
                content: (
                    <TariffVersionForm
                        key={`${task.kind}:${task.source.id}`}
                        dialog={task}
                        settings={settings}
                        isPending={versions.isPending}
                        error={versions.saveError}
                        onCancel={cancelEditing}
                        onDirtyChange={setFormDirty}
                        onSubmitNewVersion={versions.submitNewVersion}
                        onSubmitDuplicate={versions.submitDuplicate}
                        onSubmitRename={versions.submitRename}
                    />
                ),
            }
        }
        if (tariffFormOpen) {
            return {
                label: editingTariffId ? t('pages.tariffs.pane.task.edit') : '',
                content: (
                    <TariffForm
                        key={editingTariffId ?? 'new'}
                        initialTariff={editingTariff}
                        selectedZevId={selectedZevId || ''}
                        isPending={tariffPending}
                        error={crudSaveError}
                        onDelete={editingTariff ? () => confirmDeleteTariff(editingTariff) : undefined}
                        onSubmit={submitTariff}
                        onCancel={cancelEditing}
                        onDirtyChange={setFormDirty}
                    />
                ),
            }
        }
        if (periodFormOpen) {
            return {
                label: t(editingPeriodId ? 'pages.tariffs.editPeriodTitle' : 'pages.tariffs.createPeriodTitle'),
                content: (
                    <TariffPeriodForm
                        key={editingPeriodId ?? 'new'}
                        initialPeriod={editingPeriod}
                        defaultTariffId={periodTariffId}
                        tariffs={bandableTariffs}
                        periods={periods}
                        isPending={periodPending}
                        error={crudSaveError}
                        onDelete={editingPeriod ? () => confirmDeletePeriod(editingPeriod) : undefined}
                        onSubmit={submitPeriod}
                        onCancel={cancelEditing}
                        onDirtyChange={setFormDirty}
                    />
                ),
            }
        }
        return null
    }
    const editorPane = renderEditor()

    return (
        <div className="page-stack">
            {header}
            <ScopeGuard skeleton="table">
            {seriesQuery.isLoading ? <PageSkeleton variant="table" /> : seriesQuery.isError ? (
                <Notice tone="error" onRetry={() => void seriesQuery.refetch()} isRetrying={seriesQuery.isFetching}>{t('common.error')}</Notice>
            ) : <>
            {selectedZev?.vat_mode === 'inclusive' && (
                <div className="info-banner">{t('pages.tariffs.vatInclusiveNotice')}</div>
            )}

            {selectedZevId && (
                <VseTariffImportModal
                    isOpen={showImportModal}
                    onClose={() => setShowImportModal(false)}
                    zevId={selectedZevId}
                    initialUrl={selectedZev?.tariff_source_url ?? ''}
                />
            )}

            <div
                ref={splitRef}
                className="tariff-split"
                data-layout={fitsTwoPanes ? 'wide' : 'narrow'}
                data-pane={paneOpen ? 'open' : 'closed'}
            >
                <div className="tariff-split-list" hidden={listHidden}>
                    {tariffs.length === 0 ? (
                        <TariffEmptyState onOpenCreateTariff={createTariff} readOnly={readOnly} />
                    ) : (
                        <TariffOverview
                            groups={overview}
                            settings={settings}
                            selected={selected}
                            onOpenDetail={showVersion}
                        />
                    )}
                </div>

                {editor === 'create' && editorPane ? (
                    <TariffPaneFrame
                        title={t('pages.tariffs.createTitle')}
                        onClose={escapePane}
                        titleRef={paneTitleRef}
                    >
                        <div className="tariff-pane-body page-stack">{editorPane.content}</div>
                    </TariffPaneFrame>
                ) : openSeries && (
                    <TariffDetailPane
                        series={openSeries}
                        allSeries={allSeries}
                        settings={settings}
                        shownVersionId={shownVersionId}
                        onShowVersion={(versionId) => showVersion(openSeries, versionId)}
                        onClose={escapePane}
                        onEditTariff={(version, actionKey) => beginEditing(actionKey, () => startTariffEdit(version))}
                        onOpenCreatePeriod={(versionId) => beginEditing('add-period', () => openCreatePeriod(versionId))}
                        onEditPeriod={(period, actionKey) => beginEditing(actionKey, () => startPeriodEdit(period))}
                        onNewVersion={(series, source) => beginEditing('new-version', () => versions.openNewVersion(series, source))}
                        onDuplicate={(series, source) => beginEditing('duplicate', () => versions.openDuplicate(series, source))}
                        onRenameSeries={(series, source) => beginEditing('rename', () => versions.openRename(series, source))}
                        readOnly={readOnly}
                        titleRef={paneTitleRef}
                        editor={editorPane ?? undefined}
                    />
                )}
            </div>

            {dialog && (
                <ConfirmDialog {...dialog} isLoading={dialogLoading} onConfirm={handleConfirm} onCancel={handleCancel} />
            )}
            </>}
            </ScopeGuard>
        </div>
    )
}
