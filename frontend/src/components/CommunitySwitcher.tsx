import type { ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { Menu } from '@mantine/core'
import { useTranslation } from 'react-i18next'
import { useOptionalManagedZev } from '../lib/managedZev'
import { hasUnsavedZevSettingsDraft } from '../lib/zevUnsavedGuard'
import { ConfirmDialog, useConfirmDialog } from './ConfirmDialog'

/**
 * The page's scope line, as the place to change community: the name above
 * the title opens the list of the account's communities. With one community
 * (or none) there is nothing to choose, and the name stays plain text.
 */
export function CommunitySwitcher({ name }: { name: ReactNode }) {
    const managedZev = useOptionalManagedZev()
    if (!managedZev || (managedZev.entries ?? []).length < 2) {
        return <>{name}</>
    }
    return <CommunityMenu name={name} managedZev={managedZev} />
}

function CommunityMenu({ name, managedZev }: {
    name: ReactNode
    managedZev: NonNullable<ReturnType<typeof useOptionalManagedZev>>
}) {
    const { t } = useTranslation()
    const { dialog, confirm, handleConfirm, handleCancel } = useConfirmDialog()
    const { entries, selectedZevId, isSelectable, setSelectedZevId } = managedZev
    const currentName = entries.find((entry) => entry.id === selectedZevId)?.name

    // A dirty settings draft lives in ZevSettingsPage; confirm before the
    // switch drops it. Clean switches go through immediately.
    function requestSwitch(zevId: string) {
        if (zevId === selectedZevId) {
            return
        }
        if (!hasUnsavedZevSettingsDraft()) {
            setSelectedZevId(zevId)
            return
        }
        confirm({
            title: t('pages.zevSettings.unsavedGuardTitle'),
            message: t('pages.zevSettings.unsavedGuardSwitchMessage'),
            confirmText: t('pages.zevSettings.switchWithoutSaving'),
            onConfirm: () => {
                setSelectedZevId(zevId)
            },
        })
    }

    return (
        <>
            <Menu position="bottom-start" withinPortal shadow="md" offset={6}>
                <Menu.Target>
                    <button
                        type="button"
                        className="community-switch"
                        aria-label={currentName ? t('nav.chooseZevCurrent', { name: currentName }) : t('nav.chooseZev')}
                        title={t('nav.chooseZev')}
                    >
                        <span className="community-switch-name">{name}</span>
                        <svg className="community-switch-caret" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                            <path d="m6 9 6 6 6-6" />
                        </svg>
                    </button>
                </Menu.Target>
                <Menu.Dropdown className="community-menu">
                    {entries.map((entry) => {
                        const isCurrent = entry.id === selectedZevId
                        return (
                            <Menu.Item
                                key={entry.id}
                                className={`community-menu-item${isCurrent ? ' is-current' : ''}`}
                                aria-current={isCurrent ? 'true' : undefined}
                                disabled={!isSelectable && !isCurrent}
                                onClick={() => {
                                    if (isSelectable) {
                                        requestSwitch(entry.id)
                                    }
                                }}
                                rightSection={isCurrent ? <CheckIcon /> : null}
                            >
                                <span className="community-menu-name">{entry.name}</span>
                                {entry.relation !== 'admin' && (
                                    <small className="community-menu-relation">{t(`nav.relation.${entry.relation}`)}</small>
                                )}
                            </Menu.Item>
                        )
                    })}
                </Menu.Dropdown>
            </Menu>
            {/* The switcher sits in the scope line's paragraph; the dialog
                cannot nest there. */}
            {dialog && createPortal(
                <ConfirmDialog
                    {...dialog}
                    onConfirm={handleConfirm}
                    onCancel={handleCancel}
                />,
                document.body,
            )}
        </>
    )
}

function CheckIcon() {
    return (
        <svg className="community-menu-check" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            <path d="M20 6 9 17l-5-5" />
        </svg>
    )
}
