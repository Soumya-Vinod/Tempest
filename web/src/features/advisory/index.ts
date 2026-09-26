// Advisory feature (Dev B): suggested blocks, Gemini drafts and the approval queue.
import { useCallback, useMemo, useState } from 'react'

import { createAdvisory } from '../../lib/api'
import { REPLAY_TIMESTEPS, relativeLabel } from '../../lib/constants'
import type { Advisory, BlockId } from '../../types/contracts'
import type { AdvisoryDrawerProps } from './AdvisoryDrawer'
import type { AdvisoryPanelProps } from './AdvisoryPanel'
import { errorText } from './errors'
import { useQueue, useSuggestions } from './useAdvisories'

export { default as AdvisoryDrawer } from './AdvisoryDrawer'
export { default as AdvisoryPanel } from './AdvisoryPanel'

export interface AdvisoryUi {
  panel: AdvisoryPanelProps
  drawer: AdvisoryDrawerProps
}

/**
 * Advisories for the scrubber's timestep. `blocks` lists every scored block (for adding one that
 * isn't suggested); `selectBlock` selects a block on the map when an advisory is opened.
 */
export function useAdvisories(
  timestepIndex: number,
  blocks: { block_id: BlockId; block_name: string }[],
  selectBlock: (blockId: BlockId) => void,
): AdvisoryUi {
  const timestep = REPLAY_TIMESTEPS[timestepIndex]
  const suggestions = useSuggestions(timestep)
  const { queue, reload } = useQueue()
  const [open, setOpen] = useState(false)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [generating, setGenerating] = useState<BlockId | null>(null)
  const [error, setError] = useState<string | null>(null)

  const onSelect = useCallback(
    (a: Advisory | null) => {
      setSelectedId(a?.id ?? null)
      if (a) selectBlock(a.properties.block_id)
    },
    [selectBlock],
  )

  const onGenerate = useCallback(
    async (blockId: BlockId) => {
      setGenerating(blockId)
      setError(null)
      try {
        const advisory = await createAdvisory({ block_id: blockId, timestep })
        reload()
        setOpen(true)
        onSelect(advisory)
      } catch (err) {
        setError(errorText(err))
      } finally {
        setGenerating(null)
      }
    },
    [timestep, reload, onSelect],
  )

  const onChanged = useCallback(
    (a: Advisory) => {
      reload()
      setSelectedId(a.id) // a new draft opens in place of its source
    },
    [reload],
  )

  const counts = useMemo(() => {
    const list = queue.status === 'ok' ? queue.data : []
    return {
      drafts: list.filter((a) => a.properties.status === 'draft').length,
      approved: list.filter((a) => a.properties.status === 'approved').length,
    }
  }, [queue])

  return {
    panel: {
      timestepLabel: relativeLabel(timestepIndex),
      suggestions,
      blocks,
      generating,
      error,
      ...counts,
      onGenerate: (blockId) => void onGenerate(blockId),
      onOpenQueue: () => setOpen(true),
    },
    drawer: {
      open,
      queue,
      selectedId,
      onSelect,
      onChanged,
      onClose: () => setOpen(false),
    },
  }
}
