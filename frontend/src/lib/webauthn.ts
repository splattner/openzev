/**
 * Thin bridge between the backend's WebAuthn JSON (base64url strings, as
 * py_webauthn emits it) and the browser's `navigator.credentials` API
 * (ArrayBuffers). Written out by hand rather than using
 * `PublicKeyCredential.parseCreationOptionsFromJSON` / `toJSON`, which are
 * not available in every browser this app supports yet.
 *
 * Spec 2026-09-two-factor-authentication.md §5.1, §5.2, §7.1.
 */

/** Whether this browser can run a passkey ceremony at all. Feature-detected,
 * never sniffed: the login page hides the passkey button when this is false. */
export function isPasskeySupported(): boolean {
    return (
        typeof window !== 'undefined' &&
        typeof window.PublicKeyCredential !== 'undefined' &&
        typeof navigator !== 'undefined' &&
        typeof navigator.credentials?.create === 'function' &&
        typeof navigator.credentials?.get === 'function'
    )
}

/** The user dismissed the browser's prompt, or no authenticator answered.
 * Distinct from a server-side failure so the UI can stay quiet about it. */
export class PasskeyCancelledError extends Error {
    constructor() {
        super('Passkey ceremony was cancelled')
        this.name = 'PasskeyCancelledError'
    }
}

export function base64urlToBuffer(value: string): ArrayBuffer {
    const padded = value.replace(/-/g, '+').replace(/_/g, '/').padEnd(Math.ceil(value.length / 4) * 4, '=')
    const binary = atob(padded)
    const bytes = new Uint8Array(binary.length)
    for (let i = 0; i < binary.length; i += 1) bytes[i] = binary.charCodeAt(i)
    return bytes.buffer
}

export function bufferToBase64url(buffer: ArrayBuffer | null | undefined): string {
    if (!buffer) return ''
    const bytes = new Uint8Array(buffer)
    let binary = ''
    for (let i = 0; i < bytes.length; i += 1) binary += String.fromCharCode(bytes[i])
    return btoa(binary).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '')
}

interface CredentialDescriptorJSON {
    id: string
    type: PublicKeyCredentialType
    transports?: AuthenticatorTransport[]
}

function descriptors(list: CredentialDescriptorJSON[] | undefined): PublicKeyCredentialDescriptor[] | undefined {
    return list?.map((item) => ({ ...item, id: base64urlToBuffer(item.id) }))
}

export interface CreationOptionsJSON extends Omit<PublicKeyCredentialCreationOptions, 'challenge' | 'user' | 'excludeCredentials'> {
    challenge: string
    user: { id: string; name: string; displayName: string }
    excludeCredentials?: CredentialDescriptorJSON[]
}

export interface RequestOptionsJSON extends Omit<PublicKeyCredentialRequestOptions, 'challenge' | 'allowCredentials'> {
    challenge: string
    allowCredentials?: CredentialDescriptorJSON[]
}

function isCancellation(error: unknown): boolean {
    // NotAllowedError is what browsers raise for a dismissed prompt, a
    // timeout, and "no matching authenticator" alike.
    return error instanceof DOMException && (error.name === 'NotAllowedError' || error.name === 'AbortError')
}

/** Run the registration ceremony and return the credential in the JSON shape
 * the backend verifies. */
export async function createPasskey(options: CreationOptionsJSON): Promise<Record<string, unknown>> {
    let credential: Credential | null
    try {
        credential = await navigator.credentials.create({
            publicKey: {
                ...options,
                challenge: base64urlToBuffer(options.challenge),
                user: { ...options.user, id: base64urlToBuffer(options.user.id) },
                excludeCredentials: descriptors(options.excludeCredentials),
            },
        })
    } catch (error) {
        if (isCancellation(error)) throw new PasskeyCancelledError()
        throw error
    }
    if (!(credential instanceof PublicKeyCredential)) throw new PasskeyCancelledError()
    const response = credential.response as AuthenticatorAttestationResponse
    return {
        id: credential.id,
        rawId: bufferToBase64url(credential.rawId),
        type: credential.type,
        response: {
            clientDataJSON: bufferToBase64url(response.clientDataJSON),
            attestationObject: bufferToBase64url(response.attestationObject),
            transports: typeof response.getTransports === 'function' ? response.getTransports() : [],
        },
        clientExtensionResults: credential.getClientExtensionResults(),
    }
}

/** Run the sign-in ceremony and return the assertion in the JSON shape the
 * backend verifies. */
export async function getPasskey(options: RequestOptionsJSON): Promise<Record<string, unknown>> {
    let credential: Credential | null
    try {
        credential = await navigator.credentials.get({
            publicKey: {
                ...options,
                challenge: base64urlToBuffer(options.challenge),
                allowCredentials: descriptors(options.allowCredentials),
            },
        })
    } catch (error) {
        if (isCancellation(error)) throw new PasskeyCancelledError()
        throw error
    }
    if (!(credential instanceof PublicKeyCredential)) throw new PasskeyCancelledError()
    const response = credential.response as AuthenticatorAssertionResponse
    return {
        id: credential.id,
        rawId: bufferToBase64url(credential.rawId),
        type: credential.type,
        response: {
            clientDataJSON: bufferToBase64url(response.clientDataJSON),
            authenticatorData: bufferToBase64url(response.authenticatorData),
            signature: bufferToBase64url(response.signature),
            userHandle: bufferToBase64url(response.userHandle),
        },
        clientExtensionResults: credential.getClientExtensionResults(),
    }
}
