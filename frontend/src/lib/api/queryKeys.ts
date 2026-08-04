export const queryKeys = {
  auth: {
    me: () => ['auth', 'me'] as const,
    appSettings: () => ['auth', 'app-settings'] as const,
    users: () => ['auth', 'users'] as const,
    featureFlags: () => ['auth', 'feature-flags'] as const,
    registrationEnabled: () => ['auth', 'registration-enabled'] as const,
    vatRates: () => ['auth', 'vat-rates'] as const,
    oauthProviders: () => ['auth', 'oauth-providers'] as const,
    socialAccounts: () => ['auth', 'social-accounts'] as const,
    apiKeys: () => ['auth', 'api-keys'] as const,
    allApiKeys: (user?: number | '', status?: string) => ['auth', 'all-api-keys', user ?? '', status ?? ''] as const,
    oauthProviderConfigs: () => ['auth', 'oauth-provider-configs'] as const,
  },
  zev: {
    list: () => ['zev', 'list'] as const,
    participants: (zevId?: string) => ['zev', 'participants', zevId ?? 'all'] as const,
    meteringPoints: (zevId?: string) => ['zev', 'metering-points', zevId ?? 'all'] as const,
    transferSections: () => ['zev', 'transfer-sections'] as const,
  },
  tariffs: {
    list: (zevId?: string) => ['tariffs', 'list', zevId ?? 'all'] as const,
    periods: () => ['tariffs', 'periods'] as const,
    series: (zevId?: string) => ['tariffs', 'series', zevId ?? 'all'] as const,
  },
  invoices: {
    list: (zevId?: string) => ['invoices', 'list', zevId ?? 'all'] as const,
    detail: (invoiceId: string) => ['invoices', 'detail', invoiceId] as const,
    dashboard: () => ['invoices', 'dashboard'] as const,
    periodOverview: (zevId: string, periodStart: string, periodEnd: string) =>
      ['invoices', 'period-overview', zevId, periodStart, periodEnd] as const,
  },
  admin: {
    emailTemplate: (templateKey: string) => ['admin', 'email-template', templateKey] as const,
    invoicePdfTemplate: () => ['admin', 'pdf-template', 'invoice'] as const,
    contractPdfTemplate: () => ['admin', 'pdf-template', 'contract'] as const,
    annualStatementPdfTemplate: () => ['admin', 'pdf-template', 'annual-statement'] as const,
    auditEvents: (filters?: unknown) => ['admin', 'audit-events', filters ?? {}] as const,
    auditEvent: (eventId: string) => ['admin', 'audit-event', eventId] as const,
  },
  metering: {
    points: (zevId?: string) => ['metering', 'points', zevId ?? 'all'] as const,
    pointAssignments: (meteringPointId?: string) => ['metering', 'point-assignments', meteringPointId ?? 'all'] as const,
    importLogs: () => ['metering', 'import-logs'] as const,
    chartData: (meteringPointId: string, dateFrom: string, dateTo: string, bucket: 'day' | 'hour' | 'month') =>
      ['metering', 'chart-data', meteringPointId, dateFrom, dateTo, bucket] as const,
    rawData: (meteringPointId: string, dateFrom: string, dateTo: string) =>
      ['metering', 'raw-data', meteringPointId, dateFrom, dateTo] as const,
    rawDay: (meteringPointId: string, date: string) =>
      ['metering', 'raw-day', meteringPointId, date] as const,
    dashboardSummary: (params: Record<string, string | undefined>) => ['metering', 'dashboard-summary', params] as const,
    qualityStatus: (dateFrom: string, dateTo: string, zevId?: string, meteringPointId?: string) =>
      ['metering', 'quality-status', dateFrom, dateTo, zevId ?? 'all', meteringPointId ?? 'all'] as const,
    hourlyProfile: (dateFrom: string, dateTo: string, zevId?: string, participantId?: string) =>
      ['metering', 'hourly-profile', dateFrom, dateTo, zevId ?? 'all', participantId ?? 'all'] as const,
  },
}
