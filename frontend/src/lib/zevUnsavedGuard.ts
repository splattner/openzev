/**
 * Unsaved state the community switcher asks about: a dirty ZEV settings draft,
 * or a tariff form with unsaved changes or a save in flight. One publisher at
 * a time: each page sets it while mounted and clears it on unmount.
 */
let hasUnsavedZevDraft = false

export function setZevUnsavedDraftGuard(isDirty: boolean): void {
    hasUnsavedZevDraft = isDirty
}

export function hasUnsavedZevSettingsDraft(): boolean {
    return hasUnsavedZevDraft
}
