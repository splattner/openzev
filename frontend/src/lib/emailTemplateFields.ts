export type EmailTemplateKey = 'invoice_email' | 'participant_invitation' | 'email_verification'

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
    participant_invitation: [
        { variable: '{participant_name}', descriptionKey: 'admin.emailTemplates.fields.participantName' },
        { variable: '{inviter_name}', descriptionKey: 'admin.emailTemplates.fields.inviterName' },
        { variable: '{zev_name}', descriptionKey: 'admin.emailTemplates.fields.zevName' },
        { variable: '{username}', descriptionKey: 'admin.emailTemplates.fields.username' },
        { variable: '{temporary_password}', descriptionKey: 'admin.emailTemplates.fields.temporaryPassword' },
    ],
    email_verification: [
        { variable: '{verify_url}', descriptionKey: 'admin.emailTemplates.fields.verifyUrl' },
    ],
}
