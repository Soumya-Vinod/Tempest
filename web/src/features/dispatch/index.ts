// dispatch feature (Dev B): the Dispatch dialog and receipts, used by the advisory detail view.
import { lazy } from 'react'

// Code-split: loaded when the dialog first opens (in Suspense).
export const DispatchDialog = lazy(() => import('./DispatchDialog'))
export { default as ReceiptList } from './ReceiptList'
