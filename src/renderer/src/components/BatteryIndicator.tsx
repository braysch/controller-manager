import { Battery, BatteryLow, BatteryMedium, BatteryFull } from 'lucide-react'

interface BatteryIndicatorProps {
  percent: number
}

export default function BatteryIndicator({ percent }: BatteryIndicatorProps): JSX.Element {
  let Icon = Battery
  let color = 'text-red-400'

  if (percent > 75) {
    Icon = BatteryFull
    color = 'text-green-400'
  } else if (percent > 40) {
    Icon = BatteryMedium
    color = 'text-yellow-400'
  } else if (percent > 15) {
    Icon = BatteryLow
    color = 'text-orange-400'
  }

  return (
    <div className={`flex items-center gap-0.5 ${color}`} title={`${percent}%`}>
      <Icon size={14} />
      <span className="text-[10px]">{percent}%</span>
    </div>
  )
}
