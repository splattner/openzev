import { Fragment, type MouseEvent, type ReactNode, useMemo, useState } from 'react'
import { Divider, ListSubheader, Menu, MenuItem } from '@mui/material'

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
    const [anchorEl, setAnchorEl] = useState<HTMLElement | null>(null)
    const open = Boolean(anchorEl)
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

    function handleOpen(event: MouseEvent<HTMLButtonElement>) {
        setAnchorEl(event.currentTarget)
    }

    function handleClose() {
        setAnchorEl(null)
    }

    return (
        <>
            <button
                type="button"
                className={buttonClassName}
                onClick={handleOpen}
                disabled={availableItems.length === 0}
                aria-haspopup="menu"
                aria-expanded={open ? 'true' : undefined}
            >
                {icon ? <span className="button-icon" aria-hidden="true">{icon}</span> : null}
                {label}
            </button>
            <Menu
                anchorEl={anchorEl}
                open={open}
                onClose={handleClose}
                anchorOrigin={{ vertical: 'bottom', horizontal: 'right' }}
                transformOrigin={{ vertical: 'top', horizontal: 'right' }}
            >
                {renderedItems.map(({ item, showSection, showDivider }) => (
                    <Fragment key={item.key}>
                        {showDivider && <Divider />}
                        {showSection && (
                            <ListSubheader
                                disableSticky
                                sx={{ lineHeight: 1.8, fontSize: '0.72rem', fontWeight: 700, color: '#64748b' }}
                            >
                                {item.section}
                            </ListSubheader>
                        )}
                        <MenuItem
                            disabled={item.disabled}
                            onClick={() => {
                                handleClose()
                                item.onClick()
                            }}
                            sx={item.danger ? { color: '#b91c1c' } : undefined}
                        >
                            {item.icon ? <span className="menu-item-icon" aria-hidden="true">{item.icon}</span> : null}
                            {item.label}
                        </MenuItem>
                    </Fragment>
                ))}
            </Menu>
        </>
    )
}