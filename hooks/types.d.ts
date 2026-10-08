// The values the module keeps in $.state (claude plugin validate holds it to this).
export type SilicaCoreOffer = 'hidden' | 'offer' | 'indexing'

declare module 'claude-code' {
  interface PluginState {
    'silica-core': { offer: SilicaCoreOffer }
  }
}
