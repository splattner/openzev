import { createContext, type RefCallback } from 'react'

// The selected community page can offer an in-flow home for the shell's desktop bell.
export const NotificationBellSlot = createContext<RefCallback<HTMLDivElement> | null>(null)
