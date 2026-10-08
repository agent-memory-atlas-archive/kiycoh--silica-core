import type { EngineInterface, Register } from 'claude-code'
import { GUIDANCE, START } from './guidance.ts'

// The ask of docs/adr/0001, lever 1: the UserPromptSubmit hook removed in
// 0573f2e, back in-process and only where `silica-core init` left vault.yaml.
// QUESTION and IDENTIFIER are its two regexes as measured on 2026-09-10.
const QUESTION = /\?|^\s*(what|where|how|why|which|when|who|does|do|is|are|can|list|explain|describe|find)\b/i
// a backtick, snake_case, camelCase, a path or an extension, `::`, `#L`: the
// prompt names something grep can look for
const IDENTIFIER = /`|\b[A-Za-z]\w*_\w+\b|\b[A-Za-z]*[a-z][A-Z]\w*\b|\/\w|\.\w{1,4}\b|::|#L\d/

export const NUDGE = 'silica-core: this question names no identifier. Before any grep (a Grep tool, or grep or rg in a shell), Glob or Read, state whether silica_search applies (yes or no); if yes, call it first with the question as `query`.'

// ponytail: the folder the session started in; SILICA_VAULT pointing elsewhere is not seen (ADR-0001)
const adopted = async ($: EngineInterface) => $.fs.exists(`${await $.session.root()}/vault.yaml`)

// Where `silica-core setup claude` writes its block: guidance.claude_md_path().
async function claudeMdHoldsTheBlock($: EngineInterface): Promise<boolean> {
  const dir = (await $.env.get('CLAUDE_CONFIG_DIR'))
    || `${(await $.env.get('HOME')) ?? (await $.env.get('USERPROFILE'))}/.claude`
  const text = await $.fs.read(`${dir}/CLAUDE.md`).catch(() => '')
  return String(text).includes(START)
}

export const register: Register = (on) => {
  on('prompt.submit', async ($, e, next) => {
    const text = e.text.trim()
    if (!text || !QUESTION.test(text) || IDENTIFIER.test(text)) return next(e)
    if (!(await adopted($))) return next(e)
    return next({ ...e, context: [...(e.context ?? []), NUDGE] })
  })

  // Lever 3: the block the bench measured through --append-system-prompt-file,
  // last in the system prompt, where the request offers silica_search
  on('prompt.compose', async ($, e, next) => {
    const composed = await next(e)
    if (!e.tools.some(t => t.endsWith('__silica_search'))) return composed
    if (!(await adopted($)) || (await claudeMdHoldsTheBlock($))) return composed
    return { sections: [...composed.sections, { id: 'silica-core:guidance', text: GUIDANCE, scope: 'session' }] }
  })
}
