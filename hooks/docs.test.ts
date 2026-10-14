import { describe, expect, mock, test } from 'claude-code/testing'
import type { On } from 'claude-code'
import { codePaths, decision, frontmatter, isAccepted, isRecord, mdLinks, paths, stateProblems, supersedes } from './docs.ts'

const ROOT = '/work/repo'
const BAND = { hasSurvey: false, isWorking: false, maxRows: 10, bodyColumns: 80, scroll: { offset: 0, bodyRows: 10 }, view: {} }

describe('frontmatter', () => {
  test('inline lists, quoted SHAs, block lists and quoted strings', async () => {
    const fm = frontmatter('---\nimplementation: implemented\nimplemented_in: [a/b.py, "5619919", \'c/\']\n' +
      'documents:\n- x/y.md\n  - z.md\nimplementation_note: "a, b"\n---\n\n# T\n')
    expect(fm).toEqual({ implementation: 'implemented', implemented_in: ['a/b.py', '5619919', 'c/'],
                         documents: ['x/y.md', 'z.md'], implementation_note: 'a, b' })
  })

  test('no frontmatter is empty', async () => {
    expect(frontmatter('# T\n\nimplementation: implemented\n')).toEqual({})
  })

  test('paths are the path entries of implemented_in and documents, SHAs left out', async () => {
    expect(paths({ implemented_in: ['a/b.py', '5619919', 'deadbeefcafe'], documents: ['x/y.md'] }))
      .toEqual(['a/b.py', 'x/y.md'])
  })
})

describe('records and their implementation state', () => {
  test('ADRs and specs are records, their READMEs are not', async () => {
    expect(isRecord('docs/adr/0001-a.md')).toBe(true)
    expect(isRecord('docs/specs/note-panel.md')).toBe(true)
    expect(isRecord('docs/specs/learn/spec.md')).toBe(true)
    expect(isRecord('docs/adr/README.md')).toBe(false)
    expect(isRecord('docs/specs/README.md')).toBe(false)
    expect(isRecord('docs/plans/x.md')).toBe(false)
  })

  test('each rule of the state, and a record with no state is not checked', async () => {
    expect(stateProblems({ implementation: 'built' })[0]).toContain("'built' is not one of")
    expect(stateProblems({ implementation: 'implemented' })[0]).toContain('names no evidence')
    expect(stateProblems({ implementation: 'pending', implemented_in: ['a.py'] })[0]).toContain('cannot name evidence')
    expect(stateProblems({ implementation: 'dropped' })[0]).toContain('needs an implementation_note')
    expect(stateProblems({ implementation: 'partial', implemented_in: ['a.py'], implementation_note: 'half' })).toEqual([])
    expect(stateProblems({})).toEqual([])
  })
})

describe('what a doc points at', () => {
  const DOC = [
    'See [the decision](../adr/0002-x.md#context) and [site](https://x.org) and [top](#top).',
    'In code: `[nope](missing.md)` and `silica_core/core.py:1053` and `hooks/register.ts#L12`.',
    '```', '[nope](fenced.md) `silica_core/gone.py`', '```',
    'Not paths: `retrieve/write/research`? kept, the caller filters; `~/x/y`, `/abs/p`, `a b/c`, `--flag=a/b`.',
  ].join('\n')

  test('relative markdown links outside code, anchors and schemes left out', async () => {
    expect(mdLinks(DOC)).toEqual(['../adr/0002-x.md'])
  })

  test('code spans that look like relative paths, line suffixes cut, fences left out', async () => {
    expect(codePaths(DOC)).toEqual(['silica_core/core.py', 'hooks/register.ts', 'retrieve/write/research'])
  })
})

