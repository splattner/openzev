/**
 * Async form validation utilities with debouncing.
 * Enables real-time availability checks for tariffs, participants, etc.
 */

const debounceTimers = new Map<string, number>()

/**
 * Check if a tariff is available (not deleted, valid date range)
 */
export async function validateTariffId(tariffId: string): Promise<{ valid: boolean; error?: string }> {
    if (!tariffId) return { valid: false, error: 'Tariff is required' }

    try {
        const response = await fetch(`/api/v1/tariffs/tariffs/${tariffId}/`)
        if (!response.ok) {
            return { valid: false, error: 'Tariff not found or not accessible' }
        }
        return { valid: true }
    } catch {
        return { valid: false, error: 'Failed to validate tariff' }
    }
}

/**
 * Check if a participant is available (not deleted, valid period)
 */
export async function validateParticipantId(participantId: string): Promise<{ valid: boolean; error?: string }> {
    if (!participantId) return { valid: false, error: 'Participant is required' }

    try {
        const response = await fetch(`/api/v1/zev/participants/${participantId}/`)
        if (!response.ok) {
            return { valid: false, error: 'Participant not found or not accessible' }
        }
        return { valid: true }
    } catch {
        return { valid: false, error: 'Failed to validate participant' }
    }
}

/**
 * Debounced async validator that prevents excessive API calls
 */
export function createDebouncedValidator(
    validator: (value: string) => Promise<{ valid: boolean; error?: string }>,
    debounceMs = 500,
    key = 'validator'
) {
    return async (value: string, callback: (result: { valid: boolean; error?: string }) => void) => {
        // Clear existing timer
        if (debounceTimers.has(key)) {
            clearTimeout(debounceTimers.get(key)!)
        }

        // Set new timer
        const timer = window.setTimeout(async () => {
            try {
                const result = await validator(value)
                callback(result)
            } catch {
                callback({ valid: false, error: 'Validation failed' })
            }
        }, debounceMs)

        debounceTimers.set(key, timer)
    }
}

/**
 * Validate date range (start <= end)
 */
export function validateDateRange(
    startDate: string,
    endDate: string
): { valid: boolean; error?: string } {
    if (!startDate || !endDate) {
        return { valid: false, error: 'Both start and end dates are required' }
    }

    const start = new Date(startDate)
    const end = new Date(endDate)

    if (start > end) {
        return { valid: false, error: 'Start date must be before end date' }
    }

    return { valid: true }
}

/**
 * Validate email format
 */
export function validateEmail(email: string): { valid: boolean; error?: string } {
    if (!email) return { valid: true } // Optional field

    const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/
    if (!emailRegex.test(email)) {
        return { valid: false, error: 'Invalid email address' }
    }

    return { valid: true }
}

/**
 * Validate CHF currency amount
 */
export function validateCHFAmount(value: unknown): { valid: boolean; error?: string } {
    if (value === '' || value === null || value === undefined) {
        return { valid: false, error: 'Amount is required' }
    }

    const amount = Number(value)
    if (isNaN(amount) || amount < 0) {
        return { valid: false, error: 'Amount must be a positive number' }
    }

    if (!/^\d+(\.\d{0,2})?$/.test(String(value))) {
        return { valid: false, error: 'Amount must have max 2 decimal places' }
    }

    return { valid: true }
}

/**
 * Validate required field
 */
export function validateRequired(value: unknown, fieldName: string): { valid: boolean; error?: string } {
    if (!value || (typeof value === 'string' && !value.trim())) {
        return { valid: false, error: `${fieldName} is required` }
    }
    return { valid: true }
}
