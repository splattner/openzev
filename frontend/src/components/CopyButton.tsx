import { FontAwesomeIcon } from '@fortawesome/react-fontawesome'
import { faCopy } from '@fortawesome/free-solid-svg-icons'
import { useId, type Ref } from 'react'
import { useTranslation } from 'react-i18next'
import { copyToClipboard } from '../lib/clipboard'
import { useToast } from '../lib/toast'

interface Props {
    value: string
    /** The id of the value's visible label, so each Copy is announced with what it copies. */
    labelId: string
    ref?: Ref<HTMLButtonElement>
}

/** Copy beside a value. The result is a toast, so it always speaks for the value just copied. */
export function CopyButton({ value, labelId, ref }: Props) {
    const { t } = useTranslation()
    const { pushToast } = useToast()
    const id = useId()

    async function copy() {
        const ok = await copyToClipboard(value)
        pushToast(t(ok ? 'common.copied' : 'common.copyFailed'), ok ? 'success' : 'error')
    }

    return (
        <button ref={ref} id={id} type="button" className="button button-secondary button-compact" aria-labelledby={`${id} ${labelId}`} onClick={() => void copy()}>
            <FontAwesomeIcon icon={faCopy} fixedWidth />
            {t('common.copy')}
        </button>
    )
}
