/**
 * The email templates the admin console can edit.
 *
 * This union must cover every key in the backend's `EMAIL_TEMPLATE_DEFAULTS`.
 * The API already serves them all; a key missing here is simply invisible in
 * the UI, with nothing failing to say so — which is how `participant_magic_link`
 * shipped editable-by-API-only. `tests/email-template-parity.test.ts` guards it.
 */
export type EmailTemplateKey =
    | 'invoice_email'
    | 'participant_onboarding'
    | 'email_verification'
    | 'participant_magic_link'

export interface EmailField {
    variable: string
    descriptionKey: string
}

export const EMAIL_TEMPLATE_FIELDS: Record<EmailTemplateKey, EmailField[]> = {
    invoice_email: [
        { variable: '{invoice_number}', descriptionKey: 'admin.emailTemplates.fields.invoiceNumber' },
        { variable: '{zev_name}', descriptionKey: 'admin.emailTemplates.fields.zevName' },
        { variable: '{participant_name}', descriptionKey: 'admin.emailTemplates.fields.participantName' },
        { variable: '{period_start}', descriptionKey: 'admin.emailTemplates.fields.periodStart' },
        { variable: '{period_end}', descriptionKey: 'admin.emailTemplates.fields.periodEnd' },
        { variable: '{due_date}', descriptionKey: 'admin.emailTemplates.fields.dueDate' },
        { variable: '{total_chf}', descriptionKey: 'admin.emailTemplates.fields.totalChf' },
    ],
    participant_onboarding: [
        { variable: '{participant_name}', descriptionKey: 'admin.emailTemplates.fields.participantName' },
        { variable: '{inviter_name}', descriptionKey: 'admin.emailTemplates.fields.inviterName' },
        { variable: '{zev_name}', descriptionKey: 'admin.emailTemplates.fields.zevName' },
        { variable: '{link_url}', descriptionKey: 'admin.emailTemplates.fields.onboardingLinkUrl' },
    ],
    email_verification: [
        { variable: '{verify_url}', descriptionKey: 'admin.emailTemplates.fields.verifyUrl' },
    ],
    participant_magic_link: [
        { variable: '{participant_name}', descriptionKey: 'admin.emailTemplates.fields.participantName' },
        { variable: '{zev_name}', descriptionKey: 'admin.emailTemplates.fields.zevName' },
        { variable: '{link_url}', descriptionKey: 'admin.emailTemplates.fields.linkUrl' },
        { variable: '{valid_minutes}', descriptionKey: 'admin.emailTemplates.fields.validMinutes' },
    ],
}
