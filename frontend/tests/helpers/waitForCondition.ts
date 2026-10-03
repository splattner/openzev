import { act } from 'react'

export async function waitForCondition(predicate: () => boolean, label: string, timeout = 1000) {
    const deadline = Date.now() + timeout
    while (!predicate() && Date.now() < deadline) {
        await act(async () => { await new Promise((resolve) => setTimeout(resolve, 25)) })
    }
    if (!predicate()) {
        throw new Error(`timed out waiting for ${label}`)
    }
}
