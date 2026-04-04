import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useMemo, useState, type ChangeEvent, type FormEvent } from 'react'
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome'
import {
    faCheck,
    faDownload,
    faPen,
    faPlus,
    faTrash,
    faUpload,
    faXmark,
} from '@fortawesome/free-solid-svg-icons'
import dayjs from 'dayjs'
import { DatePicker } from '@mui/x-date-pickers/DatePicker'
import { AdapterDayjs } from '@mui/x-date-pickers/AdapterDayjs'
import { LocalizationProvider } from '@mui/x-date-pickers/LocalizationProvider'
import { ConfirmDialog, useConfirmDialog } from '../components/ConfirmDialog'
import { FormModal } from '../components/FormModal'
import {
    createTariff,
    createTariffPeriod,
    deleteTariff,
    deleteTariffPeriod,
    exportTariffs,
    fetchTariffPeriods,
    fetchTariffs,
    formatApiError,
    importTariffs,
    updateTariff,
    updateTariffPeriod,
} from '../lib/api'
import { formatShortDate, toDayJsDateFormat, useAppSettings } from '../lib/appSettings'
import { useAuth } from '../lib/auth'
import { useManagedZev } from '../lib/managedZev'
import { useTranslation } from 'react-i18next'
import { useToast } from '../lib/toast'
import type { Tariff, TariffInput, TariffPeriod, TariffPeriodInput, TariffPreset } from '../types/api'

const defaultTariffForm: TariffInput = {
    zev: '',
    name: '',
    category: 'energy',
    billing_mode: 'energy',
    energy_type: 'local',
    fixed_price_chf: null,
    percentage: null,
    valid_from: new Date().toISOString().slice(0, 10),
    valid_to: null,
    notes: '',
}

const defaultPeriodForm: TariffPeriodInput = {
    tariff: '',
    period_type: 'flat',
    price_chf_per_kwh: '',
    time_from: null,
    time_to: null,
    weekdays: '',
}

const tariffCategoryOrder: Tariff['category'][] = ['energy', 'grid_fees', 'levies', 'metering']

