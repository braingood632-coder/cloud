export type RingView = 'closed' | 'menu' | 'new' | 'link'
export type RingSession = { id: string; title: string }

declare module 'claude-code' {
  interface PluginState {
    'green-lantern': {
      view: RingView
      sessions: RingSession[]
      target: string | null
      withContext: boolean
      status: string | null
    }
  }
}
