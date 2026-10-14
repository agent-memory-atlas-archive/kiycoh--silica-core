// The values the module keeps in $.state (claude plugin validate holds it to this).
export type SilicaCoreOffer = 'hidden' | 'offer' | 'indexing'

// A scan of the folder's records: what breaks the implementation contract or
// points nowhere, and the records whose files took commits since the record
// was last written (docs/adr/0004).
export type DocsReport = { problems: string[]; drift: { rec: string; commits: number }[] }

declare module 'claude-code' {
  interface PluginState {
    'silica-core': { offer: SilicaCoreOffer; docs: DocsReport | null; isDocsHidden: boolean }
  }
}