describe('decisions', () => {
  const ADR = (status: string, decided: string) =>
    `# ADR-0001\n\n- **Status:** ${status} (2026-10-08)\n\n## Context\nc\n\n## Decision\n${decided}\n\n## Consequences\nq\n`

  test('the Decision section, up to the next heading', async () => {
    expect(decision(ADR('Accepted', 'A dict.'))?.trim()).toBe('A dict.')
    expect(decision('# T\n\nno sections\n')).toBeUndefined()
  })

  test('accepted is read from the body or the frontmatter, proposed is not', async () => {
    expect(isAccepted(ADR('Accepted', 'x'))).toBe(true)
    expect(isAccepted('---\nstatus: accepted\n---\n# T\n')).toBe(true)
    expect(isAccepted('**Status:** accepted\n')).toBe(true)
    expect(isAccepted(ADR('Proposed', 'x'))).toBe(false)
  })

  test('the ADRs a record says it supersedes or is superseded by', async () => {
    expect(supersedes('Superseded by [ADR-0091](0091-x.md). Supersedes ADR-0012. Unlike silica-internal ADR-0043.'))
      .toEqual(['0091', '0012'])
  })
})

describe('the docs reminder after a write', () => {
  const ADR = `${ROOT}/docs/adr/0001-the-ask-rides-a-mod.md`
  const ADR_TEXT = '---\ndocuments:\n- silica_core/onboarding/guidance.py\nimplementation: partial\nimplemented_in: [hooks/register.ts, silica_core/skills/, "5619919"]\n---\n\n# ADR-0001\n'

  // beneath the plugin: a session in ROOT (adopted or not, docs/ there or not),
  // one ADR, and the tools answering with the record core gives them
  function session(on: On, opts: { docs?: boolean; adopted?: boolean } = {}) {
    const docs = opts.docs ?? true
    const adopted = opts.adopted ?? true
    on('session.root', () => ({ value: ROOT }))
    on('fs.exists', ($, e) => ({ value: (docs && e.path === `${ROOT}/docs`) || (adopted && e.path === `${ROOT}/vault.yaml`) }))
    on('fs.list', ($, e) => (docs && e.path === `${ROOT}/docs/adr`
      ? { value: [{ name: ADR.split('/').at(-1)!, kind: 'file', size: 1, mtimeMs: 0, isLink: false }] }
      : { deny: 'ENOENT' }) as any)
    on('fs.read', ($, e) => (docs && e.path === ADR ? { value: ADR_TEXT } : { deny: 'ENOENT' }))
    on('turn.start', ($, e) => ({ turnId: e.turnId }))
    on('tool.call', ($, e: any) => ({
      text: 'ok',
      result: e.tool === 'Write'
        ? { type: e.created ? 'create' : 'update', filePath: e.file_path, content: e.content, structuredPatch: patch(e.lines ?? 0), originalFile: null }
        : { filePath: e.file_path, structuredPatch: patch(e.lines ?? 0) },
    }) as any)
  }

  // a hunk of n changed lines, half removed and half added
  const patch = (n: number) =>
    [{ oldStart: 1, oldLines: n, newStart: 1, newLines: n, lines: Array.from({ length: n }, (_, i) => (i % 2 ? '+x' : '-x')) }]

  // `lines` and `created` ride beside the tool's arguments for the fake core above
  const edit = ($: any, path: string, lines: number) =>
    $.tool.call({ tool: 'Edit', file_path: `${ROOT}/${path}`, old_string: 'a', new_string: 'b', lines })
  const write = ($: any, path: string, created: boolean) =>
    $.tool.call({ tool: 'Write', file_path: `${ROOT}/${path}`, content: 'x\n', created, lines: 2 })
  const turn = ($: any, id: string) => $.turn.start({ text: 'go', turnId: id })

  const nudged = (r: any) => (r.context ?? []).filter((c: string) => c.startsWith("silica-core: this turn's writes"))

  test('a small edit gets nothing', async ($, on) => {
    session(on)
    await turn($, 't1')
    expect(nudged(await edit($, 'src/app.py', 4))).toEqual([])
  })

  test('edits adding up to the threshold get the reminder once, on the one that crosses it', async ($, on) => {
    session(on)
    await turn($, 't1')
    expect(nudged(await edit($, 'src/app.py', 20))).toEqual([])
    const crossing = nudged(await edit($, 'src/db.py', 20))
    expect(crossing.length).toBe(1)
    expect(crossing[0]).toContain('src/app.py')
    expect(crossing[0]).toContain('src/db.py')
    expect(nudged(await edit($, 'src/db.py', 40))).toEqual([])
  })

  test('a new file gets the reminder', async ($, on) => {
    session(on)
    await turn($, 't1')
    expect(nudged(await write($, 'src/new_module.py', true)).length).toBe(1)
  })

  test('a manifest gets the reminder', async ($, on) => {
    session(on)
    await turn($, 't1')
    expect(nudged(await edit($, 'pyproject.toml', 2)).length).toBe(1)
  })

  test('a file an ADR lists in implemented_in gets the reminder naming that ADR', async ($, on) => {
    session(on)
    await turn($, 't1')
    const r = nudged(await edit($, 'hooks/register.ts', 2))
    expect(r.length).toBe(1)
    expect(r[0]).toContain('docs/adr/0001-the-ask-rides-a-mod.md')
    // an accepted decision is never rewritten: a change that reverses it gets a new ADR
    expect(r[0]).toContain('supersede')
  })

  test('a file an ADR lists under documents gets the reminder too', async ($, on) => {
    session(on)
    await turn($, 't1')
    expect(nudged(await edit($, 'silica_core/onboarding/guidance.py', 2))[0]).toContain('0001')
  })

  test('an ADR entry naming a folder covers the files under it', async ($, on) => {
    session(on)
    await turn($, 't1')
    expect(nudged(await edit($, 'silica_core/skills/diagram/SKILL.md', 2))[0]).toContain('0001')
  })

  test('tests do not count', async ($, on) => {
    session(on)
    await turn($, 't1')
    expect(nudged(await edit($, 'tests/test_app.py', 200))).toEqual([])
    expect(nudged(await write($, 'hooks/register.test.ts', true))).toEqual([])
  })

  test('a turn that already wrote under docs/ gets nothing', async ($, on) => {
    session(on)
    await turn($, 't1')
    await edit($, 'docs/adr/0001-the-ask-rides-a-mod.md', 2)
    expect(nudged(await write($, 'src/new_module.py', true))).toEqual([])
  })

  test('the next turn starts over', async ($, on) => {
    session(on)
    await turn($, 't1')
    expect(nudged(await write($, 'src/a.py', true)).length).toBe(1)
    await turn($, 't2')
    expect(nudged(await write($, 'src/b.py', true)).length).toBe(1)
  })

  test('a folder with no docs/ gets nothing', async ($, on) => {
    session(on, { docs: false })
    await turn($, 't1')
    expect(nudged(await write($, 'src/new_module.py', true))).toEqual([])
  })

  test('a folder silica-core init never adopted gets nothing', async ($, on) => {
    session(on, { adopted: false })
    await turn($, 't1')
    expect(nudged(await write($, 'src/new_module.py', true))).toEqual([])
  })

  test('a subagent write gets nothing', async ($, on) => {
    session(on)
    await turn($, 't1')
    const r = await $.tool.call({ tool: 'Write', file_path: `${ROOT}/src/x.py`, content: 'x', agentId: 'a1', created: true } as any)
    expect(nudged(r)).toEqual([])
  })

  test('the tool result passes through untouched', async ($, on) => {
    session(on)
    await turn($, 't1')
    const r: any = await write($, 'src/new_module.py', true)
    expect(r.text).toBe('ok')
    expect(r.result.type).toBe('create')
  })
})

