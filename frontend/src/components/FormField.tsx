import { useState } from 'react'

export interface ValidationResult {
    valid: boolean
    error?: string
}

export interface FormFieldProps {
    label: string
    value: string | null
    onChange: (value: string) => void
    placeholder?: string
    type?: 'text' | 'email' | 'date' | 'number'
    required?: boolean
    disabled?: boolean
    validator?: (value: string) => Promise<ValidationResult> | ValidationResult
    debounceMs?: number
    helpText?: string
    error?: string
}

export function FormField({
    label,
    value,
    onChange,
    placeholder,
    type = 'text',
    required = false,
    disabled = false,
    validator,
    debounceMs = 500,
    helpText,
    error: externalError,
}: FormFieldProps) {
    const [error, setError] = useState<string | null>(externalError || null)
    const [isValidating, setIsValidating] = useState(false)
    const [validationTimer, setValidationTimer] = useState<number | null>(null)

    const handleValidation = async (val: string) => {
        if (!validator || !val) {
            setError(null)
            return
        }

        setIsValidating(true)
        try {
            const result = await validator(val)
            setError(result.error || null)
        } catch {
            setError('Validation failed')
        } finally {
            setIsValidating(false)
        }
    }

    const handleChange = (newValue: string) => {
        onChange(newValue)
        setError(null)

        // Clear existing timer
        if (validationTimer) {
            clearTimeout(validationTimer)
        }

        // Set new timer for debounced validation
        if (validator) {
            const timer = window.setTimeout(() => handleValidation(newValue), debounceMs)
            setValidationTimer(timer)
        }
    }

    return (
        <label style={{ display: 'flex', flexDirection: 'column', gap: '0.4rem' }}>
            <span style={{ fontWeight: '500', fontSize: '0.9rem' }}>
                {label}
                {required && <span style={{ color: '#ef4444', marginLeft: '0.2rem' }}>*</span>}
            </span>
            <input
                type={type}
                value={value || ''}
                onChange={(e) => handleChange(e.target.value)}
                placeholder={placeholder}
                disabled={disabled || isValidating}
                required={required}
                style={{
                    borderColor: error ? '#ef4444' : undefined,
                    borderRadius: '0.4rem',
                    padding: '0.6rem',
                }}
            />
            {error && (
                <span style={{ fontSize: '0.85rem', color: '#ef4444', fontWeight: '500' }}>
                    {error}
                </span>
            )}
            {isValidating && (
                <span style={{ fontSize: '0.85rem', color: '#f59e0b' }}>
                    Checking...
                </span>
            )}
            {helpText && !error && (
                <span style={{ fontSize: '0.85rem', color: '#888' }}>
                    {helpText}
                </span>
            )}
        </label>
    )
}
