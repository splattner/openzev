import { act } from 'react'

/** Shared async-test helpers for the PDF preview suites. */
export function deferred<T>() {
    let resolve!: (value: T | PromiseLike<T>) => void
    let reject!: (reason?: unknown) => void
    const promise = new Promise<T>((resolvePromise, rejectPromise) => {
        resolve = resolvePromise
        reject = rejectPromise
    })
    return { promise, resolve, reject }
}

export function pdfBlob(type = 'application/pdf') {
    return new Blob(['pdf'], { type })
}

export async function flush() {
    await act(async () => {
        await new Promise((resolve) => setTimeout(resolve, 0))
    })
}
