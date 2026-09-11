export const queryKeys = {
  auth: {
    me: () => ['auth', 'me'] as const,
    appSettings: () => ['auth', 'app-settings'] as const,
    systemHealth: () => ['auth', 'system-health'] as const,
    users: () => ['auth', 'users'] as const,
    featureFlags: () => ['auth', 'feature-flags'] as const,
    registrationEnabled: () => ['auth', 'registration-enabled'] as const,
    vatRates: () => ['auth', 'vat-rates'] as const,
    oauthProviders: () => ['auth', 'oauth-providers'] as const,
    socialAccounts: () => ['auth', 'social-accounts'] as const,
    apiKeys: () => ['auth', 'api-keys'] as const,
    allApiKeysRoot: ['auth', 'all-api-keys'] as const,
    allApiKeys: (user?: number | '', status?: string) => [...queryKeys.auth.allApiKeysRoot, user ?? '', status ?? ''] as const,
    oauthProviderConfigs: () => ['auth', 'oauth-provider-configs'] as const,
  },
  zev: {
    list: () => ['zev', 'list'] as const,
    participants: (zevId?: string) => ['zev', 'participants', zevId ?? 'all'] as const,
    transferSections: () => ['zev', 'transfer-sections'] as const,
    gridOperators: () => ['zev', 'grid-operators'] as const,
    gridOperatorSuggestions: (postalCode: string) => ['zev', 'grid-operators', 'suggest', postalCode] as const,
  },
  tariffs: {
    series: (zevId?: string) => ['tariffs', 'series', zevId ?? 'all'] as const,
    // Global, not per-ZEV: every community's tariff form reads the same list.
    dynamicSources: () => ['tariffs', 'dynamic-sources'] as const,
    dynamicPrices: (sourceId: string, dateFrom: string, dateTo: string) =>
      ['tariffs', 'dynamic-sources', sourceId, 'prices', dateFrom, dateTo] as const,
  },
  feasibility: {
    enabled: () => ['feasibility', 'enabled'] as const,
  },
  invoices: {
    lists: () => ['invoices', 'list'] as const,
    list: (zevId?: string, status?: string) => ['invoices', 'list', zevId ?? 'all', status ?? 'all'] as const,
    mine: () => ['invoices', 'mine'] as const,
    detail: (invoiceId: string) => ['invoices', 'detail', invoiceId] as const,
    dashboard: () => ['invoices', 'dashboard'] as const,
    periodOverview: (zevId: string, periodStart: string, periodEnd: string) =>
      ['invoices', 'period-overview', zevId, periodStart, periodEnd] as const,
    readiness: (zevId?: string) => ['invoices', 'readiness', zevId ?? 'all'] as const,
    readinessList: (zevId?: string) => ['invoices', 'readiness-list', zevId ?? 'all'] as const,
    attention: (zevId?: string) => ['invoices', 'attention', zevId ?? 'all'] as const,
  },
  admin: {
    emailTemplate: (templateKey: string) => ['admin', 'email-template', templateKey] as const,
    invoicePdfTemplate: () => ['admin', 'pdf-template', 'invoice'] as const,
    contractPdfTemplate: () => ['admin', 'pdf-template', 'contract'] as const,
    annualStatementPdfTemplate: () => ['admin', 'pdf-template', 'annual-statement'] as const,
    auditEvents: (filters?: unknown) => ['admin', 'audit-events', filters ?? {}] as const,
    auditEvent: (eventId: string) => ['admin', 'audit-event', eventId] as const,
    auditFilterOptions: () => ['admin', 'audit-events', 'filter-options'] as const,
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
