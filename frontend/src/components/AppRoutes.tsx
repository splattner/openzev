import { Suspense, lazy } from 'react'
import { Route, Routes } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { Layout } from './Layout'
import { ProtectedRoute } from './ProtectedRoute'
import { AliasNavigate, InvoiceDetailAlias, MeteringDataAlias } from './RouteAliases'
import { PageSkeleton } from './PageSkeleton'
import { ManagedZevProvider } from '../lib/managedZev'

const AccountProfilePage = lazy(async () => ({ default: (await import('../pages/AccountProfilePage')).AccountProfilePage }))
const AdminOverviewHubPage = lazy(async () => ({ default: (await import('../pages/AdminOverviewHubPage')).AdminOverviewHubPage }))
const AdminAccountsHubPage = lazy(async () => ({ default: (await import('../pages/AdminAccountsHubPage')).AdminAccountsHubPage }))
const AdminTemplatesHubPage = lazy(async () => ({ default: (await import('../pages/AdminTemplatesHubPage')).AdminTemplatesHubPage }))
const BillingHubPage = lazy(async () => ({ default: (await import('../pages/BillingHubPage')).BillingHubPage }))
const FeasibilityCalculatorPage = lazy(async () => ({ default: (await import('../pages/FeasibilityCalculatorPage')).FeasibilityCalculatorPage }))
const AdminSystemSettingsPage = lazy(async () => ({ default: (await import('../pages/AdminSystemSettingsPage')).AdminSystemSettingsPage }))
const DashboardPage = lazy(async () => ({ default: (await import('../pages/DashboardPage')).DashboardPage }))
const HomePage = lazy(async () => ({ default: (await import('../pages/HomePage')).HomePage }))
const ReportsPage = lazy(async () => ({ default: (await import('../pages/ReportsPage')).ReportsPage }))
const InvoiceDetailPage = lazy(async () => ({ default: (await import('../pages/InvoiceDetailPage')).InvoiceDetailPage }))
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
const ZevSettingsTabRoute = lazy(async () => ({ default: (await import('../pages/ZevSettingsPage')).ZevSettingsTabRoute }))
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
          <Route index element={<HomePage />} />
          <Route path="dashboard" element={<DashboardPage />} />
          <Route path="account" element={<AccountProfilePage />} />
          {/* Admin console (nav-regroup phase 3): four hub pages with
              tab-as-route. Legacy /admin/* URLs redirect into the matching
              hub tab so deep links keep working. */}
          <Route
            path="admin"
            element={
              <ProtectedRoute allowedRoles={['admin']}>
                <AdminOverviewHubPage />
              </ProtectedRoute>
            }
          />
          {(['overview', 'zevs', 'invoices', 'audit', 'health'] as const).map((adminTab) => (
            <Route
              key={adminTab}
              path={`admin/${adminTab}`}
              element={
                <ProtectedRoute allowedRoles={['admin']}>
                  <AdminOverviewHubPage tab={adminTab} />
                </ProtectedRoute>
              }
            />
          ))}
          <Route
            path="admin/accounts"
            element={
              <ProtectedRoute allowedRoles={['admin']}>
                <AdminAccountsHubPage />
              </ProtectedRoute>
            }
          />
          {(['users', 'api-keys'] as const).map((accountsTab) => (
            <Route
              key={accountsTab}
              path={`admin/accounts/${accountsTab === 'api-keys' ? 'api-keys' : 'users'}`}
              element={
                <ProtectedRoute allowedRoles={['admin']}>
                  <AdminAccountsHubPage tab={accountsTab} />
                </ProtectedRoute>
              }
            />
          ))}
          <Route path="admin/api-keys" element={<AliasNavigate to="/admin/accounts/api-keys" />} />
          <Route
            path="admin/templates"
            element={
              <ProtectedRoute allowedRoles={['admin']}>
                <AdminTemplatesHubPage />
              </ProtectedRoute>
            }
          />
          {(['pdf', 'email'] as const).map((templatesTab) => (
            <Route
              key={templatesTab}
              path={`admin/templates/${templatesTab}`}
              element={
                <ProtectedRoute allowedRoles={['admin']}>
                  <AdminTemplatesHubPage tab={templatesTab} />
                </ProtectedRoute>
              }
            />
          ))}
          <Route path="admin/pdf-templates" element={<AliasNavigate to="/admin/templates/pdf" />} />
          <Route path="admin/email-templates" element={<AliasNavigate to="/admin/templates/email" />} />
          {/* Legacy audit-log deep link → admin Overview audit tab. */}
          <Route path="admin/audit-logs" element={<AliasNavigate to="/admin/audit" />} />
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
          <Route path="admin/features" element={<AliasNavigate to="/admin/system-settings?tab=features" />} />
          <Route path="admin/oauth" element={<AliasNavigate to="/admin/system-settings?tab=oauth" />} />
          <Route
            path="participants"
            element={
              <ProtectedRoute allowedRoles={['admin', 'zev_owner']}>
                <ParticipantsPage />
              </ProtectedRoute>
            }
          />
          {/* ZEV settings hub (phase 3): tabs are sub-routes; /zev-settings
              renders the first tab. */}
          <Route
            path="zev-settings"
            element={
              <ProtectedRoute allowedRoles={['admin', 'zev_owner']}>
                <ZevSettingsTabRoute />
              </ProtectedRoute>
            }
          />
          <Route
            path="zev-settings/:tab"
            element={
              <ProtectedRoute allowedRoles={['admin', 'zev_owner']}>
                <ZevSettingsTabRoute />
              </ProtectedRoute>
            }
          />
          {/* Phase-3 canonical route for metering points; legacy
              /metering-points stays as an alias. Participants keep deep-link
              access (default-allow, read-only, never gated on canManage). */}
          <Route path="metering/points" element={<MeteringPointsPage />} />
          <Route path="metering-points" element={<AliasNavigate to="/metering/points" />} />
          {/* Keep identical wrappers so tab navigation preserves page state. */}
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
          {/* Period work now lives on the manager Overview. Keep the former
              tab URL as a guarded compatibility redirect. */}
          <Route
            path="billing/periods"
            element={
              <ProtectedRoute allowedRoles={['admin', 'zev_owner']}>
                <AliasNavigate to="/" />
              </ProtectedRoute>
            }
          />
          <Route
            path="billing/invoices"
            element={
              <ProtectedRoute allowedRoles={['admin', 'zev_owner']}>
                <BillingHubPage tab="invoices" />
              </ProtectedRoute>
            }
          />
          <Route
            path="billing/emails"
            element={
              <ProtectedRoute allowedRoles={['admin', 'zev_owner']}>
                <BillingHubPage tab="emails" />
              </ProtectedRoute>
            }
          />
          <Route
            path="billing/statements"
            element={
              <ProtectedRoute allowedRoles={['admin', 'zev_owner']}>
                <BillingHubPage tab="statements" />
              </ProtectedRoute>
            }
          />
          <Route path="billing/invoices/:invoiceId" element={<InvoiceDetailPage />} />
          <Route path="billing" element={<AliasNavigate to="/billing/invoices" />} />
          <Route path="invoices" element={<AliasNavigate to="/billing/invoices" />} />
          <Route path="invoices/:invoiceId" element={<InvoiceDetailAlias />} />
          {/* Audit log moved into the hubs (phase 3): the ZEV log is a
              ZEV-settings tab, the platform log an admin Overview tab.
              Legacy URLs redirect so deep links keep working. */}
          <Route path="audit-logs" element={<AliasNavigate to="/zev-settings/audit" />} />
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
          {/* Import history is a Metering-hub tab (phase 3); the same route
              renders the hub shell so tab state stays consistent. */}
          <Route
            path="metering/imports"
            element={
              <ProtectedRoute allowedRoles={['admin', 'zev_owner']}>
                <MeteringChartPage tab="imports" />
              </ProtectedRoute>
            }
          />
        </Route>
        <Route path="*" element={<NotFoundPage />} />
      </Routes>
    </Suspense>
  )
}
