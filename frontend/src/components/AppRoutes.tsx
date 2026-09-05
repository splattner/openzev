import { Suspense, lazy } from 'react'
import { Route, Routes } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { Layout } from './Layout'
import { ProtectedRoute } from './ProtectedRoute'
import { AliasNavigate, InvoiceDetailAlias, MeteringDataAlias } from './RouteAliases'
import { PageSkeleton } from './PageSkeleton'
import { ManagedZevProvider } from '../lib/managedZev'

const AccountProfilePage = lazy(async () => ({ default: (await import('../pages/AccountProfilePage')).AccountProfilePage }))
const AdminDashboardPage = lazy(async () => ({ default: (await import('../pages/AdminDashboardPage')).AdminDashboardPage }))
const AdminAccountsPage = lazy(async () => ({ default: (await import('../pages/AdminAccountsPage')).AdminAccountsPage }))
const AdminApiKeysPage = lazy(async () => ({ default: (await import('../pages/AdminApiKeysPage')).AdminApiKeysPage }))
const AdminPdfTemplatesPage = lazy(async () => ({ default: (await import('../pages/AdminPdfTemplatesPage')).AdminPdfTemplatesPage }))
const AdminEmailTemplatesPage = lazy(async () => ({ default: (await import('../pages/AdminEmailTemplatesPage')).AdminEmailTemplatesPage }))
const AdminInvoicesPage = lazy(async () => ({ default: (await import('../pages/AdminInvoicesPage')).AdminInvoicesPage }))
const FeasibilityCalculatorPage = lazy(async () => ({ default: (await import('../pages/FeasibilityCalculatorPage')).FeasibilityCalculatorPage }))
const AuditLogsPage = lazy(async () => ({ default: (await import('../pages/AdminAuditLogsPage')).AuditLogsPage }))
const AdminSystemSettingsPage = lazy(async () => ({ default: (await import('../pages/AdminSystemSettingsPage')).AdminSystemSettingsPage }))
const DashboardPage = lazy(async () => ({ default: (await import('../pages/DashboardPage')).DashboardPage }))
const ImportsPage = lazy(async () => ({ default: (await import('../pages/ImportsPage')).ImportsPage }))
const ReportsPage = lazy(async () => ({ default: (await import('../pages/ReportsPage')).ReportsPage }))
const InvoiceDetailPage = lazy(async () => ({ default: (await import('../pages/InvoiceDetailPage')).InvoiceDetailPage }))
const InvoicesPage = lazy(async () => ({ default: (await import('../pages/InvoicesPage')).InvoicesPage }))
const MyInvoicesPage = lazy(async () => ({ default: (await import('../pages/MyInvoicesPage')).MyInvoicesPage }))
const LoginPage = lazy(async () => ({ default: (await import('../pages/LoginPage')).LoginPage }))
const MeteringChartPage = lazy(async () => ({ default: (await import('../pages/MeteringChartPage')).MeteringChartPage }))
const MeteringPointsPage = lazy(async () => ({ default: (await import('../pages/MeteringPointsPage')).MeteringPointsPage }))
const NotFoundPage = lazy(async () => ({ default: (await import('../pages/NotFoundPage')).NotFoundPage }))
const MagicSignInPage = lazy(async () => ({ default: (await import('../pages/MagicSignInPage')).MagicSignInPage }))
const PublicInvoicePage = lazy(async () => ({ default: (await import('../pages/PublicInvoicePage')).PublicInvoicePage }))
const ParticipantsPage = lazy(async () => ({ default: (await import('../pages/ParticipantsPage')).ParticipantsPage }))
const TariffsPage = lazy(async () => ({ default: (await import('../pages/TariffsPage')).TariffsPage }))
const VerifyEmailPage = lazy(async () => ({ default: (await import('../pages/VerifyEmailPage')).VerifyEmailPage }))
const ZevListPage = lazy(async () => ({ default: (await import('../pages/ZevListPage')).ZevListPage }))
const ZevSettingsPage = lazy(async () => ({ default: (await import('../pages/ZevSettingsPage')).ZevSettingsPage }))
const OAuthCallbackPage = lazy(async () => ({ default: (await import('../pages/OAuthCallbackPage')).OAuthCallbackPage }))

function AuthRouteFallback() {
  const { t } = useTranslation()
  return <div className="app-route-loading">{t('common.loading')}</div>
}

