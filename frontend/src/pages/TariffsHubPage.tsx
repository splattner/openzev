import { lazy, Suspense } from 'react'
import { useTranslation } from 'react-i18next'
import { AppTabs } from '../components/AppTabs'
import { PageHeader } from '../components/PageHeader'
import { PageSkeleton } from '../components/PageSkeleton'
import { useScopeNote } from '../lib/communityAccess'
import { useManagedZev } from '../lib/managedZev'
import { usePageNavigation } from '../lib/usePageNavigation'

const TariffsPage = lazy(async () => ({ default: (await import('./TariffsPage')).TariffsPage }))
const TariffProgressionPage = lazy(async () => ({ default: (await import('./TariffProgressionPage')).TariffProgressionPage }))

export function TariffsHubPage({ tab }: { tab: 'components' | 'progression' }) {
    const { t } = useTranslation()
    const { selectedZev } = useManagedZev()
    const scopeNote = useScopeNote()
    const { navigateTab } = usePageNavigation()

    return (
        <div className="page-stack">
            <PageHeader
                eyebrow={selectedZev?.name}
                communitySwitch
                scopeNote={scopeNote}
                title={t('pages.tariffs.title')}
                documentTitle={`${t(`pages.tariffs.tabs.${tab}`)} · ${t('pages.tariffs.title')}`}
                description={t(tab === 'components' ? 'pages.tariffs.description' : 'pages.tariffs.progression.description')}
            />
            <AppTabs value={tab} keepMounted={false} onChange={(value) => {
                if (value === null || value === tab) return
                navigateTab(value === 'progression' ? '/tariffs/progression' : '/tariffs')
            }}>
                <AppTabs.List aria-label={t('pages.tariffs.title')}>
                    <AppTabs.Tab value="components">{t('pages.tariffs.tabs.components')}</AppTabs.Tab>
                    <AppTabs.Tab value="progression">{t('pages.tariffs.tabs.progression')}</AppTabs.Tab>
                </AppTabs.List>
                <AppTabs.Panel value="components">
                    <Suspense fallback={<PageSkeleton variant="table" />}>
                        <TariffsPage />
                    </Suspense>
                </AppTabs.Panel>
                <AppTabs.Panel value="progression">
                    <Suspense fallback={<PageSkeleton variant="table" />}>
                        <TariffProgressionPage />
                    </Suspense>
                </AppTabs.Panel>
            </AppTabs>
        </div>
    )
}
