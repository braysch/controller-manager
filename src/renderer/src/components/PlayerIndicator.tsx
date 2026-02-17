interface PlayerIndicatorProps {
  playerNumber: number
}

// Nintendo Switch LED patterns per player number
const LED_PATTERNS: boolean[][] = [
  [true,  false, false, false], // P1: 1000
  [true,  true,  false, false], // P2: 1100
  [true,  true,  true,  false], // P3: 1110
  [true,  true,  true,  true],  // P4: 1111
  [true,  false, false, true],  // P5: 1001
  [true,  false, true,  false], // P6: 1010
  [true,  false, true,  true],  // P7: 1011
  [false, true,  true,  false], // P8: 0110
]

export default function PlayerIndicator({ playerNumber }: PlayerIndicatorProps): JSX.Element {
  const leds = LED_PATTERNS[playerNumber - 1] ?? [false, false, false, false]

  return (
    <div className="flex gap-1" title={`Player ${playerNumber}`}>
      {leds.map((on, i) => (
        <div
          key={i}
          className={`w-2.5 h-2.5 rounded-sm ${on ? 'bg-green-400' : 'bg-gray-600'}`}
        />
      ))}
    </div>
  )
}
