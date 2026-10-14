import { describe, expect, test } from 'claude-code/testing'
import type { On } from 'claude-code'
import { NUDGE } from './register.ts'
import { GUIDANCE, START } from './guidance.ts'

const ROOT = '/work/repo'

// beneath the plugin: a session started in ROOT, vault.yaml there or not, and
// the bottom of prompt.submit echoing what entered
function session(on: On, adopted: boolean) {
  on('session.root', () => ({ value: ROOT }))
  on('fs.exists', ($, e) => ({ value: adopted && e.path === `${ROOT}/vault.yaml` }))
  on('prompt.submit', ($, e) => ({ text: e.text, context: e.context }))
}

const submit = ($: any, text: string) =>
  $.prompt.submit({ text, wait: false, origin: { kind: 'composer' } })

describe('the prompt nudge', () => {
  test('a question naming no identifier, in an adopted folder, gets the line', async ($, on) => {
    session(on, true)
    const r = await submit($, 'How does the server decide which folder it indexes?')
    expect(r.text).toBe('How does the server decide which folder it indexes?')
    expect(r.context).toEqual([NUDGE])
  })

  test('a question naming an identifier gets nothing', async ($, on) => {
    session(on, true)
    const r = await submit($, 'Where is root_gate called?')
    expect(r.context ?? []).toEqual([])
  })

  test('a statement gets nothing', async ($, on) => {
    session(on, true)
    const r = await submit($, 'Commit the change')
    expect(r.context ?? []).toEqual([])
  })

  test('a folder silica-core init never adopted gets nothing', async ($, on) => {
    session(on, false)
    const r = await submit($, 'How does the server decide which folder it indexes?')
    expect(r.context ?? []).toEqual([])
  })
})

describe('the guidance section', () => {
  const SEARCH = 'mcp__plugin_silica-core_silica-core__silica_search'
  const ENGINE = [{ id: 'intro', text: 'You are Claude Code.', scope: 'shared' as const }]
  const req = (tools: string[]) =>
    ({ model: 'claude-sonnet-5-5', promptModel: 'claude-sonnet-5-5', surfaces: [], tools, outputStyle: null, traits: [] })

  // beneath the plugin: a session started in ROOT, its environment, the files
  // a read reaches, and the engine's own system prompt
  function compose(on: On, opts: { adopted: boolean; env?: Record<string, string>; files?: Record<string, string> }) {
    const env = opts.env ?? { HOME: '/home/u' }
    const files = opts.files ?? {}
    on('session.root', () => ({ value: ROOT }))
    on('fs.exists', ($, e) => ({ value: opts.adopted && e.path === `${ROOT}/vault.yaml` }))
    on('env.get', ($, e) => ({ value: env[e.name] }))
    on('fs.read', ($, e) => (e.path in files ? { value: files[e.path]! } : { deny: 'ENOENT' }))
    on('prompt.compose', () => ({ sections: ENGINE }))
  }

  test('an adopted folder whose request offers silica_search gets the block last, as session', async ($, on) => {
    compose(on, { adopted: true })
    const r = await $.prompt.compose(req(['Bash', SEARCH]))
    expect(r.sections).toEqual([...ENGINE, { id: 'silica-core:guidance', text: GUIDANCE, scope: 'session' }])
  })

  test('a folder silica-core init never adopted gets nothing', async ($, on) => {
    compose(on, { adopted: false })
    expect((await $.prompt.compose(req(['Bash', SEARCH]))).sections).toEqual(ENGINE)
  })

  test('a request without silica_search (a subagent with other tools) gets nothing', async ($, on) => {
    compose(on, { adopted: true })
    expect((await $.prompt.compose(req(['Bash', 'Read']))).sections).toEqual(ENGINE)
  })

  test('a user-level CLAUDE.md that already holds the block gets nothing', async ($, on) => {
    compose(on, { adopted: true, files: { '/home/u/.claude/CLAUDE.md': `# mine\n${START}\n...\n` } })
    expect((await $.prompt.compose(req([SEARCH]))).sections).toEqual(ENGINE)
  })

  test('CLAUDE_CONFIG_DIR is where that CLAUDE.md is read, as setup writes it', async ($, on) => {
    compose(on, { adopted: true, env: { HOME: '/home/u', CLAUDE_CONFIG_DIR: '/cfg' },
                  files: { '/cfg/CLAUDE.md': `${START}\n...\n`, '/home/u/.claude/CLAUDE.md': '# mine\n' } })
    expect((await $.prompt.compose(req([SEARCH]))).sections).toEqual(ENGINE)
  })
})

