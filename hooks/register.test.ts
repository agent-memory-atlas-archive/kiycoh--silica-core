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
    on('fs.read', ($, e) => (e.path in files ? { value: files[e.path] } : { deny: 'ENOENT' }))
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