type Git = { shallow?: boolean; shas?: string[]; docsLog?: string; codeLog?: string }

// beneath the plugin: a repo of `files` (root-relative path to text, mtimes in
// ms), git answering from `git`, and Edit and Write applying what they are given
function world(on: On, files: Record<string, string>, opts: { git?: Git; mtimes?: Record<string, number> } = {}) {
  const fs = new Map(Object.entries(files).map(([p, t]) => [`${ROOT}/${p}`, t]))
  const isDir = (p: string) => [...fs.keys()].some(f => f.startsWith(`${p.replace(/\/$/, '')}/`))
  const git = opts.git ?? {}
  const runs: string[][] = []
  on('session.root', () => ({ value: ROOT }))
  on('env.get', () => ({ value: undefined }))
  on('store.get', () => ({ value: undefined }))
  on('fs.exists', ($, e) => ({ value: fs.has(e.path) || isDir(e.path) }))
  on('fs.read', ($, e) => (fs.has(e.path) ? { value: fs.get(e.path)! } : { deny: 'ENOENT' }))
  on('fs.list', ($, e) => {
    const dir = (e.path ?? ROOT).replace(/\/$/, '')
    if (!isDir(dir)) return { deny: 'ENOENT' } as any
    const names = new Map<string, 'file' | 'dir'>()
    for (const f of fs.keys()) if (f.startsWith(`${dir}/`)) {
      const [head, ...rest] = f.slice(dir.length + 1).split('/')
      names.set(head!, rest.length ? 'dir' : 'file')
    }
    return { value: [...names].map(([name, kind]) => ({ name, kind, size: 1, mtimeMs: 0, isLink: false })) } as any
  })
  on('fs.stat', ($, e) => ({ value: { kind: fs.has(e.path) ? 'file' : 'dir', size: 1, isLink: false,
                                       mtimeMs: opts.mtimes?.[e.path.slice(ROOT.length + 1)] ?? 0 } }) as any)
  on('process.run', ($, e) => {
    const a = e.argv.slice(3)
    runs.push([...e.argv])
    const stdout = a[0] === 'rev-parse' ? (git.shallow ? 'true\n' : 'false\n')
      : a[0] === 'rev-list' ? (git.shas ?? []).join('\n')
      : a.includes('docs/adr') ? (git.docsLog ?? '')
      : a.some(x => x.startsWith('--since=')) ? (git.codeLog ?? '')
      : ''
    return { value: { exitCode: 0, stdout, stderr: '', isStdoutTruncated: false, isStderrTruncated: false } }
  })
  on('turn.start', ($, e) => ({ turnId: e.turnId }))
  on('tool.call', ($, e: any) => {
    const before = fs.get(e.file_path) ?? null
    fs.set(e.file_path, e.tool === 'Write' ? e.content : e.after)
    return { text: 'ok', result: { filePath: e.file_path, originalFile: before, structuredPatch: [],
                                   ...(e.tool === 'Write' ? { type: before === null ? 'create' : 'update', content: e.content } : {}) } } as any
  })
  on('classic.Stop', () => ({}))
  on('command.register', ($, e) => ({ value: { command: e.name } }))
  on('command.run', () => ({ text: '' }))
  on('session.start', ($, e) => ({ cwd: e.cwd }))
  on('ui.render', ($, e) => h($.ui.resolve(e).Box, {}) as any)
  return { runs }
}

