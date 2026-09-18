import { ElectronAPI } from '@electron-toolkit/preload'

declare global {
  interface Window {
    electron: ElectronAPI & {
      readMetadata: (gameFolder: string) => Promise<{
        success: boolean
        content: string
        path: string
        error?: string
      }>
    }
    api: {
      signalLaunch: (gamePath?: string | null) => void
      getLaunchPaths: () => Promise<{
        gameFolder: string | null
        gamePath: string | null
        emulatorFolder: string | null
        emulatorTarget: string | null
      }>
    }
  }
}
