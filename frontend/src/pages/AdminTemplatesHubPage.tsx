import { useTranslation } from 'react-i18next'
import { AppTabs } from '../components/AppTabs'
import { usePageNavigation } from '../lib/usePageNavigation'
import { AdminPdfTemplatesPage, type PdfTemplateTab } from './AdminPdfTemplatesPage'
import { AdminEmailTemplatesPage } from './AdminEmailTemplatesPage'
import { EMAIL_TEMPLATE_KEYS, type EmailTemplateKey } from '../lib/emailTemplateFields'
import { PageHeader } from '../components/PageHeader'

export type AdminTemplatesTab = 'pdf' | 'email'

type TemplateKey = PdfTemplateTab | EmailTemplateKey

const pdfTemplates: PdfTemplateTab[] = ['invoice', 'contract', 'annual_statement', 'credit_note']
const emailTemplates: EmailTemplateKey[] = [...EMAIL_TEMPLATE_KEYS]

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
    const { searchParams, updateParams } = usePageNavigation()
    const requested = searchParams.get('template')
    const pdf = pdfTemplates.find((key) => key === requested) ?? 'invoice'
    const email = emailTemplates.find((key) => key === requested) ?? 'invoice_email'
    const selected: TemplateKey = tab === 'pdf' ? pdf : email

    function handleTabChange(value: string | null) {
        if (!value || value === selected) return
        const category = pdfTemplates.some((key) => key === value) ? 'pdf' : 'email'
        updateParams(params => params.set('template', value), { pathname: `/admin/templates/${category}` })
    }

    return (
        <div className="page-stack">
            <PageHeader eyebrow={t('nav.platformScope')} title={t('pages.adminTemplates.title')} />

            <AppTabs
                value={selected}
                keepMounted={false}
                onChange={handleTabChange}
            >
                <div className="template-tabs-rows">
                    <div className="template-tabs-row">
                        <span className="template-tab-group" id="template-tabs-group-pdf">
                            {t('pages.adminTemplates.tabs.pdf')}
                        </span>
                        <AppTabs.List aria-labelledby="template-tabs-group-pdf">
                            {pdfTemplates.map((key) => (
                                <AppTabs.Tab key={key} value={key}>
                                    {t(`pages.adminTemplates.items.${key}`)}
                                </AppTabs.Tab>
                            ))}
                        </AppTabs.List>
                    </div>
                    <div className="template-tabs-row">
                        <span className="template-tab-group" id="template-tabs-group-email">
                            {t('pages.adminTemplates.tabs.email')}
                        </span>
                        <AppTabs.List aria-labelledby="template-tabs-group-email">
                            {emailTemplates.map((key) => (
                                <AppTabs.Tab key={key} value={key}>
                                    {t(`pages.adminTemplates.items.${key}`)}
                                </AppTabs.Tab>
                            ))}
                        </AppTabs.List>
                    </div>
                </div>

                {pdfTemplates.map((key) => (
                    <AppTabs.Panel key={key} value={key}>
                        <AdminPdfTemplatesPage embedded template={key} />
                    </AppTabs.Panel>
                ))}
                {emailTemplates.map((key) => (
                    <AppTabs.Panel key={key} value={key}>
                        <AdminEmailTemplatesPage embedded template={key} />
                    </AppTabs.Panel>
                ))}
            </AppTabs>
        </div>
    )
}