describe('the index offer', () => {
  const HOME = '/home/u'
  // the plugin root, as the module finds it: the folder that holds hooks/
  const PLUGIN_ROOT = decodeURIComponent(new URL('..', (import.meta as { url: string }).url).pathname).replace(/\/$/, '')
  // the launch mcp.json gives the server, --frozen included (434c529), so init
  // and the server sync one environment from uv.lock
  const INIT = ['uv', 'run', '--frozen', '--project', PLUGIN_ROOT, '--extra', 'mcp', '--extra', 'dense', 'silica-core', 'init']
  const BAND = { hasSurvey: false, isWorking: false, maxRows: 10, bodyColumns: 80, scroll: { offset: 0, bodyRows: 10 }, view: {} }

  // beneath the plugin: a folder (adopted or not), HOME, a store kept in
  // memory, and `silica-core init` answering with `exitCode`
  function folder(on: On, opts: { root?: string; adopted?: boolean; exitCode?: number } = {}) {
    const root = opts.root ?? ROOT
    const store = new Map<string, unknown>()
    const runs: { argv: readonly string[]; cwd?: string }[] = []
    const commands: string[] = []
    on('session.root', () => ({ value: root }))
    on('fs.exists', ($, e) => ({ value: !!opts.adopted && e.path === `${root}/vault.yaml` }))
    on('env.get', ($, e) => ({ value: e.name === 'HOME' ? HOME : undefined }))
    on('store.get', ($, e) => ({ value: store.get(e.key) }))
    on('store.set', ($, e) => { store.set(e.key, e.value); return { value: undefined } })
    on('process.run', ($, e) => {
      runs.push({ argv: e.argv, cwd: e.init?.cwd })
      return { value: { exitCode: opts.exitCode ?? 0, stdout: '{"docs": 3}', stderr: 'no uv', isStdoutTruncated: false, isStderrTruncated: false } }
    })
    on('command.register', ($, e) => { commands.push(e.name); return { value: { command: e.name } } })
    on('ui.toast', () => ({ value: undefined }))
    on('session.start', ($, e) => ({ cwd: e.cwd }))
    on('command.run', () => ({ text: '' }))
    on('ui.render', ($, e) => h($.ui.resolve(e).Box, {}) as any)  // the engine's band: empty
    return { runs, commands }
  }

  const start = ($: any, isInteractive = true) =>
    $.session.start({ cwd: ROOT, surface: isInteractive ? 'terminal' : null, isInteractive })
  const band = ($: any, surface: 'terminal' | 'desktop') =>
    $.ui.mount({ plugin: 'silica-core', surface, component: 'AbovePrompt', props: BAND })

  test('an unadopted folder is offered, and Index runs silica-core init there, then the offer goes', async ($, on) => {
    const { runs } = folder(on)
    for (const surface of ['terminal', 'desktop'] as const) {
      await start($)
      const ui = await band($, surface)
      expect(await ui.find({ key: 'index' })).toBeDefined()
      await ui.press({ key: 'index' })
      expect(runs.at(-1)).toEqual({ argv: INIT, cwd: ROOT })
      expect(await ui.find({ key: 'index' })).toBeUndefined()
      await ui.unmount()
    }
  })

  test('an adopted folder is offered nothing', async ($, on) => {
    folder(on, { adopted: true })
    await start($)
    expect(await (await band($, 'terminal')).find({ key: 'index' })).toBeUndefined()
  })

  test('HOME itself is never offered', async ($, on) => {
    folder(on, { root: HOME })
    await start($)
    expect(await (await band($, 'terminal')).find({ key: 'index' })).toBeUndefined()
  })

  test('a session nobody can answer is offered nothing', async ($, on) => {
    folder(on)
    await start($, false)
    expect(await (await band($, 'terminal')).find({ key: 'index' })).toBeUndefined()
  })

  test('Not here hides the offer and the next session in that folder remembers it', async ($, on) => {
    const { runs } = folder(on)
    await start($)
    const ui = await band($, 'terminal')
    await ui.press({ key: 'dismiss' })
    expect(await ui.find({ key: 'index' })).toBeUndefined()
    await start($)
    expect(await (await band($, 'terminal')).find({ key: 'index' })).toBeUndefined()
    expect(runs).toEqual([])
  })

  test('a failed init puts the offer back', async ($, on) => {
    folder(on, { exitCode: 1 })
    await start($)
    const ui = await band($, 'terminal')
    await ui.press({ key: 'index' })
    expect(await ui.find({ key: 'index' })).toBeDefined()
  })

  test('/silica-init adopts the folder from the prompt', async ($, on) => {
    const { runs, commands } = folder(on)
    await start($)
    expect(commands).toContain('silica-init')
    const r = await $.command.run({ command: 'silica-init', args: '', origin: { kind: 'composer' },
                                     presentation: { isFullscreen: false, columns: 80 } })
    expect(runs.at(-1)).toEqual({ argv: INIT, cwd: ROOT })
    expect(r.text).toContain(ROOT)
  })
})
