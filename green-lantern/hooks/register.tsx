import { atom, read, update } from 'claude-code'
import type { EngineInterface, Register } from 'claude-code'

import type { RingSession, RingView } from '../types'

const PANE = 'ring-console'
const REMOTE = 'claude-code-remote'
const GREEN = '#3ce26b'
const OATH = 'In brightest day, in blackest night, no evil shall escape my sight.'
const SPINNER_WORDS = ['Charging the ring', 'Constructing', 'Focusing will', 'Shaping', 'Channeling']

const view = atom({ plugin: 'green-lantern', key: 'view' } as const, 'closed' as RingView)
const sessions = atom({ plugin: 'green-lantern', key: 'sessions' } as const, [] as RingSession[])
const target = atom({ plugin: 'green-lantern', key: 'target' } as const, null as string | null)
const withContext = atom({ plugin: 'green-lantern', key: 'withContext' } as const, true)
const status = atom({ plugin: 'green-lantern', key: 'status' } as const, null as string | null)

const LANTERN_SVG =
  '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 40 40" width="40" height="40">' +
  '<rect x="6" y="3" width="28" height="5" fill="#3ce26b"/>' +
  '<circle cx="20" cy="22" r="11" fill="none" stroke="#3ce26b" stroke-width="5"/>' +
  '<rect x="6" y="35" width="28" height="4" fill="#3ce26b"/></svg>'

const LANTERN = ['▄▄▄▄▄▄▄', '█▀▀▀▀▀█', '█ ▄▄▄ █', '█ ▀▀▀ █', '▀█▄▄▄█▀']

// Text of an MCP tool result's text blocks, joined.
function textOf(result: { content?: readonly unknown[] }): string {
  return (result.content ?? [])
    .map(block => (block as { type?: string; text?: string }).type === 'text' ? (block as { text: string }).text : '')
    .join('\n')
}

// Pulls every { id: "session_…", title } object out of whatever list_sessions answered.
function parseSessions(raw: string): RingSession[] {
  const found: RingSession[] = []
  const walk = (node: unknown): void => {
    if (Array.isArray(node)) {
      node.forEach(walk)
    } else if (node && typeof node === 'object') {
      const obj = node as Record<string, unknown>
      if (typeof obj.id === 'string' && obj.id.startsWith('session_')) {
        found.push({ id: obj.id, title: typeof obj.title === 'string' && obj.title ? obj.title : obj.id })
      }
      Object.values(obj).forEach(walk)
    }
  }
  try {
    walk(JSON.parse(raw))
  } catch {
    for (const id of raw.match(/session_[A-Za-z0-9]+/g) ?? []) found.push({ id, title: id })
  }
  const seen = new Set<string>()
  return found.filter(s => !seen.has(s.id) && seen.add(s.id))
}

// What "my info" means: this session's id and the tail of its conversation.
async function contextBlock($: EngineInterface): Promise<string> {
  const id = await $.session.id()
  const messages = await $.session.messages()
  const tail = messages
    .slice(-6)
    .map(m => `${m.role === 'user' ? 'User' : 'Claude'}: ${m.text.slice(0, 600)}`)
    .join('\n\n')
  return `\n\n--- Context from session ${id} ---\n${tail || '(no messages yet)'}`
}

async function refreshSessions($: EngineInterface): Promise<void> {
  await update($, status, () => 'Scanning sector for sessions…')
  try {
    const result = await $.mcp.call(REMOTE, 'list_sessions', { limit: 20, mine: true })
    const found = parseSessions(textOf(result))
    await update($, sessions, () => found)
    await update($, target, current => current ?? found[0]?.id ?? null)
    await update($, status, () => (found.length ? `${found.length} sessions found.` : 'No sessions found.'))
  } catch (err) {
    await update($, status, () => `Could not list sessions: ${String(err)}`)
  }
}

async function createSession($: EngineInterface, prompt: string): Promise<void> {
  const text = prompt.trim()
  await update($, status, () => 'Forging a new session…')
  try {
    const body = text + (await read($, withContext) ? await contextBlock($) : '')
    const result = await $.mcp.call(REMOTE, 'create_session', {
      prompt: body,
      title: text.slice(0, 60) || 'Green Lantern session',
    })
    const id = parseSessions(textOf(result))[0]?.id
    await update($, status, () => (result.isError ? `Failed: ${textOf(result)}` : `New session ready${id ? `: ${id}` : ''}`))
    if (!result.isError) $.ui.toast('💚 New session created')
  } catch (err) {
    await update($, status, () => `Could not create session: ${String(err)}`)
  }
}

