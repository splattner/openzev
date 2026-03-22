import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useMemo, useState, type ChangeEvent, type FormEvent } from 'react'
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

    const tariffNameById = useMemo(() => {
        return new Map((tariffs || []).map((tariff) => [tariff.id, tariff.name]))
    }, [tariffs])

    const energyTariffs = useMemo(() => {
        return tariffs.filter((tariff) => tariff.billing_mode === 'energy')
    }, [tariffs])

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
        if (tariffForm.billing_mode !== 'energy' && !tariffForm.fixed_price_chf) {
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

    function openCreatePeriodModal() {
        if (!energyTariffs.length) {
            pushToast('Create an energy-based tariff before adding tariff periods.', 'error')
            return
        }
        setEditingPeriodId(null)
        setPeriodForm({ ...defaultPeriodForm, tariff: energyTariffs[0]?.id || '' })
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
        return <div className="card">Loading tariffs...</div>
    }

    if (tariffsQuery.isError || periodsQuery.isError) {
        return <div className="card error-banner">Failed to load tariffs.</div>
    }

    return (
        <div className="page-stack">
            <header>
                <h2>{t('pages.tariffs.title')}</h2>
                <p className="muted">{t('pages.tariffs.description')}</p>
            </header>

            <div style={{ display: 'flex', gap: '1rem', marginBottom: '1rem' }}>
                <button className="button button-primary" onClick={openCreateTariffModal}>
                    {t('pages.tariffs.newTariff')}
                </button>
                <button className="button button-secondary" onClick={openExportModal}>
                    {t('pages.tariffs.exportJson')}
                </button>
                <button className="button button-secondary" onClick={openImportModal}>
                    {t('pages.tariffs.importJson')}
                </button>
            </div>

            <FormModal
                isOpen={showExportModal}
                title={t('pages.tariffs.exportModalTitle')}
                onClose={closeExportModal}
                maxWidth="520px"
            >
                <div style={{ display: 'grid', gap: '1rem' }}>
                    <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '1rem' }}>
                        <button className="button button-secondary" type="button" onClick={closeExportModal}>{t('pages.tariffs.cancel')}</button>
                        <button className="button button-primary" type="button" onClick={handleExport} disabled={exportMutation.isPending}>
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
                        <button className="button button-secondary" type="button" onClick={closeImportModal}>{t('pages.tariffs.close')}</button>
                    </div>
                </div>
            </FormModal>

            <FormModal
                isOpen={showTariffModal}
                title={editingTariffId ? t('pages.tariffs.editTitle') : t('pages.tariffs.createTitle')}
                onClose={closeTariffModal}
            >
                <form onSubmit={submitTariff} style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1rem' }}>
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
                        </select>
                    </label>
                    <label>
                        <span>{t('pages.tariffs.form.billingMode')}</span>
                        <select
                            value={tariffForm.billing_mode}
                            onChange={(event) => {
                                const billingMode = event.target.value as TariffInput['billing_mode']
                                setTariffForm((prev) => ({
                                    ...prev,
                                    billing_mode: billingMode,
                                    energy_type: billingMode === 'energy' ? (prev.energy_type || 'local') : null,
                                    fixed_price_chf: billingMode === 'energy' ? null : (prev.fixed_price_chf || ''),
                                }))
                            }}
                        >
                            <option value="energy">{t('pages.tariffs.billingModes.energy')}</option>
                            <option value="monthly_fee">{t('pages.tariffs.billingModes.monthly_fee')}</option>
                            <option value="yearly_fee">{t('pages.tariffs.billingModes.yearly_fee')}</option>
                            <option value="per_metering_point_monthly_fee">{t('pages.tariffs.billingModes.per_metering_point_monthly_fee')}</option>
                            <option value="per_metering_point_yearly_fee">{t('pages.tariffs.billingModes.per_metering_point_yearly_fee')}</option>
                        </select>
                    </label>
                    {tariffForm.billing_mode === 'energy' ? (
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
                    ) : (
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
                    )}
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
                            Cancel
                        </button>
                        <button className="button button-primary" type="submit" disabled={tariffMutation.isPending}>
                            {editingTariffId ? t('pages.tariffs.saveTariff') : t('pages.tariffs.createTariff')}
                        </button>
                    </div>
                </form>
            </FormModal>

            <div style={{ display: 'flex', gap: '1rem', marginBottom: '1rem' }}>
                <button className="button button-primary" onClick={openCreatePeriodModal}>
                    {t('pages.tariffs.newPeriod')}
                </button>
            </div>

            <FormModal
                isOpen={showPeriodModal}
                title={editingPeriodId ? t('pages.tariffs.editPeriodTitle') : t('pages.tariffs.createPeriodTitle')}
                onClose={closePeriodModal}
            >
                <form onSubmit={submitPeriod} style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1rem' }}>
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
                            Cancel
                        </button>
                        <button className="button button-primary" type="submit" disabled={periodMutation.isPending}>
                            {editingPeriodId ? t('pages.tariffs.savePeriod') : t('pages.tariffs.createPeriod')}
                        </button>
                    </div>
                </form>
            </FormModal>

            <div className="table-card">
                <h3>{t('pages.tariffs.tariffList')}</h3>
                <table>
                    <thead>
                        <tr>
                            <th>{t('pages.tariffs.col.name')}</th>
                            <th>{t('pages.tariffs.col.category')}</th>
                            <th>{t('pages.tariffs.col.billingMode')}</th>
                            <th>{t('pages.tariffs.col.pricing')}</th>
                            <th>{t('pages.tariffs.col.validity')}</th>
                            <th>{t('pages.tariffs.col.actions')}</th>
                        </tr>
                    </thead>
                    <tbody>
                        {tariffs.length ? tariffs.map((tariff) => (
                            <tr key={tariff.id}>
                                <td>{tariff.name}</td>
                                <td>{t(`pages.tariffs.categories.${tariff.category}` as Parameters<typeof t>[0])}</td>
                                <td>{t(`pages.tariffs.billingModes.${tariff.billing_mode}` as Parameters<typeof t>[0])}</td>
                                <td>
                                    {tariff.billing_mode === 'energy'
                                        ? t(`pages.tariffs.energyTypes.${tariff.energy_type || 'local'}` as Parameters<typeof t>[0])
                                        : `CHF ${tariff.fixed_price_chf || '0.00'}`}
                                </td>
                                <td>{formatShortDate(tariff.valid_from, settings)} → {tariff.valid_to ? formatShortDate(tariff.valid_to, settings) : '-'}</td>
                                <td className="actions-cell">
                                    <button className="button button-primary" type="button" onClick={() => startTariffEdit(tariff)}>
                                        Edit
                                    </button>
                                    <button
                                        className="button danger"
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
                                        Delete
                                    </button>
                                </td>
                            </tr>
                        )) : (
                            <tr>
                                <td colSpan={6}>{t('pages.tariffs.noTariffs')}</td>
                            </tr>
                        )}
                    </tbody>
                </table>
            </div>

            <div className="table-card">
                <h3>{t('pages.tariffs.tariffPeriods')}</h3>
                <table>
                    <thead>
                        <tr>
                            <th>{t('pages.tariffs.periodCol.tariff')}</th>
                            <th>{t('pages.tariffs.periodCol.type')}</th>
                            <th>{t('pages.tariffs.periodCol.pricePerKwh')}</th>
                            <th>{t('pages.tariffs.periodCol.time')}</th>
                            <th>{t('pages.tariffs.periodCol.weekdays')}</th>
                            <th>{t('pages.tariffs.periodCol.actions')}</th>
                        </tr>
                    </thead>
                    <tbody>
                        {periods.length ? periods.map((period) => (
                            <tr key={period.id}>
                                <td>{tariffNameById.get(period.tariff) || period.tariff}</td>
                                <td>{t(`pages.tariffs.periodTypes.${period.period_type}` as Parameters<typeof t>[0], { defaultValue: period.period_type })}</td>
                                <td>{period.price_chf_per_kwh}</td>
                                <td>{period.time_from || '-'} → {period.time_to || '-'}</td>
                                <td>{period.weekdays || t('pages.tariffs.allWeekdays')}</td>
                                <td className="actions-cell">
                                    <button className="button button-primary" type="button" onClick={() => startPeriodEdit(period)}>
                                        Edit
                                    </button>
                                    <button
                                        className="button danger"
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
                                        Delete
                                    </button>
                                </td>
                            </tr>
                        )) : (
                            <tr>
                                <td colSpan={6}>{t('pages.tariffs.noPeriods')}</td>
                            </tr>
                        )}
                    </tbody>
                </table>
            </div>

            {dialog && (
                <ConfirmDialog {...dialog} isLoading={dialogLoading} onConfirm={handleConfirm} onCancel={handleCancel} />
            )}
        </div>
    )
}
