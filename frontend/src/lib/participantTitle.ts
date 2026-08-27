import type { TFunction } from 'i18next'

export const TITLE_KEYS = ['mr', 'mrs', 'ms', 'dr', 'prof'] as const
export type TitleKey = (typeof TITLE_KEYS)[number]

export function getTitleLabelMap(t: TFunction): Record<TitleKey, string> {
    return Object.fromEntries(TITLE_KEYS.map((k) => [k, t(`pages.zevs.titles.${k}`)])) as Record<TitleKey, string>
}
