import { useTranslation } from 'react-i18next'
import { Tabs } from '@mantine/core'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { AdminPdfTemplatesPage, type PdfTemplateTab } from './AdminPdfTemplatesPage'
import { AdminEmailTemplatesPage } from './AdminEmailTemplatesPage'
import type { EmailTemplateKey } from '../lib/emailTemplateFields'

export type AdminTemplatesTab = 'pdf' | 'email'

type TemplateKey = PdfTemplateTab | EmailTemplateKey

const pdfTemplates: PdfTemplateTab[] = ['invoice', 'contract', 'annual_statement']
const emailTemplates: EmailTemplateKey[] = [
    'invoice_email', 'participant_onboarding', 'email_verification', 'participant_magic_link',
]

/**
 * Admin Templates hub (nav-regroup phase 3, spec §6): every template is a tab
 * in two labelled rows — PDF on one line, Email on the next — sharing one
 * standard tab strip. No icons, no nested pickers. Tabs are
 * routes: the document is selected by `?template=`, and switching to a
 * document of the other category navigates to that category's route.
 * /admin/pdf-templates and /admin/email-templates stay as aliases.
 */
export function AdminTemplatesHubPage({ tab = 'pdf' }: { tab?: AdminTemplatesTab }) {
    const { t } = useTranslation()
    const navigate = useNavigate()
    const [searchParams] = useSearchParams()
    const requested = searchParams.get('template')
    const pdf = pdfTemplates.find((key) => key === requested) ?? 'invoice'
    const email = emailTemplates.find((key) => key === requested) ?? 'invoice_email'
    const selected: TemplateKey = tab === 'pdf' ? pdf : email

    function handleTabChange(value: string | null) {
        if (!value || value === selected) return
        const category = pdfTemplates.some((key) => key === value) ? 'pdf' : 'email'
        const params = new URLSearchParams(searchParams)
        params.set('template', value)
        navigate(`/admin/templates/${category}?${params}`, { replace: true })
    }

    return (
        <div className="page-stack">
            <header>
                <p className="eyebrow">{t('nav.platformScope')}</p>
                <h2>{t('pages.adminTemplates.title')}</h2>
            </header>

            <Tabs
                classNames={{ root: 'app-tabs', list: 'app-tabs-list', tab: 'app-tabs-tab' }}
                value={selected}
                keepMounted={false}
                onChange={handleTabChange}
            >
                <div className="template-tabs-rows">
                    <div className="template-tabs-row">
                        <span className="template-tab-group" id="template-tabs-group-pdf">
                            {t('pages.adminTemplates.tabs.pdf')}
                        </span>
                        <Tabs.List aria-labelledby="template-tabs-group-pdf">
                            {pdfTemplates.map((key) => (
                                <Tabs.Tab key={key} value={key}>
                                    {t(`pages.adminTemplates.items.${key}`)}
                                </Tabs.Tab>
                            ))}
                        </Tabs.List>
                    </div>
                    <div className="template-tabs-row">
                        <span className="template-tab-group" id="template-tabs-group-email">
                            {t('pages.adminTemplates.tabs.email')}
                        </span>
                        <Tabs.List aria-labelledby="template-tabs-group-email">
                            {emailTemplates.map((key) => (
                                <Tabs.Tab key={key} value={key}>
                                    {t(`pages.adminTemplates.items.${key}`)}
                                </Tabs.Tab>
                            ))}
                        </Tabs.List>
                    </div>
                </div>

                {pdfTemplates.map((key) => (
                    <Tabs.Panel key={key} value={key}>
                        <AdminPdfTemplatesPage embedded template={key} />
                    </Tabs.Panel>
                ))}
                {emailTemplates.map((key) => (
                    <Tabs.Panel key={key} value={key}>
                        <AdminEmailTemplatesPage embedded template={key} />
                    </Tabs.Panel>
                ))}
            </Tabs>
        </div>
    )
}
