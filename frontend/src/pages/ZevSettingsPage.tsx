import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState, type FormEvent } from 'react'
import { ZevEmailTemplateFields } from '../components/ZevEmailTemplateFields'
import { ZevGeneralSettingsFields } from '../components/ZevGeneralSettingsFields'
import { formatApiError, updateZev } from '../lib/api'
import { useManagedZev } from '../lib/managedZev'
import { getDefaultZevForm, mapZevToForm } from '../lib/zevForm'
import { useToast } from '../lib/toast'
import type { ZevInput } from '../types/api'

export function ZevSettingsPage() {
    const queryClient = useQueryClient()
    const { pushToast } = useToast()
    const { selectedZev, selectedZevId, isLoading } = useManagedZev()

    const [form, setForm] = useState<ZevInput>(getDefaultZevForm())
    const [error, setError] = useState<string | null>(null)

    useEffect(() => {
        if (!selectedZev) {
            setForm(getDefaultZevForm())
            return
        }

        setForm(mapZevToForm(selectedZev))
    }, [selectedZev])

    const updateMutation = useMutation({
        mutationFn: (payload: ZevInput) => updateZev(selectedZevId, payload),
        onSuccess: () => {
            setError(null)
            pushToast('ZEV settings updated.', 'success')
            void queryClient.invalidateQueries({ queryKey: ['zevs'] })
        },
        onError: (mutationError) => setError(formatApiError(mutationError, 'Failed to update ZEV settings.')),
    })

    function submit(event: FormEvent<HTMLFormElement>) {
        event.preventDefault()
        if (!selectedZevId) {
            return
        }
        updateMutation.mutate(form)
    }

    if (isLoading) {
        return <div className="card">Loading ZEV settings...</div>
    }

    if (!selectedZevId || !selectedZev) {
        return <div className="card">Select a ZEV from the global selector to edit settings.</div>
    }

    return (
        <div className="page-stack">
            <header>
                <h2>Settings</h2>
                <p className="muted">Edit the selected ZEV details.</p>
            </header>

            <section className="card page-stack">
                <form className="inline-form grid grid-3" onSubmit={submit}>
                    <ZevGeneralSettingsFields
                        form={form}
                        onChange={(patch) => setForm((previous) => ({ ...previous, ...patch }))}
                    />

                    {error && <div className="error-banner grid-span-full">{error}</div>}

                    <div className="actions-row grid-span-full">
                        <button className="button button-primary" type="submit" disabled={updateMutation.isPending}>
                            Save settings
                        </button>
                    </div>
                </form>
            </section>

            <section className="card page-stack">
                <form className="inline-form page-stack" onSubmit={submit}>
                    <ZevEmailTemplateFields
                        subjectTemplate={form.email_subject_template ?? ''}
                        bodyTemplate={form.email_body_template ?? ''}
                        onSubjectTemplateChange={(value) =>
                            setForm((previous) => ({ ...previous, email_subject_template: value }))
                        }
                        onBodyTemplateChange={(value) =>
                            setForm((previous) => ({ ...previous, email_body_template: value }))
                        }
                    />

                    {error && <div className="error-banner">{error}</div>}

                    <div className="actions-row">
                        <button className="button button-primary" type="submit" disabled={updateMutation.isPending}>
                            Save email template
                        </button>
                    </div>
                </form>
            </section>
        </div>
    )
}
