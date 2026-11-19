import { Fragment, useMemo, useRef, useState, type ComponentPropsWithRef, type ReactNode } from 'react'
import { Menu } from '@mantine/core'
import { ActionTooltip } from './ActionTooltip'
import { closePopupOnEscape } from '../lib/popupKeyboard'

export interface ActionMenuItem {
    key: string
    label: string
    icon?: ReactNode
    /** Name when rendered as a lone icon button. */
    iconButtonLabel?: string
    onClick: () => void
    disabled?: boolean
    danger?: boolean
    section?: string
}

interface ActionMenuProps {
    label: string
    items: ActionMenuItem[]
    icon?: ReactNode
    iconOnly?: boolean
    /** Row-level size by default; `false` for a page toolbar, beside full-size buttons. */
    compact?: boolean
    /** Lets the caller find the trigger again, to return focus once a form it opened closes. */
    actionKey?: string
}

function ActionTrigger({ direct, ...props }: ComponentPropsWithRef<'button'> & { direct: boolean }) {
    return (
        <button
            {...props}
            aria-haspopup={direct ? undefined : props['aria-haspopup']}
            aria-expanded={direct ? undefined : props['aria-expanded']}
            aria-controls={direct ? undefined : props['aria-controls']}
        />
    )
}

export function ActionMenu({ label, items, icon, iconOnly = false, compact = true, actionKey }: ActionMenuProps) {
    const triggerRef = useRef<HTMLButtonElement>(null)
    const availableItems = useMemo(() => items.filter((item) => !item.disabled), [items])
    const renderedItems = useMemo(() => {
        return items.map((item, index) => {
            const previousSection = index > 0 ? items[index - 1]?.section : undefined
            const showSection = item.section && item.section !== previousSection

            return {
                item,
                showSection,
                showDivider: index > 0 && showSection,
            }
        })
    }, [items])

    // Keep the trigger mounted when a refresh turns a menu into a direct action.
    const single = iconOnly && items.length === 1 ? items[0] : undefined
    const iconLabel = single?.icon ? single.iconButtonLabel : undefined
    const onlyIcon = single ? !!iconLabel : iconOnly
    const buttonIcon = single ? single.icon : icon
    const disabled = single ? single.disabled : availableItems.length === 0
    const [opened, setOpened] = useState(false)
    if (single && opened) setOpened(false)
    const tooltip = onlyIcon ? (single ? iconLabel : label) : undefined

    // Capture on the trigger so an open menu takes precedence over its tooltip.
    return (
        <Menu
            opened={!single && opened}
            onChange={next => setOpened(!single && next)}
            position="bottom-end"
            withinPortal
            shadow="md"
            middlewares={{ size: true }}
            transitionProps={{ transition: 'pop-top-right' }}
        >
            <ActionTooltip label={tooltip} disabled={disabled}>
                <Menu.Target>
                    <ActionTrigger
                        direct={!!single}
                        ref={triggerRef}
                        type="button"
                        className={`button button-secondary${compact ? ' button-compact' : ''}${single?.danger ? ' button-destructive' : ''}${onlyIcon ? ' button-icon' : ''}`}
                        disabled={disabled}
                        data-action-key={actionKey}
                        onKeyDownCapture={single ? undefined : closePopupOnEscape}
                        aria-label={tooltip}
                        onClick={single ? () => {
                            // Pointer activation does not focus a button in every browser.
                            triggerRef.current?.focus()
                            single.onClick()
                        } : undefined}
                    >
                        {buttonIcon ? <span className="menu-item-icon" aria-hidden="true">{buttonIcon}</span> : null}
                        {onlyIcon ? null : single?.label ?? label}
                    </ActionTrigger>
                </Menu.Target>
            </ActionTooltip>
            {!single && <Menu.Dropdown className="action-menu-dropdown">
                {renderedItems.map(({ item, showSection, showDivider }) => (
                    <Fragment key={item.key}>
                        {showDivider && <Menu.Divider />}
                        {showSection && <Menu.Label>{item.section}</Menu.Label>}
                        <Menu.Item
                            disabled={item.disabled}
                            leftSection={item.icon ? <span className="menu-item-icon" aria-hidden="true">{item.icon}</span> : undefined}
                            className={item.danger ? 'action-menu-item-danger' : undefined}
                            onClick={() => {
                                // The menu unmounts with the focused item, so a dialog opened from it
                                // would remember nothing to return to; hand focus to the trigger first.
                                triggerRef.current?.focus()
                                item.onClick()
                            }}
                        >
                            {item.label}
                        </Menu.Item>
                    </Fragment>
                ))}
            </Menu.Dropdown>}
        </Menu>
    )
}
