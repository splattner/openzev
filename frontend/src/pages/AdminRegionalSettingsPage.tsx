import { useEffect, useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { updateAppSettings } from '../lib/api'
import {
    DATE_TIME_FORMAT_OPTIONS,
    LONG_DATE_FORMAT_OPTIONS,
    SHORT_DATE_FORMAT_OPTIONS,
    formatDateByPattern,
    formatDateTime,
    useAppSettings,
} from '../lib/appSettings'
import { useToast } from '../lib/toast'
import type { DateTimeFormat, LongDateFormat, ShortDateFormat } from '../types/api'

export function AdminRegionalSettingsPage() {
    const queryClient = useQueryClient()
    const { pushToast } = useToast()
    const { settings, isLoading } = useAppSettings()
    const [form, setForm] = useState({
        date_format_short: settings.date_format_short,
        date_format_long: settings.date_format_long,
        date_time_format: settings.date_time_format,
    })

    useEffect(() => {
        setForm({
            date_format_short: settings.date_format_short,
            date_format_long: settings.date_format_long,
            date_time_format: settings.date_time_format,
        })
    }, [settings.date_format_long, settings.date_format_short, settings.date_time_format])

    const saveMutation = useMutation({
        mutationFn: updateAppSettings,
        onSuccess: (data) => {
            queryClient.setQueryData(['app-settings'], data)
            pushToast('Regional settings updated.', 'success')
        },
        onError: () => pushToast('Failed to update regional settings.', 'error'),
    })

    if (isLoading) {
        return <div className="card">Loading settings...</div>
    }

    const previewDate = '2026-03-18'
    const previewDateTime = '2026-03-18T14:35:00Z'

    return (
        <div className="page-stack">
            <header>
                <p className="eyebrow">Admin Console</p>
                <h2>Regional Settings</h2>
                <p className="muted">Manage global date display formats used across the application.</p>
            </header>

            <section className="card" style={{ maxWidth: 720 }}>
                <form
                    onSubmit={(event) => {
                        event.preventDefault()
                        saveMutation.mutate(form)
                    }}
                    className="page-stack"
                >
                    <label>
                        <span>Short date format</span>
                        <select
                            value={form.date_format_short}
                            onChange={(event) => setForm((prev) => ({
                                ...prev,
                                date_format_short: event.target.value as ShortDateFormat,
                            }))}
                        >
                            {SHORT_DATE_FORMAT_OPTIONS.map((option) => (
                                <option key={option.value} value={option.value}>{option.label}</option>
                            ))}
                        </select>
                    </label>

                    <label>
                        <span>Long date format</span>
                        <select
                            value={form.date_format_long}
                            onChange={(event) => setForm((prev) => ({
                                ...prev,
                                date_format_long: event.target.value as LongDateFormat,
                            }))}
                        >
                            {LONG_DATE_FORMAT_OPTIONS.map((option) => (
                                <option key={option.value} value={option.value}>{option.label}</option>
                            ))}
                        </select>
                    </label>

                    <label>
                        <span>Date & time format</span>
                        <select
                            value={form.date_time_format}
                            onChange={(event) => setForm((prev) => ({
                                ...prev,
                                date_time_format: event.target.value as DateTimeFormat,
                            }))}
                        >
                            {DATE_TIME_FORMAT_OPTIONS.map((option) => (
                                <option key={option.value} value={option.value}>{option.label}</option>
                            ))}
                        </select>
                    </label>

                    <div className="card" style={{ background: 'var(--color-bg-soft, #f8fafc)' }}>
                        <h3 style={{ marginTop: 0 }}>Preview</h3>
                        <p style={{ marginBottom: '0.35rem' }}>
                            <strong>Short:</strong> {formatDateByPattern(previewDate, form.date_format_short)}
                        </p>
                        <p style={{ marginBottom: '0.35rem' }}>
                            <strong>Long:</strong> {formatDateByPattern(previewDate, form.date_format_long)}
                        </p>
                        <p style={{ marginBottom: 0 }}>
                            <strong>Date & time:</strong> {formatDateTime(previewDateTime, {
                                ...settings,
                                date_format_short: form.date_format_short,
                                date_format_long: form.date_format_long,
                                date_time_format: form.date_time_format,
                            })}
                        </p>
                    </div>

                    <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '1rem' }}>
                        <button
                            className="button button-primary"
                            type="submit"
                            disabled={saveMutation.isPending}
                        >
                            Save settings
                        </button>
                    </div>
                </form>
            </section>
        </div>
    )
}