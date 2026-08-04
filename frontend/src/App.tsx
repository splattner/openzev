import { Suspense, lazy } from 'react'
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import { Layout } from './components/Layout'
import { ProtectedRoute } from './components/ProtectedRoute'
import { ManagedZevProvider } from './lib/managedZev'

const AccountProfilePage = lazy(async () => ({ default: (await import('./pages/AccountProfilePage')).AccountProfilePage }))
const AdminDashboardPage = lazy(async () => ({ default: (await import('./pages/AdminDashboardPage')).AdminDashboardPage }))
const AdminAccountsPage = lazy(async () => ({ default: (await import('./pages/AdminAccountsPage')).AdminAccountsPage }))
const AdminApiKeysPage = lazy(async () => ({ default: (await import('./pages/AdminApiKeysPage')).AdminApiKeysPage }))
const AdminPdfTemplatesPage = lazy(async () => ({ default: (await import('./pages/AdminPdfTemplatesPage')).AdminPdfTemplatesPage }))
const AdminEmailTemplatesPage = lazy(async () => ({ default: (await import('./pages/AdminEmailTemplatesPage')).AdminEmailTemplatesPage }))
const AdminInvoicesPage = lazy(async () => ({ default: (await import('./pages/AdminInvoicesPage')).AdminInvoicesPage }))
const FeasibilityCalculatorPage = lazy(async () => ({ default: (await import('./pages/FeasibilityCalculatorPage')).FeasibilityCalculatorPage }))
const AuditLogsPage = lazy(async () => ({ default: (await import('./pages/AdminAuditLogsPage')).AuditLogsPage }))
const AdminSystemSettingsPage = lazy(async () => ({ default: (await import('./pages/AdminSystemSettingsPage')).AdminSystemSettingsPage }))
const AdminVatSettingsPage = lazy(async () => ({ default: (await import('./pages/AdminVatSettingsPage')).AdminVatSettingsPage }))
const DashboardPage = lazy(async () => ({ default: (await import('./pages/DashboardPage')).DashboardPage }))
const ImportsPage = lazy(async () => ({ default: (await import('./pages/ImportsPage')).ImportsPage }))
const InvoiceDetailPage = lazy(async () => ({ default: (await import('./pages/InvoiceDetailPage')).InvoiceDetailPage }))
const InvoicesPage = lazy(async () => ({ default: (await import('./pages/InvoicesPage')).InvoicesPage }))
const LoginPage = lazy(async () => ({ default: (await import('./pages/LoginPage')).LoginPage }))
const MeteringChartPage = lazy(async () => ({ default: (await import('./pages/MeteringChartPage')).MeteringChartPage }))
const MeteringPointsPage = lazy(async () => ({ default: (await import('./pages/MeteringPointsPage')).MeteringPointsPage }))
const NotFoundPage = lazy(async () => ({ default: (await import('./pages/NotFoundPage')).NotFoundPage }))
const ParticipantsPage = lazy(async () => ({ default: (await import('./pages/ParticipantsPage')).ParticipantsPage }))
const TariffsPage = lazy(async () => ({ default: (await import('./pages/TariffsPage')).TariffsPage }))
const VerifyEmailPage = lazy(async () => ({ default: (await import('./pages/VerifyEmailPage')).VerifyEmailPage }))
const ZevListPage = lazy(async () => ({ default: (await import('./pages/ZevListPage')).ZevListPage }))
const ZevSettingsPage = lazy(async () => ({ default: (await import('./pages/ZevSettingsPage')).ZevSettingsPage }))
const OAuthCallbackPage = lazy(async () => ({ default: (await import('./pages/OAuthCallbackPage')).OAuthCallbackPage }))

function RouteFallback() {
  return <div className="app-route-loading">Loading...</div>
}

function App() {
  return (
    <BrowserRouter>
      <Suspense fallback={<RouteFallback />}>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route path="/verify-email" element={<VerifyEmailPage />} />
          <Route path="/oauth/callback" element={<OAuthCallbackPage />} />
          <Route
            path="/"
            element={
              <ProtectedRoute>
                <ManagedZevProvider>
                  <Layout />
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
            <Route path="admin/settings/regional" element={<Navigate to="/admin/system-settings?tab=regional" replace />} />
            <Route
              path="admin/settings/vat"
              element={
                <ProtectedRoute allowedRoles={['admin']}>
                  <AdminVatSettingsPage />
                </ProtectedRoute>
              }
            />
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
            <Route path="admin/features" element={<Navigate to="/admin/system-settings?tab=features" replace />} />
            <Route path="admin/oauth" element={<Navigate to="/admin/system-settings?tab=oauth" replace />} />
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
            <Route path="metering-data" element={<MeteringChartPage />} />
            <Route
              path="tariffs"
              element={
                <ProtectedRoute allowedRoles={['admin', 'zev_owner']}>
                  <TariffsPage />
                </ProtectedRoute>
              }
            />
            <Route
              path="invoices"
              element={
                <ProtectedRoute allowedRoles={['admin', 'zev_owner']}>
                  <InvoicesPage />
                </ProtectedRoute>
              }
            />
            <Route path="invoices/:invoiceId" element={<InvoiceDetailPage />} />
            <Route
              path="feasibility"
              element={
                <ProtectedRoute allowedRoles={['admin', 'zev_owner']}>
                  <FeasibilityCalculatorPage />
                </ProtectedRoute>
              }
            />
            <Route
              path="imports"
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
    </BrowserRouter>
  )
}

export default App
