import type { EngineInterface } from 'claude-code'
import type { DocsReport } from './types.d.ts'

// The docs upkeep of docs/adr/0004: what a doc says about itself and what it
// points at, read from its text; what the repo's records break, read with git.
// The implementation contract is silica-internal ADR-0056's, as its
// scripts/docs_status.py held it before 544963a5 removed it.

export type Front = Record<string, string | string[]>

export const SHA = /^[0-9a-f]{7,40}$/
const STATES = ['implemented', 'partial', 'pending', 'draft', 'dropped', 'n/a']
// ponytail: a file three records list (cli.py, plugin.json) changes with every feature, so its commits are not drift; measured on silica-internal 2026-10-14, 85 drifting records became 37
export const HUB = 3

const unquote = (s: string) => s.trim().replace(/^(["'])(.*)\1$/, '$2')

// ponytail: the YAML records use, not YAML: `k: v`, `k: [a, "b"]` and a `- x`
// block list under an empty `k:`; a folded or nested value reads as its first line
export function frontmatter(text: string): Front {
  const m = text.match(/^---\r?\n([\s\S]*?)\r?\n---\s*(\r?\n|$)/)
  if (!m) return {}
  const out: Front = {}
  let list: string[] | undefined
  for (const line of m[1]!.split(/\r?\n/)) {
    const item = line.match(/^\s*-\s+(.*)$/)
    if (item && list) { list.push(unquote(item[1]!)); continue }
    const kv = line.match(/^([A-Za-z_][\w-]*):\s*(.*)$/)
    if (!kv) continue
    const [, key, value] = kv as unknown as [string, string, string]
    list = undefined
    if (value === '') out[key] = list = []
    else if (value.startsWith('[') && value.endsWith(']')) out[key] = value.slice(1, -1).split(',').map(unquote).filter(Boolean)
    else out[key] = unquote(value)
  }
  return out
}

export const listOf = (v: string | string[] | undefined): string[] => (v === undefined ? [] : Array.isArray(v) ? v : [v])

// the path entries of implemented_in and documents; a SHA is evidence, not a path
export const paths = (fm: Front): string[] =>
  [...listOf(fm.implemented_in), ...listOf(fm.documents)].filter(r => !SHA.test(r))

export const isRecord = (rel: string) =>
  /^docs\/adr\/\d{4}-[^/]+\.md$/.test(rel)
  || (/^docs\/specs\/[^/]+\.md$/.test(rel) && !rel.endsWith('/README.md'))
  || /^docs\/specs\/[^/]+\/spec\.md$/.test(rel)

// the rules of the state that need nothing but the frontmatter; a record
// with no `implementation` is not under the contract and is left alone
export function stateProblems(fm: Front): string[] {
  const state = fm.implementation
  if (state === undefined) return []
  if (typeof state !== 'string' || !STATES.includes(state)) return [`implementation: '${state}' is not one of ${STATES.join(', ')}`]
  const refs = listOf(fm.implemented_in)
  const note = String(fm.implementation_note ?? '').trim()
  const out: string[] = []
  if ((state === 'implemented' || state === 'partial') && !refs.length) out.push(`${state} names no evidence in implemented_in`)
  if ((state === 'pending' || state === 'draft') && refs.length) out.push(`${state} cannot name evidence; implemented_in is for what was built`)
  if ((state === 'partial' || state === 'dropped') && !note) out.push(`${state} needs an implementation_note`)
  return out
}

const FENCE = /^(```|~~~)[^\n]*\n[\s\S]*?^\1[^\n]*$/gm
const withoutFences = (text: string) => text.replace(FENCE, '')

// relative markdown link targets outside code: no scheme, no bare anchor, no absolute path
export function mdLinks(text: string): string[] {
  const prose = withoutFences(text).replace(/`[^`\n]*`/g, '')
  const out: string[] = []
  for (const m of prose.matchAll(/\]\(\s*<?([^)\s>]+)>?(?:\s+"[^"]*")?\s*\)/g)) {
    const target = m[1]!.split('#')[0]!.split('?')[0]!
    if (!target || target.startsWith('/') || /^[a-z][a-z0-9+.-]*:/i.test(target)) continue
    try { out.push(decodeURI(target)) } catch { out.push(target) }
  }
  return out
}

// code spans outside fences that read as relative paths with a folder in
// them, a line suffix (`:12`, `:3-9`, `#L12`) cut; the caller keeps only the
// ones whose first folder is in the repo
export function codePaths(text: string): string[] {
  const out: string[] = []
  for (const m of withoutFences(text).matchAll(/`([^`\s]+)`/g)) {
    const token = m[1]!.replace(/(:\d+(-\d+)?|#L\d+(-L?\d+)?)$/, '')
    if (!token.includes('/') || /^[/~.$-]/.test(token) || /[*<>{}()@=:\[\]]/.test(token)) continue
    out.push(token)
  }
  return out
}

// the body under `## Decision`, up to the next heading of level 1 or 2
export function decision(text: string): string | undefined {
  const m = text.match(/^##\s+Decision\b[^\n]*\n([\s\S]*?)(?=^#{1,2}\s|(?![\s\S]))/m)
  return m ? m[1] : undefined
}

// `**Status:** Accepted`, `- **Status:** accepted (date)`, or `status: accepted` in the frontmatter
export const isAccepted = (text: string) => /\bstatus:?\**\s*:?\s*\**\s*accepted\b/i.test(text)

// the ADR numbers a record supersedes or is superseded by
export const supersedes = (text: string): string[] =>
  [...text.matchAll(/supersed(?:ed by|es)\s+\[?ADR-(\d{4})/gi)].map(m => m[1]!)

export const covers = (entry: string, rel: string) => rel === entry || rel.startsWith(`${entry.replace(/\/$/, '')}/`)

// `a/../b` and `./` resolved; undefined when it climbs out of the root
function normalize(rel: string): string | undefined {
  const out: string[] = []
  for (const part of rel.split('/')) {
    if (part === '..') { if (!out.length) return undefined; out.pop() }
    else if (part && part !== '.') out.push(part)
  }
  return out.join('/')
}

async function git($: EngineInterface, root: string, args: string[]): Promise<string> {
  const r = await $.process.run(['git', '-C', root, ...args], { timeoutMs: 30_000 }).catch(() => undefined)
  return r && r.exitCode === 0 ? r.stdout : ''
}

// every commit reachable from HEAD, or null where that cannot be known (not a repo, a shallow clone)
async function commits($: EngineInterface, root: string): Promise<string[] | null> {
  if ((await git($, root, ['rev-parse', '--is-shallow-repository'])).trim() !== 'false') return null
  return (await git($, root, ['rev-list', 'HEAD'])).split('\n').filter(Boolean)
}

// a `--format=@%ct --name-only` log, newest first
const parseLog = (out: string) => {
  const log: { t: number; files: string[] }[] = []
  for (const line of out.split('\n')) {
    if (line.startsWith('@')) log.push({ t: Number(line.slice(1)), files: [] })
    else if (line.trim() && log.length) log.at(-1)!.files.push(line.trim())
  }
  return log
}

// the records under docs/adr/ and docs/specs/, root-relative
async function records($: EngineInterface, root: string): Promise<string[]> {
  const ls = (rel: string) => $.fs.list(`${root}/${rel}`).catch(() => [])
  const out = (await ls('docs/adr')).map(x => `docs/adr/${x.name}`)
  for (const x of await ls('docs/specs')) out.push(x.kind === 'dir' ? `docs/specs/${x.name}/spec.md` : `docs/specs/${x.name}`)
  return out.filter(isRecord)
}

// what a record names that is not there: a SHA that is not one commit
// reachable from HEAD, a path of implemented_in or documents not in the tree
async function evidence($: EngineInterface, root: string, fm: Front, known: string[] | null): Promise<string[]> {
  const out: string[] = []
  for (const ref of listOf(fm.implemented_in)) {
    if (SHA.test(ref)) {
      if (known && known.filter(c => c.startsWith(ref)).length !== 1) out.push(`${ref} is not one commit reachable from HEAD`)
    } else if (!(await $.fs.exists(`${root}/${ref.replace(/\/$/, '')}`))) out.push(`${ref} is neither a commit nor a path in the tree`)
  }
  for (const ref of listOf(fm.documents)) {
    if (!SHA.test(ref) && !(await $.fs.exists(`${root}/${ref.replace(/\/$/, '')}`))) out.push(`documents names ${ref}, which is not in the tree`)
  }
  return out
}

// each record by its path, with the paths its implemented_in and documents name
export async function listed($: EngineInterface, root: string): Promise<Map<string, string[]>> {
  const out = new Map<string, string[]>()
  for (const rec of await records($, root)) {
    const names = paths(frontmatter(String(await $.fs.read(`${root}/${rec}`).catch(() => ''))))
    if (names.length) out.set(rec, names)
  }
  return out
}

export async function scan($: EngineInterface, root: string): Promise<DocsReport> {
  const recs = await records($, root)
  if (!recs.length) return { problems: [], drift: [] }
  const fms = new Map<string, Front>()
  for (const rec of recs) fms.set(rec, frontmatter(String(await $.fs.read(`${root}/${rec}`).catch(() => ''))))

  const known = await commits($, root)
  const problems: string[] = []
  for (const [rec, fm] of fms) {
    if (fm.implementation === undefined) continue
    for (const p of [...stateProblems(fm), ...(await evidence($, root, fm, known))]) problems.push(`${rec}: ${p}`)
  }

  // drift: commits to a record's files after the record's last commit (its mtime when git does not track it)
  const hubs = new Map<string, number>()
  for (const fm of fms.values()) for (const p of paths(fm)) hubs.set(p, (hubs.get(p) ?? 0) + 1)
  const last = new Map<string, number>()
  for (const c of parseLog(await git($, root, ['log', '--format=@%ct', '--name-only', '--', 'docs/adr', 'docs/specs'])))
    for (const f of c.files) if (!last.has(f)) last.set(f, c.t)
  const anchors = new Map<string, number>()
  for (const rec of recs) {
    anchors.set(rec, last.get(rec) ?? Math.floor(((await $.fs.stat(`${root}/${rec}`).catch(() => undefined))?.mtimeMs ?? 0) / 1000))
  }
  const since = Math.min(...anchors.values())
  const log = parseLog(await git($, root, ['log', `--since=@${since}`, '--format=@%ct', '--name-only']))
  const drift: DocsReport['drift'] = []
  for (const [rec, fm] of fms) {
    if (fm.implementation !== 'implemented' && fm.implementation !== 'partial') continue
    const own = paths(fm).filter(p => (hubs.get(p) ?? 0) < HUB)
    const anchor = anchors.get(rec)!
    const n = own.length ? log.filter(c => c.t > anchor && c.files.some(f => own.some(p => covers(p, f)))).length : 0
    if (n) drift.push({ rec, commits: n })
  }
  drift.sort((a, b) => b.commits - a.commits)
  return { problems, drift }
}

export function describe(r: DocsReport): string {
  if (!r.problems.length && !r.drift.length) return 'docs: nothing to report'
  const lines = [`docs: ${r.problems.length} problems · ${r.drift.length} drifting`]
  if (r.problems.length) {
    lines.push('', 'Problems (a record whose implementation state breaks its rules, or that names what is not there):',
      ...r.problems.map(p => `- ${p}`))
  }
  if (r.drift.length) {
    lines.push('', `Drift (commits to the files a record lists since the record was last written; files ${HUB} or more records list are left out):`,
      ...r.drift.map(d => `- ${d.rec}: ${d.commits} commit${d.commits > 1 ? 's' : ''}`))
  }
  return lines.join('\n')
}

// what the docs this turn wrote get wrong, one line each; `docs` holds each
// with its text before the turn's first write (null for a new one)
export async function lint($: EngineInterface, root: string, docs: Map<string, string | null>): Promise<string[]> {
  const out: string[] = []
  const exists = (rel: string) => $.fs.exists(`${root}/${rel.replace(/\/$/, '')}`)
  const top = new Set((await $.fs.list(root).catch(() => [])).filter(x => x.kind === 'dir').map(x => x.name))
  const adrs = (await $.fs.list(`${root}/docs/adr`).catch(() => [])).map(x => x.name)
  let known: string[] | null | undefined
  for (const [rel, before] of docs) {
    const text = await $.fs.read(`${root}/${rel}`).then(String).catch(() => undefined)
    if (text === undefined) continue
    const dir = rel.split('/').slice(0, -1).join('/')
    for (const target of mdLinks(text)) {
      const to = normalize(`${dir}/${target}`)
      if (to === undefined || !(await exists(to))) out.push(`${rel}: the link to ${target} leads nowhere`)
    }
    for (const p of codePaths(text)) {
      if (top.has(p.split('/')[0]!) && !(await exists(p))) out.push(`${rel}: \`${p}\` is not in the repo`)
    }
    if (isRecord(rel)) {
      const fm = frontmatter(text)
      if (fm.implementation !== undefined) {
        known ??= await commits($, root)
        for (const p of [...stateProblems(fm), ...(await evidence($, root, fm, known))]) out.push(`${rel}: ${p}`)
      }
      for (const n of supersedes(text)) {
        if (!adrs.some(x => x.startsWith(`${n}-`))) out.push(`${rel}: it names ADR-${n}, which docs/adr/ does not hold`)
      }
    }
    const num = rel.match(/^docs\/adr\/(\d{4})-/)?.[1]
    const same = num ? adrs.filter(x => x.startsWith(`${num}-`)) : []
    if (same.length > 1) out.push(`${rel}: ADR number ${num} is taken by ${same.length} files: ${same.join(', ')}`)
    const was = before != null && rel.startsWith('docs/adr/') && isAccepted(before) ? decision(before) : undefined
    if (was !== undefined && was.trim() !== (decision(text) ?? '').trim()) {
      out.push(`${rel}: the Decision of an accepted ADR changed this turn. If the decision was reversed or replaced, ` +
        'put it back, write a new ADR that supersedes this one and mark this one "Superseded by" it; if the change only clarifies it, say so')
    }
  }
  return out
}

export function reminder(why: string, files: string[], adrs: string[]): string {
  const shown = files.length > 8 ? [...files.slice(0, 8), `${files.length - 8} more`] : files
  return `silica-core: this turn's writes are worth recording (${why}): ${shown.join(', ')}. ` +
    'Before you end the turn, bring docs/ up to date with what a later session would need: ' +
    'a decision that had alternatives goes in an ADR under docs/adr/; ' +
    (adrs.length ? `${adrs.join(', ')} list${adrs.length > 1 ? '' : 's'} these files in implemented_in or documents: if its decision still stands, update its implementation_note; ` +
      'if this change reverses or replaces that decision, write a new ADR that supersedes it and mark the old one "Superseded by", never rewriting its Decision; ' : '') +
    'a finding you measured or verified goes in the doc it belongs to; say whether a security check ran on this change, and which. ' +
    'A routine change gets no doc: say "docs: nothing to record" in one line instead.'
}