// a git log as `--format=@%ct --name-only` prints it
const log = (...commits: [number, ...string[]][]) =>
  commits.map(([t, ...names]) => `@${t}\n\n${names.join('\n')}\n`).join('\n')

const turn = ($: any, id = 't1') => $.turn.start({ text: 'go', turnId: id })
const stop = ($: any, active = false) => $.classic.Stop({ stop_hook_active: active } as any)
const writeDoc = ($: any, rel: string, content: string) =>
  $.tool.call({ tool: 'Write', file_path: `${ROOT}/${rel}`, content } as any)
const editDoc = ($: any, rel: string, after: string) =>
  $.tool.call({ tool: 'Edit', file_path: `${ROOT}/${rel}`, old_string: 'a', new_string: 'b', after } as any)
const status = ($: any) => $.command.run({ command: 'silica-docs', args: '', origin: { kind: 'composer' },
                                            presentation: { isFullscreen: false, columns: 80 } })

const ADR1 = 'docs/adr/0001-dict-cache.md'
const adr = (status: string, decided: string, fm = 'implementation: implemented\nimplemented_in: [src/cache.py]') =>
  `---\n${fm}\n---\n\n# ADR-0001\n\n- **Status:** ${status} (2026-10-08)\n\n## Decision\n${decided}\n\n## Consequences\nq\n`
const REPO = { 'vault.yaml': '', 'src/cache.py': 'x', [ADR1]: adr('Accepted', 'A dict, no eviction.'), 'docs/plans/p.md': '# plan\n' }

