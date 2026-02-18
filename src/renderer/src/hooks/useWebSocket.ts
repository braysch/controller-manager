import { useEffect, useRef, useState, useCallback } from 'react'
import type { WSEvent, ControllerAction, BluetoothDevice } from '../types'
import { playSound } from '../lib/sounds'

const WS_URL = 'ws://127.0.0.1:8000/ws'
const RECONNECT_DELAY = 2000

export function useWebSocket(
  dispatch: React.Dispatch<ControllerAction>
): {
  connected: boolean
  bluetoothDevices: BluetoothDevice[]
  bluetoothScanning: boolean
  clearBluetoothDevices: () => void
} {
  const [connected, setConnected] = useState(false)
  const [bluetoothDevices, setBluetoothDevices] = useState<BluetoothDevice[]>([])
  const [bluetoothScanning, setBluetoothScanning] = useState(false)
  const wsRef = useRef<WebSocket | null>(null)
  const reconnectTimer = useRef<ReturnType<typeof setTimeout>>()

  const clearBluetoothDevices = useCallback(() => {
    setBluetoothDevices([])
  }, [])

  const connect = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) return

    const ws = new WebSocket(WS_URL)
    wsRef.current = ws

    ws.onopen = () => {
      console.log('[WS] Connected')
      setConnected(true)
    }

    ws.onmessage = (event) => {
      try {
        const msg: WSEvent = JSON.parse(event.data)
        switch (msg.type) {
          case 'state_snapshot':
            dispatch({
              type: 'SET_STATE',
              connected: msg.data.connected,
              ready: msg.data.ready
            })
            break
          case 'controller_connected':
            dispatch({ type: 'CONTROLLER_CONNECTED', controller: msg.data })
            break
          case 'controller_disconnected':
            dispatch({ type: 'CONTROLLER_DISCONNECTED', unique_id: msg.data.unique_id })
            break
          case 'controller_ready':
            dispatch({ type: 'CONTROLLER_READY', controller: msg.data })
            playSound(msg.data.snd_src)
            break
          case 'controller_unready':
            dispatch({ type: 'CONTROLLER_UNREADY', unique_id: msg.data.unique_id })
            break
          case 'battery_update':
            dispatch({
              type: 'BATTERY_UPDATE',
              unique_id: msg.data.unique_id,
              battery_percent: msg.data.battery_percent
            })
            break
          case 'bluetooth_scan_started':
            setBluetoothScanning(true)
            break
          case 'bluetooth_device_found':
            setBluetoothDevices((prev) => {
              if (prev.some((d) => d.address === msg.data.address)) return prev
              return [...prev, { name: msg.data.name, address: msg.data.address }]
            })
            break
          case 'bluetooth_scan_complete':
            setBluetoothScanning(false)
            break
        }
      } catch (err) {
        console.warn('[WS] Failed to parse message:', err)
      }
    }

    ws.onclose = () => {
      console.log('[WS] Disconnected, reconnecting...')
      setConnected(false)
      wsRef.current = null
      reconnectTimer.current = setTimeout(connect, RECONNECT_DELAY)
    }

    ws.onerror = () => {
      ws.close()
    }
  }, [dispatch])

  useEffect(() => {
    connect()
    return () => {
      clearTimeout(reconnectTimer.current)
      wsRef.current?.close()
    }
  }, [connect])

  return { connected, bluetoothDevices, bluetoothScanning, clearBluetoothDevices }
}
