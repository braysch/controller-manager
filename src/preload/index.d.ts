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
      quitAndLaunch: () => void
      getLaunchPaths: () => Promise<{
        gameFolder: string | null
        emulatorFolder: string | null
        emulatorTarget: string | null
      }>
    }
  }
}