describe('the docs lint at the end of a turn', () => {
  test('a turn that wrote no doc ends as it would', async ($, on) => {
    world(on, REPO)
    await turn($)
    expect((await stop($)).block).toBeUndefined()
  })

  test('a broken relative link blocks the end, naming the doc and the target', async ($, on) => {
    world(on, REPO)
    await turn($)
    await writeDoc($, 'docs/plans/p.md', '# plan\n\nSee [x](missing.md).\n')
    const block = (await stop($)).block!
    expect(block).toContain('docs/plans/p.md')
    expect(block).toContain('missing.md')
  })

  test('a folder silica-core init never adopted is not linted', async ($, on) => {
    const { 'vault.yaml': _, ...unadopted } = REPO
    world(on, unadopted)
    await turn($)
    await writeDoc($, 'docs/plans/p.md', '# plan\n\nSee [x](missing.md).\n')
    expect((await stop($)).block).toBeUndefined()
  })

  test('a link that resolves, or sits in code, passes', async ($, on) => {
    world(on, REPO)
    await turn($)
    await writeDoc($, 'docs/plans/p.md', '# plan\n\n[c](../adr/0001-dict-cache.md) and `[x](missing.md)`\n')
    expect((await stop($)).block).toBeUndefined()
  })

  test('a code path under a top-level folder of the repo that is not there blocks; one outside it passes', async ($, on) => {
    world(on, REPO)
    await turn($)
    await writeDoc($, 'docs/plans/p.md', '`src/gone.py`, `elsewhere/x.py` and `src/cache.py:3`\n')
    const block = (await stop($)).block!
    expect(block).toContain('src/gone.py')
    expect(block).not.toContain('elsewhere/x.py')
    expect(block).not.toContain('src/cache.py')
  })

  test('a record written this turn is held to its implementation state', async ($, on) => {
    world(on, REPO)
    await turn($)
    await writeDoc($, 'docs/adr/0002-lru.md', adr('Accepted', 'LRU.', 'implementation: implemented\nimplemented_in: [src/gone.py]'))
    const block = (await stop($)).block!
    expect(block).toContain('docs/adr/0002-lru.md')
    expect(block).toContain('src/gone.py')
  })

  test('an accepted ADR whose Decision changed is named, and supersession is offered, not imposed', async ($, on) => {
    world(on, REPO)
    await turn($)
    await editDoc($, ADR1, adr('Accepted', 'An LRU dict of 128 entries.'))
    const block = (await stop($)).block!
    expect(block).toContain(ADR1)
    expect(block).toContain('Decision')
    expect(block).toContain('supersed')
    expect(block).toContain('clarif')
    expect(block).toContain('Superseded by')
  })

  test('the same change to a proposed ADR passes', async ($, on) => {
    world(on, { ...REPO, [ADR1]: adr('Proposed', 'A dict.') })
    await turn($)
    await editDoc($, ADR1, adr('Proposed', 'An LRU dict.'))
    expect((await stop($)).block).toBeUndefined()
  })

  test('a supersession that names an ADR which does not exist blocks', async ($, on) => {
    world(on, REPO)
    await turn($)
    await writeDoc($, 'docs/adr/0002-lru.md', '# ADR-0002\n\nSupersedes ADR-0009.\n')
    expect((await stop($)).block).toContain('ADR-0009')
  })

  test('two ADRs with one number block', async ($, on) => {
    world(on, REPO)
    await turn($)
    await writeDoc($, 'docs/adr/0001-other.md', '# ADR-0001\n')
    expect((await stop($)).block).toContain('0001')
  })

  test('the same problems a second time end the turn', async ($, on) => {
    world(on, REPO)
    await turn($)
    await writeDoc($, 'docs/plans/p.md', '[x](missing.md)\n')
    expect((await stop($)).block).toBeDefined()
    expect((await stop($, true)).block).toBeUndefined()
  })

  test('a fix that leaves a new problem gets one more block, and never a third', async ($, on) => {
    world(on, REPO)
    await turn($)
    await writeDoc($, 'docs/plans/p.md', '[x](missing.md)\n')
    expect((await stop($)).block).toContain('missing.md')
    await writeDoc($, 'docs/plans/p.md', '[x](other.md)\n')
    expect((await stop($, true)).block).toContain('other.md')
    await writeDoc($, 'docs/plans/p.md', '[x](third.md)\n')
    expect((await stop($, true)).block).toBeUndefined()
  })

  test('the next turn starts over', async ($, on) => {
    world(on, REPO)
    await turn($, 't1')
    await writeDoc($, 'docs/plans/p.md', '[x](missing.md)\n')
    await turn($, 't2')
    expect((await stop($)).block).toBeUndefined()
  })
})

