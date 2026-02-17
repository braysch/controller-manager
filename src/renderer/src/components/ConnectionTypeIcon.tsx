import { Bluetooth, Usb } from 'lucide-react'

interface ConnectionTypeIconProps {
  type: 'usb' | 'bluetooth'
}

export default function ConnectionTypeIcon({ type }: ConnectionTypeIconProps): JSX.Element {
  if (type === 'bluetooth') {
    return <Bluetooth size={12} className="text-blue-400" title="Bluetooth" />
  }
  return <Usb size={12} className="text-gray-400" title="USB" />
}
