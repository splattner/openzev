// Enable React's act() environment; provide Mantine's missing matchMedia.
globalThis.IS_REACT_ACT_ENVIRONMENT = true

// Unconditional shared mock returning the supplied query as `media`;
// per-test overrides only for specialized behavior (e.g. reduced-motion).
if (typeof window !== 'undefined') {
    Object.defineProperty(window, 'matchMedia', {
        writable: true,
        value: (query: string) => ({
            matches: false,
            media: query,
            onchange: null,
            addListener: () => undefined,
            removeListener: () => undefined,
            addEventListener: () => undefined,
            removeEventListener: () => undefined,
            dispatchEvent: () => false,
        }),
    })
}
