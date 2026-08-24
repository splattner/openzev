import { Fragment, useMemo, type ReactNode } from 'react'
import { Menu } from '@mantine/core'

export interface ActionMenuItem {
    key: string
    label: string
    icon?: ReactNode
    onClick: () => void
    disabled?: boolean
    danger?: boolean
    section?: string
}

interface ActionMenuProps {
    label: string
    items: ActionMenuItem[]
    buttonClassName?: string
    icon?: ReactNode
}

export function ActionMenu({ label, items, buttonClassName = 'button button-secondary button-compact', icon }: ActionMenuProps) {
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

    return (
        <Menu
            position="bottom-end"
            withinPortal
            shadow="md"
            transitionProps={{ transition: 'pop-top-right' }}
        >
            <Menu.Target>
                <button
                    type="button"
                    className={buttonClassName}
                    disabled={availableItems.length === 0}
                    aria-haspopup="menu"
                >
                    {icon ? <span className="menu-item-icon" aria-hidden="true">{icon}</span> : null}
                    {label}
                </button>
            </Menu.Target>
            <Menu.Dropdown>
                {renderedItems.map(({ item, showSection, showDivider }) => (
                    <Fragment key={item.key}>
                        {showDivider && <Menu.Divider />}
                        {showSection && <Menu.Label>{item.section}</Menu.Label>}
                        <Menu.Item
                            disabled={item.disabled}
                            leftSection={item.icon ? <span className="menu-item-icon" aria-hidden="true">{item.icon}</span> : undefined}
                            className={item.danger ? 'action-menu-item-danger' : undefined}
                            onClick={item.onClick}
                        >
                            {item.label}
                        </Menu.Item>
                    </Fragment>
                ))}
            </Menu.Dropdown>
        </Menu>
    )
}
