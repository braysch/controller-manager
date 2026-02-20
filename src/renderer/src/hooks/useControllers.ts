import { useReducer, useCallback } from 'react'
import type { Controller, ReadyController, ControllerAction } from '../types'
import { api } from '../lib/api'

interface ControllerState {
  connected: Controller[]
  ready: ReadyController[]
}

function controllerReducer(state: ControllerState, action: ControllerAction): ControllerState {
  switch (action.type) {
    case 'SET_STATE':
      return { connected: action.connected, ready: action.ready }

    case 'CONTROLLER_CONNECTED':
      if (state.connected.some((c) => c.unique_id === action.controller.unique_id)) {
        return state
      }
      return { ...state, connected: [...state.connected, action.controller] }

    case 'CONTROLLER_DISCONNECTED':
      return {
        connected: state.connected.filter((c) => c.unique_id !== action.unique_id),
        ready: state.ready.filter((c) => c.unique_id !== action.unique_id)
      }

    case 'CONTROLLER_READY': {
      const remaining = state.connected.filter(
        (c) => c.unique_id !== action.controller.unique_id
      )
      const alreadyReady = state.ready.some(
        (c) => c.unique_id === action.controller.unique_id
      )
      if (alreadyReady) return state
      return { connected: remaining, ready: [...state.ready, action.controller] }
    }

    case 'CONTROLLER_UNREADY': {
      const removed = state.ready.find((c) => c.unique_id === action.unique_id)
      if (!removed) return state
      const { slot_index: _, ...base } = removed
      return {
        connected: [...state.connected, base as Controller],
        ready: state.ready.filter((c) => c.unique_id !== action.unique_id)
      }
    }

    case 'BATTERY_UPDATE':
      return {
        connected: state.connected.map((c) =>
          c.unique_id === action.unique_id
            ? { ...c, battery_percent: action.battery_percent }
            : c
        ),
        ready: state.ready.map((c) =>
          c.unique_id === action.unique_id
            ? { ...c, battery_percent: action.battery_percent }
            : c
        )
      }

    default:
      return state
  }
}

export function useControllers() {
  const [state, rawDispatch] = useReducer(controllerReducer, {
    connected: [],
    ready: []
  })

  const dispatch = useCallback(
    (action: ControllerAction) => {
      if (action.type === 'REASSIGN') {
        api.clearReady().catch(console.error)
        return
      }
      if (action.type === 'APPLY_CONFIG') {
        api.applyConfig(action.emulatorTarget)
          .then(() => window.api.quitAndLaunch())
          .catch(console.error)
        return
      }
      rawDispatch(action)
    },
    [rawDispatch]
  )

  return { connected: state.connected, ready: state.ready, dispatch }
}