async function sendToSession($: EngineInterface, message: string): Promise<void> {
  const sessionId = await read($, target)
  if (!sessionId) {
    await update($, status, () => 'Pick a session first.')
    return
  }
  await update($, status, () => `Sending to ${sessionId}…`)
  try {
    const body = message.trim() + (await read($, withContext) ? await contextBlock($) : '')
    const result = await $.mcp.call(REMOTE, 'send_message', { session_id: sessionId, message: body })
    await update($, status, () => (result.isError ? `Failed: ${textOf(result)}` : `Sent to ${sessionId} ✓`))
    if (!result.isError) $.ui.toast('💚 Message delivered')
  } catch (err) {
    await update($, status, () => `Could not send: ${String(err)}`)
  }
}

export const register: Register = on => {
  on('session.start', async ($, e, next) => {
    await $.command.register({ name: 'ring', description: 'Open the Green Lantern ring console' })
    await $.command.register({ name: 'ring-new', description: 'Start a new session with this task', argumentHint: '<task>' })
    await $.command.register({ name: 'ring-send', description: 'Send a message to the session picked in /ring', argumentHint: '<message>' })
    void $.ui.open({ id: PANE, title: '💚 Ring' })
    return next(e)
  })

  on('command.run', { command: 'ring' }, async $ => {
    await $.ui.open({ id: PANE, title: '💚 Ring' })
    await update($, view, () => 'menu')
    return { text: 'Ring console opened.' }
  })

  // Typed forms of the console's actions, for surfaces with no Input (the phone).
  on('command.run', { command: 'ring-new' }, async ($, e) => {
    if (!e.args.trim()) return { text: 'Usage: /ring-new <task>' }
    await createSession($, e.args)
    return { text: (await read($, status)) ?? 'Done.' }
  })

  on('command.run', { command: 'ring-send' }, async ($, e) => {
    if (!e.args.trim()) return { text: 'Usage: /ring-send <message>' }
    await sendToSession($, e.args)
    return { text: (await read($, status)) ?? 'Done.' }
  })

  // The spinner and the closing line speak the Corps' language.
  on('ui.render', { component: 'Spinner' }, ($, e, next) => {
    const word = SPINNER_WORDS[e.props.word.length % SPINNER_WORDS.length] ?? 'Charging the ring'
    return next({ ...e, props: { ...e.props, word } })
  })

  on('ui.render', { component: 'TurnDuration' }, ($, e, next) => next({ ...e, props: { ...e.props, word: 'Channeled' } }))

  // The band above the prompt: the lantern, the Corps and the oath.
  on('ui.render', { component: 'AbovePrompt' }, async ($, e, next) => {
    if (e.props.hasSurvey) return next(e)
    const { Box, Text } = $.ui.resolve(e)
    return (
      <Box flexDirection="row" gap={2}>
        <Box flexDirection="column">
          {LANTERN.map(row => (
            <Text color={GREEN}>{row}</Text>
          ))}
        </Box>
        <Box flexDirection="column">
          <Text color={GREEN} bold>
            GREEN LANTERN CORPS · Sector 2814
          </Text>
          <Text color={GREEN}>{OATH}</Text>
          <Text dimColor>{e.props.isWorking ? 'Ring is charging…' : 'Ring at full power · /ring for the console'}</Text>
        </Box>
      </Box>
    )
  })

  // The ring console: a pane docked on the right, its menu button at the top right.
  on('ui.render', { component: 'Pane', requestId: PANE }, async ($, e) => {
    if (e.surface === 'mobile') {
      const { Box, Text, Button, Svg } = $.ui.resolve(e)
      const current = await read($, view)
      const note = await read($, status)
      const attach = await read($, withContext)
      const list = await read($, sessions)
      const chosen = await read($, target)

      return (
        <Box flexDirection="column" gap={1}>
          <Box flexDirection="row" justifyContent="space-between" alignItems="center">
            <Box flexDirection="row" gap={1} alignItems="center">
              <Svg source={LANTERN_SVG} alt="Green Lantern" width={5} height={3} />
              <Text color={GREEN} bold>GREEN LANTERN CORPS · 2814</Text>
            </Box>
            <Button
              key="ring-menu"
              label={current === 'closed' ? '💍 Menu' : '✕'}
              variant="primary"
              onPress={() => update($, view, v => (v === 'closed' ? 'menu' : 'closed'))}
            />
          </Box>
          <Text color={GREEN} italic>{OATH}</Text>
          {current === 'menu' && (
            <Box flexDirection="column" gap={1}>
              <Button key="opt-new" label="1. New session" onPress={() => update($, view, () => 'new')} />
              <Button
                key="opt-link"
                label="2. Link & message an old session"
                onPress={async () => {
                  await update($, view, () => 'link')
                  await refreshSessions($)
                }}
              />
            </Box>
          )}
          {current === 'new' && <Text>Type /ring-new followed by the task, then send.</Text>}
          {current === 'link' && (
            <Box flexDirection="column" gap={1}>
              {list.map(s => (
                <Button
                  key={`pick-${s.id}`}
                  label={`${s.id === chosen ? '● ' : '○ '}${s.title}`}
                  plain
                  onPress={() => update($, target, () => s.id)}
                />
              ))}
              <Button key="refresh" label="↻ Refresh list" plain onPress={() => refreshSessions($)} />
              <Text>Pick a session, then type /ring-send followed by your message.</Text>
            </Box>
          )}
          {(current === 'new' || current === 'link') && (
            <Box flexDirection="column" gap={1}>
              <Button
                key="toggle-context"
                label={attach ? '☑ Attach my session info' : '☐ Attach my session info'}
                plain
                onPress={() => update($, withContext, v => !v)}
              />
              <Button key="back" label="← Back" plain onPress={() => update($, view, () => 'menu')} />
            </Box>
          )}
          {note && <Text dimColor>{note}</Text>}
        </Box>
      )
    }
    const { Box, Text, Button, Input, Select } = $.ui.resolve(e)
    const current = await read($, view)
    const note = await read($, status)
    const attach = await read($, withContext)

    const header = (
      <Box flexDirection="row" justifyContent="flex-end">
        <Button
          key="ring-menu"
          label={current === 'closed' ? '💍 Menu' : '✕ Close'}
          variant="primary"
          onPress={() => update($, view, v => (v === 'closed' ? 'menu' : 'closed'))}
        />
      </Box>
    )

    const contextToggle = (
      <Button
        key="toggle-context"
        label={attach ? '☑ Attach my session info' : '☐ Attach my session info'}
        plain
        onPress={() => update($, withContext, v => !v)}
      />
    )

    let body = <Text color={GREEN} dimColor>Press 💍 Menu to use the ring.</Text>

    if (current === 'menu') {
      body = (
        <Box flexDirection="column" gap={1}>
          <Button key="opt-new" label="1. New session" hotkey="1" onPress={() => update($, view, () => 'new')} />
          <Button
            key="opt-link"
            label="2. Link & message an old session"
            hotkey="2"
            onPress={async () => {
              await update($, view, () => 'link')
              await refreshSessions($)
            }}
          />
        </Box>
      )
    } else if (current === 'new') {
      body = (
        <Box flexDirection="column" gap={1}>
          <Text color={GREEN} bold>New session</Text>
          <Input
            key="new-prompt"
            label="Task"
            placeholder="What should the new session do?"
            submitLabel="Create"
            autoFocus
            onSubmit={value => createSession($, value)}
          />
          {contextToggle}
          <Button key="back-new" label="← Back" plain onPress={() => update($, view, () => 'menu')} />
        </Box>
      )
    } else if (current === 'link') {
      const list = await read($, sessions)
      const chosen = await read($, target)
      body = (
        <Box flexDirection="column" gap={1}>
          <Text color={GREEN} bold>Link an old session</Text>
          {list.length > 0 ? (
            <Select
              key="pick-session"
              label="Session"
              options={list.map(s => ({ value: s.id, label: s.title }))}
              value={chosen ?? undefined}
              onSelect={value => update($, target, () => value)}
            />
          ) : (
            <Text dimColor>No sessions loaded.</Text>
          )}
          <Button key="refresh" label="↻ Refresh list" plain onPress={() => refreshSessions($)} />
          <Input
            key="link-message"
            label="Message"
            placeholder="e.g. continue the plan, and also…"
            submitLabel="Send"
            onSubmit={value => sendToSession($, value)}
          />
          {contextToggle}
          <Button key="back-link" label="← Back" plain onPress={() => update($, view, () => 'menu')} />
        </Box>
      )
    }

    return (
      <Box flexDirection="column" gap={1}>
        {header}
        {body}
        {note && <Text dimColor>{note}</Text>}
      </Box>
    )
  })
}