describe('the docs report', () => {
  const fm = (refs: string) => `implementation: implemented\nimplemented_in: [${refs}]`
  const RECORDS = {
    'vault.yaml': '', 'src/cache.py': 'x', 'src/hub.py': 'x', 'src/b.py': 'x',
    'docs/adr/0001-a.md': adr('Accepted', 'a', fm('src/cache.py, src/hub.py, abc1234')),
    'docs/adr/0002-b.md': adr('Accepted', 'b', fm('src/b.py, src/hub.py, src/gone.py')),
    'docs/adr/0003-c.md': adr('Accepted', 'c', fm('src/hub.py')),
  }
  const GIT: Git = {
    shas: ['fff0000aaaa'],
    docsLog: log([100, 'docs/adr/0001-a.md', 'docs/adr/0002-b.md', 'docs/adr/0003-c.md']),
    codeLog: log([300, 'src/hub.py'], [200, 'src/cache.py'], [50, 'src/b.py']),
  }

  test('/silica-docs lists the problems and the drift, and hands them to the model', async ($, on) => {
    world(on, RECORDS, { git: GIT })
    const r = await status($)
    expect(r.text).toContain('abc1234')
    expect(r.text).toContain('src/gone.py')
    expect(r.text).toContain('docs/adr/0001-a.md: 1 commit')
    expect(r.context?.[0]).toBe(r.text)
  })

  test('commits to a file three records list are not drift, nor commits before the record', async ($, on) => {
    world(on, RECORDS, { git: GIT })
    const r = await status($)
    expect(r.text).not.toMatch(/0002-b\.md: \d+ commit/)
    expect(r.text).not.toMatch(/0003-c\.md: \d+ commit/)
  })

  test('a record git does not track is anchored at its mtime', async ($, on) => {
    world(on, RECORDS, { git: { ...GIT, docsLog: '' }, mtimes: { 'docs/adr/0001-a.md': 250_000, 'docs/adr/0002-b.md': 10_000 } })
    const r = await status($)
    expect(r.text).not.toMatch(/0001-a\.md: \d+ commit/)
    expect(r.text).toContain('docs/adr/0002-b.md: 1 commit')
  })

  test('a shallow clone does not check commits', async ($, on) => {
    world(on, RECORDS, { git: { ...GIT, shallow: true } })
    expect((await status($)).text).not.toContain('abc1234')
  })

  test('a folder with no records has nothing to report', async ($, on) => {
    world(on, { 'vault.yaml': '', 'src/a.py': 'x' })
    const r = await status($)
    expect(r.text).toContain('nothing to report')
    expect(r.context ?? []).toEqual([])
  })

  test('an interactive session scans once it has started; the band shows the counts and Hide hides it', async ($, on) => {
    world(on, RECORDS, { git: GIT })
    const clock = mock.clock(on)
    await $.session.start({ cwd: ROOT, surface: 'terminal', isInteractive: true })
    await clock.settle()
    for (const surface of ['terminal', 'desktop'] as const) {
      const ui = await $.ui.mount({ plugin: 'silica-core', surface, component: 'AbovePrompt', props: BAND })
      expect(await ui.find({ text: /2 problems · 1 drifting/ })).toBeDefined()
      await ui.unmount()
    }
    const ui = await $.ui.mount({ plugin: 'silica-core', surface: 'terminal', component: 'AbovePrompt', props: BAND })
    await ui.press({ key: 'hide-docs' })
    expect(await ui.find({ text: /problems/ })).toBeUndefined()
  })

  test('a session nobody can answer runs no git', async ($, on) => {
    const { runs } = world(on, RECORDS, { git: GIT })
    const clock = mock.clock(on)
    await $.session.start({ cwd: ROOT, surface: null, isInteractive: false })
    await clock.settle()
    expect(runs).toEqual([])
  })

  test('a folder silica-core init never adopted runs no git at start', async ($, on) => {
    const { 'vault.yaml': _, ...unadopted } = RECORDS
    const { runs } = world(on, unadopted, { git: GIT })
    const clock = mock.clock(on)
    await $.session.start({ cwd: ROOT, surface: 'terminal', isInteractive: true })
    await clock.settle()
    expect(runs).toEqual([])
  })
})
