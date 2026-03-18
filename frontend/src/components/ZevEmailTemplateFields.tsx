type ZevEmailTemplateFieldsProps = {
    subjectTemplate: string
    bodyTemplate: string
    onSubjectTemplateChange: (value: string) => void
    onBodyTemplateChange: (value: string) => void
    showHeader?: boolean
}

const DEFAULT_EMAIL_SUBJECT = 'Invoice {invoice_number} – {zev_name}'
const DEFAULT_EMAIL_BODY =
    'Dear {participant_name},\n\n' +
    'Please find your energy invoice for the period {period_start} to {period_end} attached.\n\n' +
    'Total: CHF {total_chf}\n\n' +
    'Kind regards,\n{zev_name}'

const TEMPLATE_VARIABLES: { variable: string; description: string }[] = [
    { variable: '{participant_name}', description: 'Full name of the participant' },
    { variable: '{invoice_number}', description: 'Invoice number (e.g. INV-00001)' },
    { variable: '{period_start}', description: 'Start of the billing period (formatted date)' },
    { variable: '{period_end}', description: 'End of the billing period (formatted date)' },
    { variable: '{total_chf}', description: 'Total invoice amount in CHF' },
    { variable: '{zev_name}', description: 'Name of the ZEV' },
]

export function ZevEmailTemplateFields({
    subjectTemplate,
    bodyTemplate,
    onSubjectTemplateChange,
    onBodyTemplateChange,
    showHeader = true,
}: ZevEmailTemplateFieldsProps) {
    return (
        <>
            {showHeader && (
                <header>
                    <h3>Invoice Email Template</h3>
                    <p className="muted">
                        Customize the subject line and body of the invoice email sent to participants.
                        Leave a field blank to use the system default. Click <strong>Reset</strong> to clear a customization and revert to the default.
                    </p>
                </header>
            )}

            <div className="inline-form page-stack">
                <label>
                    <span>Subject</span>
                    <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center' }}>
                        <input
                            style={{ flex: 1 }}
                            value={subjectTemplate}
                            placeholder={DEFAULT_EMAIL_SUBJECT}
                            onChange={(event) => onSubjectTemplateChange(event.target.value)}
                        />
                        <button
                            type="button"
                            className="button button-secondary"
                            disabled={!subjectTemplate}
                            onClick={() => onSubjectTemplateChange('')}
                            title="Revert to system default"
                        >
                            Reset
                        </button>
                    </div>
                </label>

                <label>
                    <span>Body</span>
                    <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'flex-start' }}>
                        <textarea
                            style={{ flex: 1 }}
                            rows={10}
                            value={bodyTemplate}
                            placeholder={DEFAULT_EMAIL_BODY}
                            onChange={(event) => onBodyTemplateChange(event.target.value)}
                        />
                        <button
                            type="button"
                            className="button button-secondary"
                            disabled={!bodyTemplate}
                            onClick={() => onBodyTemplateChange('')}
                            title="Revert to system default"
                        >
                            Reset
                        </button>
                    </div>
                </label>

                <details open>
                    <summary style={{ cursor: 'pointer' }}>Available template variables</summary>
                    <table style={{ marginTop: '0.75rem', width: '100%' }}>
                        <thead>
                            <tr>
                                <th style={{ textAlign: 'left', padding: '0.4rem 0.75rem' }}>Variable</th>
                                <th style={{ textAlign: 'left', padding: '0.4rem 0.75rem' }}>Description</th>
                            </tr>
                        </thead>
                        <tbody>
                            {TEMPLATE_VARIABLES.map(({ variable, description }) => (
                                <tr key={variable}>
                                    <td style={{ padding: '0.4rem 0.75rem' }}>{variable}</td>
                                    <td style={{ padding: '0.4rem 0.75rem' }}>{description}</td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                </details>
            </div>
        </>
    )
}
