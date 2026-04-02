import { BrowserRouter, Route, Routes } from 'react-router-dom'
import { Layout } from './components/Layout'
import { ProtectedRoute } from './components/ProtectedRoute'
import { ManagedZevProvider } from './lib/managedZev'
import { AccountProfilePage } from './pages/AccountProfilePage'
import { AdminDashboardPage } from './pages/AdminDashboardPage'
import { AdminAccountsPage } from './pages/AdminAccountsPage'
import { AdminPdfTemplatesPage } from './pages/AdminPdfTemplatesPage'
import { AdminEmailTemplatesPage } from './pages/AdminEmailTemplatesPage'
import { AdminFeaturesPage } from './pages/AdminFeaturesPage'
import { AdminInvoicesPage } from './pages/AdminInvoicesPage'
import { AdminRegionalSettingsPage } from './pages/AdminRegionalSettingsPage'
import { AdminVatSettingsPage } from './pages/AdminVatSettingsPage'
import { DashboardPage } from './pages/DashboardPage'
import { ImportsPage } from './pages/ImportsPage'
import { InvoiceDetailPage } from './pages/InvoiceDetailPage'
import { InvoicesPage } from './pages/InvoicesPage'
import { LoginPage } from './pages/LoginPage'
import { MeteringChartPage } from './pages/MeteringChartPage'
import { MeteringPointsPage } from './pages/MeteringPointsPage'
import { NotFoundPage } from './pages/NotFoundPage'
import { ParticipantsPage } from './pages/ParticipantsPage'
import { TariffsPage } from './pages/TariffsPage'
import { VerifyEmailPage } from './pages/VerifyEmailPage'
import { ZevListPage } from './pages/ZevListPage'
import { ZevSettingsPage } from './pages/ZevSettingsPage'

function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route path="/verify-email" element={<VerifyEmailPage />} />
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
            path="admin/settings/regional"
            element={
              <ProtectedRoute allowedRoles={['admin']}>
                <AdminRegionalSettingsPage />
              </ProtectedRoute>
            }
          />
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
          <Route
            path="admin/features"
            element={
              <ProtectedRoute allowedRoles={['admin']}>
                <AdminFeaturesPage />
              </ProtectedRoute>
            }
          />
          <Route
            path="admin/invoices"
            element={
              <ProtectedRoute allowedRoles={['admin']}>
                <AdminInvoicesPage />
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
    </BrowserRouter>
  )
}

export default App
