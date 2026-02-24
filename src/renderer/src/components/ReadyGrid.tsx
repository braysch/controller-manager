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

  const TOTAL_SLOTS = playerCount ?? 1
  const slots = Array.from({ length: TOTAL_SLOTS }, (_, i) => controllers[i] ?? null)

  const gridCols = TOTAL_SLOTS <= 4 ? TOTAL_SLOTS : 4
  const gridRows = Math.ceil(TOTAL_SLOTS / 4)

  return (
    <div className="flex-1">
      <div 
        className="gap-y-3 gap-x-9 h-full"
        style={{ 
          display: 'grid',
          gridTemplateColumns: `repeat(${gridCols}, minmax(0, 1fr))`,
          gridTemplateRows: `repeat(${gridRows}, minmax(0, 1fr))`
        }}
      >
        {slots.map((controller, index) => (
          <ReadySlot key={index} controller={controller} slotIndex={index} poppingControllers={poppingControllers} />
        ))}
      </div>
    </div>
  )
}