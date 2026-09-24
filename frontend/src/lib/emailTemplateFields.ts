/** Email template route keys; field definitions come from the backend. */
export const EMAIL_TEMPLATE_KEYS = [
    'invoice_email',
    'participant_onboarding',
    'email_verification',
    'participant_magic_link',
] as const

export type EmailTemplateKey = (typeof EMAIL_TEMPLATE_KEYS)[number]
