import type { ReadyController } from '../types'
import ReadySlot from './ReadySlot'
import { useEffect, useState } from 'react'

interface ReadyGridProps {
  controllers: ReadyController[]
  poppingControllers: Set<string>
  gameFolder: string | null
}

function parsePlayersCount(content: string): number | null {
  for (const line of content.split('\n')) {
    const match = line.match(/^players\s*:\s*(\d+)/)
    if (match) {
      return parseInt(match[1], 10)
    }
  }
  return null
}

export default function ReadyGrid({ controllers, poppingControllers, gameFolder }: ReadyGridProps): JSX.Element {
  const [metadataPath, setMetadataPath] = useState('')
  const [metadataContent, setMetadataContent] = useState('')
  const [playerCount, setPlayerCount] = useState<number | null>(null)

  useEffect(() => {
    if (gameFolder) {
      window.electron.readMetadata(gameFolder).then((result) => {
        if (result.success) {
          setMetadataPath(result.path)
          setMetadataContent(result.content)
          setPlayerCount(parsePlayersCount(result.content))
        } else {
          setMetadataContent(`Error: ${result.error}`)
        }
      })
    }
  }, [gameFolder])

  const TOTAL_SLOTS = playerCount ?? 8
  const slots = Array.from({ length: TOTAL_SLOTS }, (_, i) => controllers[i] ?? null)

  return (
    <div>
      <div className="flex-1">
        <div className={`grid grid-cols-${TOTAL_SLOTS <= 4 ? TOTAL_SLOTS : 4} ${TOTAL_SLOTS > 4 ? 'grid-rows-2' : 'grid-rows-1'} gap-y-3 gap-x-9 h-full`}>
          {slots.map((controller, index) => (
            <ReadySlot key={index} controller={controller} slotIndex={index} poppingControllers={poppingControllers} />
          ))}
        </div>
      </div>
    </div>
  )
}