export function AppRoutes() {
  return (
    <Suspense fallback={<AuthRouteFallback />}>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route path="/verify-email" element={<VerifyEmailPage />} />
        <Route path="/oauth/callback" element={<OAuthCallbackPage />} />
        {/* Public (QR on invoice): no session, no app chrome. */}
        <Route path="/i/:prefix" element={<PublicInvoicePage />} />
        <Route path="/signin/:token" element={<MagicSignInPage />} />
        <Route
          path="/"
          element={
            <ProtectedRoute>
              <ManagedZevProvider>
                <Suspense fallback={<PageSkeleton variant="page" />}>
                  <Layout />
                </Suspense>
              </ManagedZevProvider>
            </ProtectedRoute>
          }
        >
          <Route index element={<DashboardPage />} />
          <Route path="account" element={<AccountProfilePage />} />
          <Route
            path="admin"
            element={
              <ProtectedRoute allowedRoles={['admin']}>
                <AdminDashboardPage />
              </ProtectedRoute>
            }
          />
          <Route
            path="admin/system-settings"
            element={
              <ProtectedRoute allowedRoles={['admin']}>
                <AdminSystemSettingsPage />
              </ProtectedRoute>
            }
          />
          <Route path="admin/settings/regional" element={<AliasNavigate to="/admin/system-settings?tab=regional" />} />
          <Route path="admin/settings/vat" element={<AliasNavigate to="/admin/system-settings?tab=vat" />} />
          <Route
            path="admin/pdf-templates"
            element={
              <ProtectedRoute allowedRoles={['admin']}>
                <AdminPdfTemplatesPage />
              </ProtectedRoute>
            }
          />
          <Route
            path="admin/email-templates"
            element={
              <ProtectedRoute allowedRoles={['admin']}>
                <AdminEmailTemplatesPage />
              </ProtectedRoute>
            }
          />
          <Route path="admin/features" element={<AliasNavigate to="/admin/system-settings?tab=features" />} />
          <Route path="admin/oauth" element={<AliasNavigate to="/admin/system-settings?tab=oauth" />} />
          <Route
            path="admin/invoices"
            element={
              <ProtectedRoute allowedRoles={['admin']}>
                <AdminInvoicesPage />
              </ProtectedRoute>
            }
          />
          <Route
            path="admin/audit-logs"
            element={
              <ProtectedRoute allowedRoles={['admin']}>
                <AuditLogsPage scope="admin" />
              </ProtectedRoute>
            }
          />
          <Route
            path="audit-logs"
            element={
              <ProtectedRoute allowedRoles={['admin', 'zev_owner']}>
                <AuditLogsPage scope="owner" />
              </ProtectedRoute>
            }
          />
          <Route
            path="admin/accounts"
            element={
              <ProtectedRoute allowedRoles={['admin']}>
                <AdminAccountsPage />
              </ProtectedRoute>
            }
          />
          <Route
            path="admin/api-keys"
            element={
              <ProtectedRoute allowedRoles={['admin']}>
                <AdminApiKeysPage />
              </ProtectedRoute>
            }
          />
          <Route
            path="admin/zevs"
            element={
              <ProtectedRoute allowedRoles={['admin']}>
                <ZevListPage />
              </ProtectedRoute>
            }
          />
          <Route
            path="participants"
            element={
              <ProtectedRoute allowedRoles={['admin', 'zev_owner']}>
                <ParticipantsPage />
              </ProtectedRoute>
            }
          />
          <Route
            path="zev-settings"
            element={
              <ProtectedRoute allowedRoles={['admin', 'zev_owner']}>
                <ZevSettingsPage />
              </ProtectedRoute>
            }
          />
          <Route path="metering-points" element={<MeteringPointsPage />} />
          {/* Same component types at the same tree positions so tab navigation preserves page state. */}
          <Route
            path="metering/chart"
            element={
              <ProtectedRoute>
                <MeteringChartPage tab="chart" />
              </ProtectedRoute>
            }
          />
          <Route
            path="metering/quality"
            element={
              <ProtectedRoute allowedRoles={['admin', 'zev_owner']}>
                <MeteringChartPage tab="quality" />
              </ProtectedRoute>
            }
          />
          <Route path="metering-data" element={<MeteringDataAlias />} />
          <Route path="metering" element={<AliasNavigate to="/metering/chart" />} />
          <Route
            path="tariffs"
            element={
              <ProtectedRoute allowedRoles={['admin', 'zev_owner']}>
                <TariffsPage />
              </ProtectedRoute>
            }
          />
          <Route
            path="billing/invoices"
            element={
              <ProtectedRoute allowedRoles={['admin', 'zev_owner']}>
                <InvoicesPage />
              </ProtectedRoute>
            }
          />
          <Route path="billing/invoices/:invoiceId" element={<InvoiceDetailPage />} />
          <Route path="billing" element={<AliasNavigate to="/billing/invoices" />} />
          <Route path="invoices" element={<AliasNavigate to="/billing/invoices" />} />
          <Route path="invoices/:invoiceId" element={<InvoiceDetailAlias />} />
          <Route
            path="me/statement"
            element={
              <ProtectedRoute allowedRoles={['participant']}>
                <ReportsPage />
              </ProtectedRoute>
            }
          />
          {/* Recorded exception 2 (spec §4): participant's own invoices — reuses
              the existing role-scoped backend list, no new grant. */}
          <Route
            path="me/invoices"
            element={
              <ProtectedRoute allowedRoles={['participant']}>
                <MyInvoicesPage />
              </ProtectedRoute>
            }
          />
          <Route
            path="reports"
            element={
              <ProtectedRoute allowedRoles={['admin', 'zev_owner', 'participant']}>
                <ReportsPage />
              </ProtectedRoute>
            }
          />
          <Route
            path="feasibility"
            element={
              <ProtectedRoute allowedRoles={['admin', 'zev_owner']}>
                <FeasibilityCalculatorPage />
              </ProtectedRoute>
            }
          />
          <Route path="imports" element={<AliasNavigate to="/metering/imports" />} />
          <Route
            path="metering/imports"
            element={
              <ProtectedRoute allowedRoles={['admin', 'zev_owner']}>
                <ImportsPage />
              </ProtectedRoute>
            }
          />
        </Route>
        <Route path="*" element={<NotFoundPage />} />
      </Routes>
    </Suspense>
  )
}
