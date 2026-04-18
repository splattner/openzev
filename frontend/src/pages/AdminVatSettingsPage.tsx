import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome'
import { faCheck, faPen, faPlus, faTrash, faXmark } from '@fortawesome/free-solid-svg-icons'
import { createVatRate, deleteVatRate, fetchVatRates, formatApiError, updateVatRate } from '../lib/api'
import { formatShortDate, useAppSettings } from '../lib/appSettings'
import { useTranslation } from 'react-i18next'
import { useToast } from '../lib/toast'
import { ConfirmDialog, useConfirmDialog } from '../components/ConfirmDialog'
import type { VatRateInput } from '../types/api'

type VatRateFormState = {
    rate_percent: string
    valid_from: string
    valid_to?: string | null
}

const defaultForm: VatRateFormState = {
    rate_percent: '8.1',
    valid_from: new Date().toISOString().slice(0, 10),
    valid_to: null,
}

export function AdminVatSettingsPage() {
    const queryClient = useQueryClient()
    const { pushToast } = useToast()
    const { settings } = useAppSettings()
    const { t } = useTranslation()
    const { dialog, confirm, handleConfirm, handleCancel, isLoading: dialogLoading } = useConfirmDialog()
    const [form, setForm] = useState<VatRateFormState>(defaultForm)
    const [editingId, setEditingId] = useState<number | null>(null)

    const vatRatesQuery = useQuery({
        queryKey: ['vat-rates'],
        queryFn: fetchVatRates,
    })

    const vatRates = useMemo(() => vatRatesQuery.data?.results ?? [], [vatRatesQuery.data?.results])
    const today = new Date().toISOString().slice(0, 10)

    const activeVatRate = useMemo(
        () => vatRates.find((rate) => rate.valid_from <= today && (!rate.valid_to || rate.valid_to >= today)) ?? null,
        [today, vatRates],
    )

    const futureVatRatesCount = useMemo(
        () => vatRates.filter((rate) => rate.valid_from > today).length,
        [today, vatRates],
    )

    const saveMutation = useMutation({
        mutationFn: ({ id, payload }: { id?: number; payload: VatRateInput }) => {
            if (id) return updateVatRate(id, payload)
            return createVatRate(payload)
        },
        onSuccess: (_, variables) => {
            void queryClient.invalidateQueries({ queryKey: ['vat-rates'] })
            setForm(defaultForm)
            setEditingId(null)
            pushToast(variables.id ? t('adminVatSettings.messages.updated') : t('adminVatSettings.messages.created'), 'success')
        },
        onError: (error) => pushToast(formatApiError(error, t('adminVatSettings.messages.saveFailed')), 'error'),
    })

    const deleteMutation = useMutation({
        mutationFn: deleteVatRate,
        onSuccess: () => {
            void queryClient.invalidateQueries({ queryKey: ['vat-rates'] })
            pushToast(t('adminVatSettings.messages.deleted'), 'success')
        },
        onError: (error) => pushToast(formatApiError(error, t('adminVatSettings.messages.deleteFailed')), 'error'),
    })

    function resetForm() {
        setForm(defaultForm)
        setEditingId(null)
    }

    function toVatPayload(values: VatRateFormState): VatRateInput | null {
        const percentage = Number(values.rate_percent)
        if (!Number.isFinite(percentage) || percentage < 0 || percentage > 100) {
            pushToast(t('adminVatSettings.messages.invalidRate'), 'error')
            return null
        }
        return {
            rate: (percentage / 100).toFixed(4),
            valid_from: values.valid_from,
            valid_to: values.valid_to || null,
        }
    }

    return (
        <div className="page-stack">
            <header>
                <p className="eyebrow">{t('adminVatSettings.eyebrow')}</p>
                <h2>{t('adminVatSettings.title')}</h2>
                <p className="muted">
                    {t('adminVatSettings.description')}
                </p>
            </header>

            <section
                style={{
                    display: 'grid',
                    gap: '1rem',
                    gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))',
                }}
            >
                <article className="stat-card">
                    <span className="eyebrow">{t('adminVatSettings.stats.total')}</span>
                    <strong>{vatRates.length}</strong>
                </article>
                <article className="stat-card">
                    <span className="eyebrow">{t('adminVatSettings.stats.active')}</span>
                    <strong>
                        {activeVatRate ? `${(Number(activeVatRate.rate) * 100).toFixed(2)}%` : t('adminVatSettings.stats.none')}
                    </strong>
                </article>
                <article className="stat-card">
                    <span className="eyebrow">{t('adminVatSettings.stats.scheduled')}</span>
                    <strong>{futureVatRatesCount}</strong>
                </article>
            </section>

            <section className="card page-stack" style={{ maxWidth: 860 }}>
                <h3 style={{ marginTop: 0 }}>{editingId ? t('adminVatSettings.editTitle') : t('adminVatSettings.createTitle')}</h3>
                <form
                    className="page-stack"
                    onSubmit={(event) => {
                        event.preventDefault()
                        const payload = toVatPayload(form)
                        if (!payload) return
                        saveMutation.mutate({ id: editingId ?? undefined, payload })
                    }}
                >
                    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: '1rem' }}>
                        <label>
                            <span>{t('adminVatSettings.form.rate')}</span>
                            <input
                                type="number"
                                min="0"
                                max="100"
                                step="0.0001"
                                value={form.rate_percent}
                                onChange={(event) => setForm((prev) => ({ ...prev, rate_percent: event.target.value }))}
                                placeholder="8.1"
                                required
                            />
                            <small className="muted">{t('adminVatSettings.form.rateHint')}</small>
                        </label>
                        <label>
                            <span>{t('adminVatSettings.form.validFrom')}</span>
                            <input
                                type="date"
                                value={form.valid_from}
                                onChange={(event) => setForm((prev) => ({ ...prev, valid_from: event.target.value }))}
                                required
                            />
                            <small className="muted">{t('adminVatSettings.form.validFromHint')}</small>
                        </label>
                        <label>
                            <span>{t('adminVatSettings.form.validTo')}</span>
                            <input
                                type="date"
                                value={form.valid_to ?? ''}
                                onChange={(event) => setForm((prev) => ({ ...prev, valid_to: event.target.value || null }))}
                            />
                            <small className="muted">{t('adminVatSettings.form.validToHint')}</small>
                        </label>
                    </div>

                    <div className="actions-row actions-row-wrap">
                        <button className="button button-primary" type="submit" disabled={saveMutation.isPending}>
                            <FontAwesomeIcon icon={editingId ? faCheck : faPlus} fixedWidth />
                            {saveMutation.isPending ? t('common.saving') : editingId ? t('adminVatSettings.actions.update') : t('adminVatSettings.actions.create')}
                        </button>
                        {editingId && (
                            <button className="button button-secondary" type="button" onClick={resetForm}>
                                <FontAwesomeIcon icon={faXmark} fixedWidth />
                                {t('adminVatSettings.actions.cancelEdit')}
                            </button>
                        )}
                    </div>
                </form>
            </section>

            <section className="page-stack" style={{ maxWidth: 860 }}>
                <h3 style={{ marginTop: 0 }}>{t('adminVatSettings.listTitle')}</h3>
                {vatRatesQuery.isLoading ? (
                    <div className="muted">{t('adminVatSettings.loading')}</div>
                ) : vatRates.length === 0 ? (
                    <div className="muted">{t('adminVatSettings.empty')}</div>
                ) : (
                    <div className="table-card">
                        <table>
                            <thead>
                                <tr>
                                    <th>{t('adminVatSettings.table.rate')}</th>
                                    <th>{t('adminVatSettings.table.validFrom')}</th>
                                    <th>{t('adminVatSettings.table.validTo')}</th>
                                    <th>{t('common.actions')}</th>
                                </tr>
                            </thead>
                            <tbody>
                                {vatRates.map((rate) => (
                                    <tr key={rate.id}>
                                        <td>{(Number(rate.rate) * 100).toFixed(2)}%</td>
                                        <td>{formatShortDate(rate.valid_from, settings)}</td>
                                        <td>{rate.valid_to ? formatShortDate(rate.valid_to, settings) : t('adminVatSettings.table.openEnded')}</td>
                                        <td className="actions-cell">
                                            <div className="actions-cell-content">
                                                <button
                                                    className="button button-secondary button-compact"
                                                    type="button"
                                                    onClick={() => {
                                                        setEditingId(rate.id)
                                                        setForm({
                                                            rate_percent: (Number(rate.rate) * 100).toFixed(4).replace(/\.?0+$/, ''),
                                                            valid_from: rate.valid_from,
                                                            valid_to: rate.valid_to ?? null,
                                                        })
                                                    }}
                                                >
                                                    <FontAwesomeIcon icon={faPen} fixedWidth />
                                                    {t('common.edit')}
                                                </button>
                                                <button
                                                    className="button button-danger button-compact"
                                                    type="button"
                                                    disabled={deleteMutation.isPending || dialogLoading}
                                                    onClick={() => confirm({
                                                        title: t('adminVatSettings.deleteTitle'),
                                                        message: t('adminVatSettings.deleteMessage', { rate: (Number(rate.rate) * 100).toFixed(2) }),
                                                        confirmText: t('common.delete'),
                                                        cancelText: t('common.cancel'),
                                                        isDangerous: true,
                                                        onConfirm: () => deleteMutation.mutate(rate.id),
                                                    })}
                                                >
                                                    <FontAwesomeIcon icon={faTrash} fixedWidth />
                                                    {t('common.delete')}
                                                </button>
                                            </div>
                                        </td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    </div>
                )}
            </section>

            {dialog && (
                <ConfirmDialog
                    {...dialog}
                    isLoading={dialogLoading}
                    onConfirm={handleConfirm}
                    onCancel={handleCancel}
                />
            )}
        </div>
    )
}
