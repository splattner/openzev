import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { createVatRate, deleteVatRate, fetchVatRates, formatApiError, updateVatRate } from '../lib/api'
import { formatShortDate, useAppSettings } from '../lib/appSettings'
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
    const { dialog, confirm, handleConfirm, handleCancel, isLoading: dialogLoading } = useConfirmDialog()
    const [form, setForm] = useState<VatRateFormState>(defaultForm)
    const [editingId, setEditingId] = useState<number | null>(null)

    const vatRatesQuery = useQuery({
        queryKey: ['vat-rates'],
        queryFn: fetchVatRates,
    })

    const vatRates = useMemo(() => vatRatesQuery.data?.results ?? [], [vatRatesQuery.data?.results])

    const saveMutation = useMutation({
        mutationFn: ({ id, payload }: { id?: number; payload: VatRateInput }) => {
            if (id) return updateVatRate(id, payload)
            return createVatRate(payload)
        },
        onSuccess: (_, variables) => {
            void queryClient.invalidateQueries({ queryKey: ['vat-rates'] })
            setForm(defaultForm)
            setEditingId(null)
            pushToast(variables.id ? 'VAT rate updated.' : 'VAT rate created.', 'success')
        },
        onError: (error) => pushToast(formatApiError(error, 'Failed to save VAT rate.'), 'error'),
    })

    const deleteMutation = useMutation({
        mutationFn: deleteVatRate,
        onSuccess: () => {
            void queryClient.invalidateQueries({ queryKey: ['vat-rates'] })
            pushToast('VAT rate deleted.', 'success')
        },
        onError: (error) => pushToast(formatApiError(error, 'Failed to delete VAT rate.'), 'error'),
    })

    function resetForm() {
        setForm(defaultForm)
        setEditingId(null)
    }

    function toVatPayload(values: VatRateFormState): VatRateInput | null {
        const percentage = Number(values.rate_percent)
        if (!Number.isFinite(percentage) || percentage < 0 || percentage > 100) {
            pushToast('Rate must be a valid percentage between 0 and 100.', 'error')
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
                <p className="eyebrow">Admin Console</p>
                <h2>VAT Management</h2>
                <p className="muted">
                    Manage global VAT rates by validity range. Invoices use the rate active on the invoice period end date, but only if the ZEV has a VAT number.
                </p>
            </header>

            <section className="card page-stack" style={{ maxWidth: 860 }}>
                <h3 style={{ marginTop: 0 }}>{editingId ? 'Edit VAT rate' : 'Add VAT rate'}</h3>
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
                            <span>Rate (%)</span>
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
                            <small className="muted">Enter percentage directly (example: 8.1).</small>
                        </label>
                        <label>
                            <span>Valid from</span>
                            <input
                                type="date"
                                value={form.valid_from}
                                onChange={(event) => setForm((prev) => ({ ...prev, valid_from: event.target.value }))}
                                required
                            />
                            <small className="muted">First day this VAT rate applies.</small>
                        </label>
                        <label>
                            <span>Valid to (optional)</span>
                            <input
                                type="date"
                                value={form.valid_to ?? ''}
                                onChange={(event) => setForm((prev) => ({ ...prev, valid_to: event.target.value || null }))}
                            />
                            <small className="muted">Leave empty for currently active/open-ended rate.</small>
                        </label>
                    </div>

                    <div className="actions-row">
                        <button className="button button-primary" type="submit" disabled={saveMutation.isPending}>
                            {saveMutation.isPending ? 'Saving…' : editingId ? 'Update VAT rate' : 'Create VAT rate'}
                        </button>
                        {editingId && (
                            <button className="button button-secondary" type="button" onClick={resetForm}>
                                Cancel edit
                            </button>
                        )}
                    </div>
                </form>
            </section>

            <section className="card page-stack" style={{ maxWidth: 860 }}>
                <h3 style={{ marginTop: 0 }}>Configured VAT rates</h3>
                {vatRatesQuery.isLoading ? (
                    <div className="muted">Loading VAT rates…</div>
                ) : vatRates.length === 0 ? (
                    <div className="muted">No VAT rates configured yet.</div>
                ) : (
                    <table>
                        <thead>
                            <tr>
                                <th>Rate</th>
                                <th>Valid from</th>
                                <th>Valid to</th>
                                <th>Actions</th>
                            </tr>
                        </thead>
                        <tbody>
                            {vatRates.map((rate) => (
                                <tr key={rate.id}>
                                    <td>{(Number(rate.rate) * 100).toFixed(2)}%</td>
                                    <td>{formatShortDate(rate.valid_from, settings)}</td>
                                    <td>{rate.valid_to ? formatShortDate(rate.valid_to, settings) : 'Open'}</td>
                                    <td>
                                        <div style={{ display: 'flex', gap: '0.5rem' }}>
                                            <button
                                                className="button button-secondary"
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
                                                Edit
                                            </button>
                                            <button
                                                className="button button-danger"
                                                type="button"
                                                disabled={deleteMutation.isPending || dialogLoading}
                                                onClick={() => confirm({
                                                    title: 'Delete VAT rate',
                                                    message: `Are you sure you want to delete the ${(Number(rate.rate) * 100).toFixed(2)}% VAT rate? This action cannot be undone.`,
                                                    confirmText: 'Delete',
                                                    isDangerous: true,
                                                    onConfirm: () => deleteMutation.mutate(rate.id),
                                                })}
                                            >
                                                Delete
                                            </button>
                                        </div>
                                    </td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
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
