const ASSETS_BASE = 'http://127.0.0.1:8000'

let currentAudio: HTMLAudioElement | null = null

export function playSound(snd_src: string): void {
  if (currentAudio) {
    currentAudio.pause()
    currentAudio = null
  }

  const url = `${ASSETS_BASE}/assets/sounds/${snd_src}`
  currentAudio = new Audio(url)
  currentAudio.play().catch((err) => {
    console.warn('Failed to play sound:', err)
  })
}