export function TariffsPage() {
    const queryClient = useQueryClient()
    const { pushToast } = useToast()
    const { dialog, confirm, handleConfirm, handleCancel, isLoading: dialogLoading } = useConfirmDialog()
    const { user } = useAuth()
    const { settings } = useAppSettings()
    const { selectedZevId } = useManagedZev()
    const { t } = useTranslation()
    const isManagedScope = user?.role === 'admin' || user?.role === 'zev_owner'

    const tariffsQuery = useQuery({ queryKey: ['tariffs'], queryFn: fetchTariffs })
    const periodsQuery = useQuery({ queryKey: ['tariff-periods'], queryFn: fetchTariffPeriods })

    const [tariffForm, setTariffForm] = useState<TariffInput>(defaultTariffForm)
    const [periodForm, setPeriodForm] = useState<TariffPeriodInput>(defaultPeriodForm)
    const [editingTariffId, setEditingTariffId] = useState<string | null>(null)
    const [editingPeriodId, setEditingPeriodId] = useState<string | null>(null)
    const [showTariffModal, setShowTariffModal] = useState(false)
    const [showPeriodModal, setShowPeriodModal] = useState(false)
    const [showExportModal, setShowExportModal] = useState(false)
    const [showImportModal, setShowImportModal] = useState(false)

    const tariffs = useMemo(
        () => (tariffsQuery.data?.results || []).filter((tariff) => !isManagedScope || !selectedZevId || tariff.zev === selectedZevId),
        [tariffsQuery.data?.results, isManagedScope, selectedZevId],
    )

    const allowedTariffIds = useMemo(() => new Set(tariffs.map((tariff) => tariff.id)), [tariffs])

    const periods = useMemo(
        () => (periodsQuery.data?.results || []).filter((period) => allowedTariffIds.has(period.tariff)),
        [periodsQuery.data?.results, allowedTariffIds],
    )

    const periodsByTariff = useMemo(() => {
        const grouped = new Map<string, TariffPeriod[]>()

        periods.forEach((period) => {
            const existing = grouped.get(period.tariff) ?? []
            existing.push(period)
            grouped.set(period.tariff, existing)
        })

        grouped.forEach((tariffPeriods) => {
            tariffPeriods.sort((left, right) => {
                const periodTypeOrder = { flat: 0, high: 1, low: 2 }
                const typeDelta = periodTypeOrder[left.period_type] - periodTypeOrder[right.period_type]
                if (typeDelta !== 0) return typeDelta

                const fromDelta = (left.time_from ?? '').localeCompare(right.time_from ?? '')
                if (fromDelta !== 0) return fromDelta

                return (left.time_to ?? '').localeCompare(right.time_to ?? '')
            })
        })

        return grouped
    }, [periods])

    const tariffNameById = useMemo(() => {
        return new Map((tariffs || []).map((tariff) => [tariff.id, tariff.name]))
    }, [tariffs])

    const energyTariffs = useMemo(() => {
        return tariffs.filter((tariff) => tariff.billing_mode === 'energy')
    }, [tariffs])

    const tariffsWithPeriodsCount = useMemo(
        () => tariffs.filter((tariff) => (periodsByTariff.get(tariff.id)?.length ?? 0) > 0).length,
        [tariffs, periodsByTariff],
    )

    const tariffSections = useMemo(
        () =>
            tariffCategoryOrder
                .map((category) => ({
                    category,
                    tariffs: tariffs.filter((tariff) => tariff.category === category),
                }))
                .filter((section) => section.tariffs.length > 0),
        [tariffs],
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
            setTariffForm(defaultTariffForm)
            setShowTariffModal(false)
            pushToast(variables.id ? 'Tariff updated.' : 'Tariff created.', 'success')
            void queryClient.invalidateQueries({ queryKey: ['tariffs'] })
        },
        onError: (error) => pushToast(formatApiError(error, 'Failed to save tariff.'), 'error'),
    })

    const deleteTariffMutation = useMutation({
        mutationFn: deleteTariff,
        onSuccess: () => {
            pushToast('Tariff deleted.', 'success')
            void queryClient.invalidateQueries({ queryKey: ['tariffs'] })
            void queryClient.invalidateQueries({ queryKey: ['tariff-periods'] })
        },
        onError: (error) => pushToast(formatApiError(error, 'Failed to delete tariff.'), 'error'),
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
            setPeriodForm(defaultPeriodForm)
            setShowPeriodModal(false)
            pushToast(variables.id ? 'Tariff period updated.' : 'Tariff period created.', 'success')
            void queryClient.invalidateQueries({ queryKey: ['tariff-periods'] })
        },
        onError: (error) => pushToast(formatApiError(error, 'Failed to save tariff period.'), 'error'),
    })

    const deletePeriodMutation = useMutation({
        mutationFn: deleteTariffPeriod,
        onSuccess: () => {
            pushToast('Tariff period deleted.', 'success')
            void queryClient.invalidateQueries({ queryKey: ['tariff-periods'] })
        },
        onError: (error) => pushToast(formatApiError(error, 'Failed to delete tariff period.'), 'error'),
    })

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
            pushToast('Tariffs exported successfully.', 'success')
        },
        onError: (error) => pushToast(formatApiError(error, 'Failed to export tariffs.'), 'error'),
    })

    const importMutation = useMutation({
        mutationFn: ({ zevId, tariffs }: { zevId: string; tariffs: TariffPreset[] }) => importTariffs(zevId, tariffs),
        onSuccess: (result) => {
            setShowImportModal(false)
            void queryClient.invalidateQueries({ queryKey: ['tariffs'] })
            void queryClient.invalidateQueries({ queryKey: ['tariff-periods'] })
            pushToast(`Imported ${result.created} tariff(s) successfully.`, 'success')
        },
        onError: (error) => pushToast(formatApiError(error, 'Failed to import tariffs.'), 'error'),
    })

    function submitTariff(event: FormEvent<HTMLFormElement>) {
        event.preventDefault()
        const zevForSubmit = isManagedScope ? selectedZevId : tariffForm.zev
        if (!zevForSubmit) {
            pushToast('Select a ZEV before saving the tariff.', 'error')
            return
        }
        if (tariffForm.billing_mode === 'energy' && !tariffForm.energy_type) {
            pushToast('Select an energy type for energy-based tariffs.', 'error')
            return
        }
        if (tariffForm.billing_mode === 'percentage_of_energy' && !tariffForm.energy_type) {
            pushToast('Select an energy type for percentage tariffs.', 'error')
            return
        }
        if (tariffForm.billing_mode === 'percentage_of_energy' && !tariffForm.percentage) {
            pushToast('Enter a percentage value.', 'error')
            return
        }
        if (!['energy', 'percentage_of_energy'].includes(tariffForm.billing_mode) && !tariffForm.fixed_price_chf) {
            pushToast('Enter a fixed fee amount.', 'error')
            return
        }
        tariffMutation.mutate({ id: editingTariffId || undefined, payload: { ...tariffForm, zev: zevForSubmit } })
    }

    function submitPeriod(event: FormEvent<HTMLFormElement>) {
        event.preventDefault()
        if (!periodForm.tariff) {
            pushToast('Select a tariff before saving the period.', 'error')
            return
        }
        periodMutation.mutate({ id: editingPeriodId || undefined, payload: periodForm })
    }

    function startTariffEdit(tariff: Tariff) {
        setEditingTariffId(tariff.id)
        setTariffForm({
            zev: tariff.zev,
            name: tariff.name,
            category: tariff.category,
            billing_mode: tariff.billing_mode,
            energy_type: tariff.energy_type || null,
            fixed_price_chf: tariff.fixed_price_chf || null,
            percentage: tariff.percentage || null,
            valid_from: tariff.valid_from,
            valid_to: tariff.valid_to || null,
            notes: tariff.notes || '',
        })
        setShowTariffModal(true)
    }

    function startPeriodEdit(period: TariffPeriod) {
        setEditingPeriodId(period.id)
        setPeriodForm({
            tariff: period.tariff,
            period_type: period.period_type,
            price_chf_per_kwh: period.price_chf_per_kwh,
            time_from: period.time_from || null,
            time_to: period.time_to || null,
            weekdays: period.weekdays || '',
        })
        setShowPeriodModal(true)
    }

    function openCreateTariffModal() {
        setEditingTariffId(null)
        setTariffForm({ ...defaultTariffForm, zev: isManagedScope ? selectedZevId : '' })
        setShowTariffModal(true)
    }

    function closeTariffModal() {
        setShowTariffModal(false)
        setEditingTariffId(null)
        setTariffForm(defaultTariffForm)
    }

    function openCreatePeriodModal(tariffId?: string) {
        const defaultTariffId = tariffId ?? energyTariffs[0]?.id

        if (!defaultTariffId) {
            pushToast('Create an energy-based tariff before adding tariff periods.', 'error')
            return
        }
        setEditingPeriodId(null)
        setPeriodForm({ ...defaultPeriodForm, tariff: defaultTariffId })
        setShowPeriodModal(true)
    }

    function closePeriodModal() {
        setShowPeriodModal(false)
        setEditingPeriodId(null)
        setPeriodForm(defaultPeriodForm)
    }

    function openExportModal() {
        setShowExportModal(true)
    }

    function closeExportModal() {
        setShowExportModal(false)
    }

    function handleExport() {
        if (!selectedZevId) {
            pushToast('Please select a ZEV to export.', 'error')
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
                const tariffs = JSON.parse(content) as TariffPreset[]
                if (!Array.isArray(tariffs)) {
                    pushToast('Invalid file format. Expected an array of tariffs.', 'error')
                    return
                }
                if (!selectedZevId) {
                    pushToast('Please select a ZEV to import into.', 'error')
                    return
                }
                importMutation.mutate({ zevId: selectedZevId, tariffs })
            } catch (error) {
                pushToast(`Failed to parse JSON file: ${error instanceof Error ? error.message : 'Unknown error'}`, 'error')
            }
        }
        reader.readAsText(file)
    }
    if (tariffsQuery.isLoading || periodsQuery.isLoading) {
        return <div className="card">{t('common.loading')}</div>
    }

    if (tariffsQuery.isError || periodsQuery.isError) {
        return <div className="card error-banner">{t('common.error')}</div>
    }

    return (
        <div className="page-stack">
            <header>
                <h2>{t('pages.tariffs.title')}</h2>
                <p className="muted">{t('pages.tariffs.description')}</p>
            </header>

            <section className="card tariff-toolbar">
                <div className="tariff-toolbar-header">
                    <div className="tariff-summary" aria-label={t('pages.tariffs.summaryLabel')}>
                        <span className="tariff-summary-stat">
                            <span className="tariff-summary-label">{t('pages.tariffs.summary.total')}</span>
                            <span className="tariff-summary-value">{tariffs.length}</span>
                        </span>
                        <span className="tariff-summary-stat">
                            <span className="tariff-summary-label">{t('pages.tariffs.summary.energyBased')}</span>
                            <span className="tariff-summary-value">{energyTariffs.length}</span>
                        </span>
                        <span className="tariff-summary-stat">
                            <span className="tariff-summary-label">{t('pages.tariffs.summary.withPeriods')}</span>
                            <span className="tariff-summary-value">{tariffsWithPeriodsCount}</span>
                        </span>
                        <span className="tariff-summary-stat">
                            <span className="tariff-summary-label">{t('pages.tariffs.summary.totalPeriods')}</span>
                            <span className="tariff-summary-value">{periods.length}</span>
                        </span>
                    </div>

                    <div className="actions-row actions-row-wrap">
                        <button className="button button-primary" onClick={openCreateTariffModal}>
                            <FontAwesomeIcon icon={faPlus} fixedWidth />
                            {t('pages.tariffs.newTariff')}
                        </button>
                        <button className="button button-secondary" onClick={openExportModal}>
                            <FontAwesomeIcon icon={faDownload} fixedWidth />
                            {t('pages.tariffs.exportJson')}
                        </button>
                        <button className="button button-secondary" onClick={openImportModal}>
                            <FontAwesomeIcon icon={faUpload} fixedWidth />
                            {t('pages.tariffs.importJson')}
                        </button>
                    </div>
                </div>
            </section>

            <FormModal
                isOpen={showExportModal}
                title={t('pages.tariffs.exportModalTitle')}
                onClose={closeExportModal}
                maxWidth="520px"
            >
                <div style={{ display: 'grid', gap: '1rem' }}>
                    <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '1rem' }}>
                        <button className="button button-secondary" type="button" onClick={closeExportModal}>
                            <FontAwesomeIcon icon={faXmark} fixedWidth />
                            {t('pages.tariffs.cancel')}
                        </button>
                        <button className="button button-primary" type="button" onClick={handleExport} disabled={exportMutation.isPending}>
                            <FontAwesomeIcon icon={faDownload} fixedWidth />
                            {t('pages.tariffs.export')}
                        </button>
                    </div>
                </div>
            </FormModal>

            <FormModal
                isOpen={showImportModal}
                title={t('pages.tariffs.importModalTitle')}
                onClose={closeImportModal}
                maxWidth="520px"
            >
                <div style={{ display: 'grid', gap: '1rem' }}>
                    <label>
                        <span>{t('pages.tariffs.form.jsonFile')}</span>
                        <input type="file" accept="application/json,.json" onChange={handleImportFile} />
                    </label>
                    <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
                        <button className="button button-secondary" type="button" onClick={closeImportModal}>
                            <FontAwesomeIcon icon={faXmark} fixedWidth />
                            {t('pages.tariffs.close')}
                        </button>
                    </div>
                </div>
            </FormModal>

            <FormModal
                isOpen={showTariffModal}
                title={editingTariffId ? t('pages.tariffs.editTitle') : t('pages.tariffs.createTitle')}
                onClose={closeTariffModal}
            >
                <form onSubmit={submitTariff} className="form-grid">
                    <label>
                        <span>{t('pages.tariffs.form.name')}</span>
                        <input
                            value={tariffForm.name}
                            onChange={(event) => setTariffForm((prev) => ({ ...prev, name: event.target.value }))}
                            required
                        />
                    </label>
                    <label>
                        <span>{t('pages.tariffs.form.category')}</span>
                        <select
                            value={tariffForm.category}
                            onChange={(event) => setTariffForm((prev) => ({ ...prev, category: event.target.value as TariffInput['category'] }))}
                        >
                            <option value="energy">{t('pages.tariffs.categories.energy')}</option>
                            <option value="grid_fees">{t('pages.tariffs.categories.grid_fees')}</option>
                            <option value="levies">{t('pages.tariffs.categories.levies')}</option>
                            <option value="metering">{t('pages.tariffs.categories.metering')}</option>
                        </select>
                    </label>
                    <label>
                        <span>{t('pages.tariffs.form.billingMode')}</span>
                        <select
                            value={tariffForm.billing_mode}
                            onChange={(event) => {
                                const billingMode = event.target.value as TariffInput['billing_mode']
                                const isEnergyMode = billingMode === 'energy' || billingMode === 'percentage_of_energy'
                                setTariffForm((prev) => ({
                                    ...prev,
                                    billing_mode: billingMode,
                                    energy_type: isEnergyMode ? (prev.energy_type || 'local') : null,
                                    fixed_price_chf: isEnergyMode ? null : (prev.fixed_price_chf || ''),
                                    percentage: billingMode === 'percentage_of_energy' ? (prev.percentage || '') : null,
                                }))
                            }}
                        >
                            <option value="energy">{t('pages.tariffs.billingModes.energy')}</option>
                            <option value="percentage_of_energy">{t('pages.tariffs.billingModes.percentage_of_energy')}</option>
                            <option value="monthly_fee">{t('pages.tariffs.billingModes.monthly_fee')}</option>
                            <option value="yearly_fee">{t('pages.tariffs.billingModes.yearly_fee')}</option>
                            <option value="per_metering_point_monthly_fee">{t('pages.tariffs.billingModes.per_metering_point_monthly_fee')}</option>
                            <option value="per_metering_point_yearly_fee">{t('pages.tariffs.billingModes.per_metering_point_yearly_fee')}</option>
                        </select>
                    </label>
                    {(tariffForm.billing_mode === 'energy' || tariffForm.billing_mode === 'percentage_of_energy') ? (
                        <label>
                            <span>{t('pages.tariffs.form.energyType')}</span>
                            <select
                                value={tariffForm.energy_type ?? 'local'}
                                onChange={(event) => setTariffForm((prev) => ({ ...prev, energy_type: event.target.value as TariffInput['energy_type'] }))}
                            >
                                <option value="local">{t('pages.tariffs.energyTypes.local')}</option>
                                <option value="grid">{t('pages.tariffs.energyTypes.grid')}</option>
                                <option value="feed_in">{t('pages.tariffs.energyTypes.feed_in')}</option>
                            </select>
                        </label>
                    ) : null}
                    {tariffForm.billing_mode === 'percentage_of_energy' ? (
                        <label>
                            <span>{t('pages.tariffs.form.percentage')}</span>
                            <input
                                type="number"
                                step="0.01"
                                min="0"
                                max="100"
                                value={tariffForm.percentage ?? ''}
                                onChange={(event) => setTariffForm((prev) => ({ ...prev, percentage: event.target.value || null }))}
                                required
                            />
                        </label>
                    ) : tariffForm.billing_mode !== 'energy' ? (
                        <label>
                            <span>
                                {tariffForm.billing_mode === 'monthly_fee'
                                    ? t('pages.tariffs.form.monthlyFee')
                                    : tariffForm.billing_mode === 'yearly_fee'
                                        ? t('pages.tariffs.form.yearlyFee')
                                        : tariffForm.billing_mode === 'per_metering_point_monthly_fee'
                                            ? t('pages.tariffs.form.mpMonthlyFee')
                                            : t('pages.tariffs.form.mpYearlyFee')}
                            </span>
                            <input
                                type="number"
                                step="0.01"
                                value={tariffForm.fixed_price_chf ?? ''}
                                onChange={(event) => setTariffForm((prev) => ({ ...prev, fixed_price_chf: event.target.value || null }))}
                                required
                            />
                        </label>
                    ) : null}
                    <label>
                        <span>{t('pages.tariffs.form.validFrom')}</span>
                        <LocalizationProvider dateAdapter={AdapterDayjs}>
                            <DatePicker
                                format={toDayJsDateFormat(settings.date_format_short)}
                                value={tariffForm.valid_from ? dayjs(tariffForm.valid_from) : null}
                                onChange={(val) => setTariffForm((prev) => ({ ...prev, valid_from: val ? val.format('YYYY-MM-DD') : '' }))}
                                slotProps={{ textField: { size: 'small', fullWidth: true } }}
                            />
                        </LocalizationProvider>
                    </label>
                    <label>
                        <span>{t('pages.tariffs.form.validTo')}</span>
                        <LocalizationProvider dateAdapter={AdapterDayjs}>
                            <DatePicker
                                format={toDayJsDateFormat(settings.date_format_short)}
                                value={tariffForm.valid_to ? dayjs(tariffForm.valid_to) : null}
                                onChange={(val) => setTariffForm((prev) => ({ ...prev, valid_to: val ? val.format('YYYY-MM-DD') : null }))}
                                slotProps={{ textField: { size: 'small', fullWidth: true } }}
                            />
                        </LocalizationProvider>
                    </label>
                    <label>
                        <span>{t('pages.tariffs.form.notes')}</span>
                        <input
                            value={tariffForm.notes ?? ''}
                            onChange={(event) => setTariffForm((prev) => ({ ...prev, notes: event.target.value }))}
                        />
                    </label>
                    <div style={{ gridColumn: '1 / -1', display: 'flex', gap: '1rem', justifyContent: 'flex-end', marginTop: '1rem' }}>
                        <button className="button button-secondary" type="button" onClick={closeTariffModal}>
                            <FontAwesomeIcon icon={faXmark} fixedWidth />
                            {t('common.cancel')}
                        </button>
                        <button className="button button-primary" type="submit" disabled={tariffMutation.isPending}>
                            <FontAwesomeIcon icon={faCheck} fixedWidth />
                            {editingTariffId ? t('pages.tariffs.saveTariff') : t('pages.tariffs.createTariff')}
                        </button>
                    </div>
                </form>
            </FormModal>

            <FormModal
                isOpen={showPeriodModal}
                title={editingPeriodId ? t('pages.tariffs.editPeriodTitle') : t('pages.tariffs.createPeriodTitle')}
                onClose={closePeriodModal}
            >
                <form onSubmit={submitPeriod} className="form-grid">
                    <label>
                        <span>{t('pages.tariffs.form.tariff')}</span>
                        <select
                            value={periodForm.tariff}
                            onChange={(event) => setPeriodForm((prev) => ({ ...prev, tariff: event.target.value }))}
                            required
                        >
                            <option value="">{t('pages.tariffs.form.selectTariff')}</option>
                            {energyTariffs.map((tariff) => (
                                <option key={tariff.id} value={tariff.id}>{tariff.name}</option>
                            ))}
                        </select>
                    </label>
                    <label>
                        <span>{t('pages.tariffs.form.periodType')}</span>
                        <select
                            value={periodForm.period_type}
                            onChange={(event) => setPeriodForm((prev) => ({ ...prev, period_type: event.target.value as TariffPeriodInput['period_type'] }))}
                        >
                            <option value="flat">{t('pages.tariffs.periodTypes.flat')}</option>
                            <option value="high">{t('pages.tariffs.periodTypes.high')}</option>
                            <option value="low">{t('pages.tariffs.periodTypes.low')}</option>
                        </select>
                    </label>
                    <label>
                        <span>{t('pages.tariffs.form.pricePerKwh')}</span>
                        <input
                            type="number"
                            step="0.00001"
                            value={periodForm.price_chf_per_kwh}
                            onChange={(event) => setPeriodForm((prev) => ({ ...prev, price_chf_per_kwh: event.target.value }))}
                            required
                        />
                    </label>
                    <label>
                        <span>{t('pages.tariffs.form.timeFrom')}</span>
                        <input
                            type="time"
                            value={periodForm.time_from ?? ''}
                            onChange={(event) => setPeriodForm((prev) => ({ ...prev, time_from: event.target.value || null }))}
                        />
                    </label>
                    <label>
                        <span>{t('pages.tariffs.form.timeTo')}</span>
                        <input
                            type="time"
                            value={periodForm.time_to ?? ''}
                            onChange={(event) => setPeriodForm((prev) => ({ ...prev, time_to: event.target.value || null }))}
                        />
                    </label>
                    <label>
                        <span>{t('pages.tariffs.form.weekdays')}</span>
                        <input
                            value={periodForm.weekdays ?? ''}
                            onChange={(event) => setPeriodForm((prev) => ({ ...prev, weekdays: event.target.value }))}
                            placeholder="0,1,2,3,4"
                        />
                    </label>
                    <div style={{ gridColumn: '1 / -1', display: 'flex', gap: '1rem', justifyContent: 'flex-end', marginTop: '1rem' }}>
                        <button className="button button-secondary" type="button" onClick={closePeriodModal}>
                            <FontAwesomeIcon icon={faXmark} fixedWidth />
                            {t('common.cancel')}
                        </button>
                        <button className="button button-primary" type="submit" disabled={periodMutation.isPending}>
                            <FontAwesomeIcon icon={faCheck} fixedWidth />
                            {editingPeriodId ? t('pages.tariffs.savePeriod') : t('pages.tariffs.createPeriod')}
                        </button>
                    </div>
                </form>
            </FormModal>

            {tariffs.length === 0 ? (
                <section className="card tariff-empty-state">
                    <h3>{t('pages.tariffs.noTariffs')}</h3>
                    <p className="muted">{t('pages.tariffs.description')}</p>
                    <div className="actions-row actions-row-wrap">
                        <button className="button button-primary" type="button" onClick={openCreateTariffModal}>
                            <FontAwesomeIcon icon={faPlus} fixedWidth />
                            {t('pages.tariffs.newTariff')}
                        </button>
                        <button className="button button-secondary" type="button" onClick={openImportModal}>
                            <FontAwesomeIcon icon={faUpload} fixedWidth />
                            {t('pages.tariffs.importJson')}
                        </button>
                    </div>
                </section>
            ) : (
                <div className="tariff-category-sections">
                    {tariffSections.map((section) => (
                        <section
                            key={section.category}
                            className={`tariff-category-section tariff-category-section-${section.category.replace(/_/g, '-')}`}
                        >
                            <div className="tariff-category-header">
                                <div className="tariff-category-title-row">
                                    <h3>{t(`pages.tariffs.categories.${section.category}` as Parameters<typeof t>[0])}</h3>
                                    <span className="badge badge-neutral">{section.tariffs.length}</span>
                                </div>
                            </div>

                            <div className="tariff-card-list">
                                {section.tariffs.map((tariff) => {
                                    const tariffPeriods = periodsByTariff.get(tariff.id) ?? []
                                    const usesPeriods = tariff.billing_mode === 'energy'
                                    const pricingLabel = tariff.billing_mode === 'energy'
                                        ? t(`pages.tariffs.energyTypes.${tariff.energy_type || 'local'}` as Parameters<typeof t>[0])
                                        : tariff.billing_mode === 'percentage_of_energy'
                                            ? `${tariff.percentage ?? '0'}% · ${t(`pages.tariffs.energyTypes.${tariff.energy_type || 'local'}` as Parameters<typeof t>[0])}`
                                            : `CHF ${tariff.fixed_price_chf || '0.00'}`

                                    return (
                                        <article key={tariff.id} className="tariff-card">
                                            <div className="tariff-card-header">
                                                <div className="tariff-card-title">
                                                    <div className="tariff-card-heading">
                                                        <strong>{tariff.name}</strong>
                                                        <div className="tariff-name-badges">
                                                            <span className="badge badge-info">
                                                                {t(`pages.tariffs.billingModes.${tariff.billing_mode}` as Parameters<typeof t>[0], { defaultValue: tariff.billing_mode })}
                                                            </span>
                                                            {tariff.energy_type && (
                                                                <span className="badge badge-success">
                                                                    {t(`pages.tariffs.energyTypes.${tariff.energy_type}` as Parameters<typeof t>[0])}
                                                                </span>
                                                            )}
                                                        </div>
                                                    </div>
                                                </div>

                                                <div className="tariff-card-actions">
                                                    <button className="button button-primary button-compact" type="button" onClick={() => startTariffEdit(tariff)}>
                                                        <FontAwesomeIcon icon={faPen} fixedWidth />
                                                        {t('common.edit')}
                                                    </button>
                                                    <button
                                                        className="button button-danger button-compact"
                                                        type="button"
                                                        disabled={deleteTariffMutation.isPending || dialogLoading}
                                                        onClick={() => confirm({
                                                            title: t('pages.tariffs.deleteTitle'),
                                                            message: t('pages.tariffs.deleteMessage', { name: tariff.name }),
                                                            confirmText: t('pages.tariffs.deleteConfirm'),
                                                            isDangerous: true,
                                                            onConfirm: () => deleteTariffMutation.mutate(tariff.id),
                                                        })}
                                                    >
                                                        <FontAwesomeIcon icon={faTrash} fixedWidth />
                                                        {t('common.delete')}
                                                    </button>
                                                </div>
                                            </div>

                                            <div className="tariff-card-details">
                                                <div className="tariff-detail-card">
                                                    <span className="tariff-detail-label">{t('pages.tariffs.col.pricing')}</span>
                                                    <span className="tariff-detail-value">{pricingLabel}</span>
                                                </div>
                                                <div className="tariff-detail-card">
                                                    <span className="tariff-detail-label">{t('pages.tariffs.col.validity')}</span>
                                                    <span className="tariff-detail-value">
                                                        {formatShortDate(tariff.valid_from, settings)} - {tariff.valid_to ? formatShortDate(tariff.valid_to, settings) : '-'}
                                                    </span>
                                                </div>
                                                <div className="tariff-detail-card tariff-detail-card-wide">
                                                    <span className="tariff-detail-label">{t('pages.tariffs.form.notes')}</span>
                                                    <span className="tariff-detail-value">{tariff.notes?.trim() || t('pages.tariffs.noNotes')}</span>
                                                </div>
                                            </div>

                                            <div className="tariff-period-section">
                                                <div className="tariff-period-section-header">
                                                    <div className="tariff-period-section-title-row">
                                                        <h4>{t('pages.tariffs.tariffPeriods')}</h4>
                                                        {usesPeriods && tariffPeriods.length > 0 && (
                                                            <span className="badge badge-neutral">{tariffPeriods.length}</span>
                                                        )}
                                                    </div>
                                                    {usesPeriods && (
                                                        <button
                                                            className="button button-secondary button-compact"
                                                            type="button"
                                                            onClick={() => openCreatePeriodModal(tariff.id)}
                                                        >
                                                            <FontAwesomeIcon icon={faPlus} fixedWidth />
                                                            {t('pages.tariffs.addPeriod')}
                                                        </button>
                                                    )}
                                                </div>

                                                {!usesPeriods ? (
                                                    <p className="muted tariff-period-empty">{t('pages.tariffs.fixedFeeHint')}</p>
                                                ) : tariffPeriods.length === 0 ? (
                                                    <p className="muted tariff-period-empty">{t('pages.tariffs.noPeriods')}</p>
                                                ) : (
                                                    <div className="tariff-period-list">
                                                        {tariffPeriods.map((period) => (
                                                            <div key={period.id} className="tariff-period-row">
                                                                <div className="tariff-period-main">
                                                                    <div className="tariff-period-line">
                                                                        <span className="badge badge-neutral">
                                                                            {t(`pages.tariffs.periodTypes.${period.period_type}` as Parameters<typeof t>[0], { defaultValue: period.period_type })}
                                                                        </span>
                                                                        <strong>CHF {period.price_chf_per_kwh}/kWh</strong>
                                                                    </div>
                                                                    <div className="muted tariff-period-meta">
                                                                        {period.period_type === 'flat'
                                                                            ? `${t('pages.tariffs.allDay')} · ${t('pages.tariffs.allWeekdays')}`
                                                                            : `${period.time_from || '--'} - ${period.time_to || '--'} · ${period.weekdays || t('pages.tariffs.allWeekdays')}`}
                                                                    </div>
                                                                </div>

                                                                <div className="tariff-period-actions">
                                                                    <button className="button button-secondary button-compact" type="button" onClick={() => startPeriodEdit(period)}>
                                                                        <FontAwesomeIcon icon={faPen} fixedWidth />
                                                                        {t('common.edit')}
                                                                    </button>
                                                                    <button
                                                                        className="button button-danger button-compact"
                                                                        type="button"
                                                                        disabled={deletePeriodMutation.isPending || dialogLoading}
                                                                        onClick={() => confirm({
                                                                            title: t('pages.tariffs.deletePeriodTitle'),
                                                                            message: t('pages.tariffs.deletePeriodMessage', { name: tariffNameById.get(period.tariff) ?? period.tariff }),
                                                                            confirmText: t('pages.tariffs.deletePeriodConfirm'),
                                                                            isDangerous: true,
                                                                            onConfirm: () => deletePeriodMutation.mutate(period.id),
                                                                        })}
                                                                    >
                                                                        <FontAwesomeIcon icon={faTrash} fixedWidth />
                                                                        {t('common.delete')}
                                                                    </button>
                                                                </div>
                                                            </div>
                                                        ))}
                                                    </div>
                                                )}
                                            </div>
                                        </article>
                                    )
                                })}
                            </div>
                        </section>
                    ))}
                </div>
            )}

            {dialog && (
                <ConfirmDialog {...dialog} isLoading={dialogLoading} onConfirm={handleConfirm} onCancel={handleCancel} />
            )}
        </div>
    )
}
