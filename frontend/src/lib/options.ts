export const BILLING_INTERVAL_OPTIONS = [
    { value: 'monthly', labelKey: 'pages.zevs.billingIntervals.monthly' },
    { value: 'quarterly', labelKey: 'pages.zevs.billingIntervals.quarterly' },
    { value: 'semi_annual', labelKey: 'pages.zevs.billingIntervals.semi_annual' },
    { value: 'annual', labelKey: 'pages.zevs.billingIntervals.annual' },
] as const

export const ZEV_TYPE_OPTIONS = [
    { value: 'zev', labelKey: 'pages.zevs.zevTypes.zev' },
    { value: 'vzev', labelKey: 'pages.zevs.zevTypes.vzev' },
] as const

export const METER_TYPE_OPTIONS = [
    { value: 'consumption', labelKey: 'pages.meteringPoints.meterTypes.consumption' },
    { value: 'production', labelKey: 'pages.meteringPoints.meterTypes.production' },
    { value: 'bidirectional', labelKey: 'pages.meteringPoints.meterTypes.bidirectional' },
] as const
