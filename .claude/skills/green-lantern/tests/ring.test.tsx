import { expect, test } from 'claude-code/testing'

const PANE = {
  plugin: 'green-lantern',
  component: 'Pane',
  requestId: 'ring-console',
  props: {
    title: '💚 Ring',
    isFocused: true,
    bodyColumns: 50,
    placement: 'dock',
    scroll: { offset: 0, bodyRows: 30 },
    view: {},
  },
} as const

test('the ring menu lists old sessions and sends them a message', async ($, on) => {
  const calls: { tool: string; args: Record<string, unknown> }[] = []
  on('mcp.call', ($, e) => {
    calls.push({ tool: e.tool, args: e.args })
    const text =
      e.tool === 'list_sessions'
        ? JSON.stringify({ data: [{ id: 'session_old1', title: 'Old plan' }] })
        : JSON.stringify({ ok: true })
    return { value: { content: [{ type: 'text', text }], isError: false } }
  })

  on('session.id', () => ({ value: 'session_here' }))
  on('session.messages', () => ({ value: [{ role: 'user', text: 'plan the landing page', toolUses: [] }] }))

  for (const surface of ['terminal', 'desktop'] as const) {
    calls.length = 0
    const ui = await $.ui.mount({ ...PANE, surface })
    await ui.press({ key: 'ring-menu' })
    expect(await ui.find({ key: 'opt-new' })).toBeDefined()

    await ui.press({ key: 'opt-link' })
    expect(await ui.find({ key: 'pick-session' })).toBeDefined()

    await ui.input({ key: 'link-message', text: 'continue the plan' })
    const sent = calls.find(c => c.tool === 'send_message')
    expect(sent?.args.session_id).toBe('session_old1')
    expect(String(sent?.args.message)).toContain('continue the plan')
    expect(String(sent?.args.message)).toContain('session_here')

    await ui.press({ key: 'back-link' })
    await ui.press({ key: 'opt-new' })
    await ui.input({ key: 'new-prompt', text: 'build a landing page' })
    expect(calls.some(c => c.tool === 'create_session')).toBe(true)

    await ui.press({ key: 'ring-menu' })
    await ui.unmount()
  }
})

test('the phone gets the lantern, the menu button and session picking', async ($, on) => {
  const calls: { tool: string; args: Record<string, unknown> }[] = []
  on('mcp.call', ($, e) => {
    calls.push({ tool: e.tool, args: e.args })
    const text =
      e.tool === 'list_sessions'
        ? JSON.stringify({ data: [{ id: 'session_a', title: 'A' }, { id: 'session_b', title: 'B' }] })
        : JSON.stringify({ ok: true })
    return { value: { content: [{ type: 'text', text }], isError: false } }
  })
  on('session.id', () => ({ value: 'session_here' }))
  on('session.messages', () => ({ value: [] }))

  const ui = await $.ui.mount({ ...PANE, surface: 'mobile' })
  expect(await ui.find({ type: 'Svg' })).toBeDefined()
  await ui.press({ key: 'ring-menu' })
  await ui.press({ key: 'opt-link' })
  await ui.press({ key: 'pick-session_b' })

  const ran = await $.command.run({
    command: 'ring-send',
    args: 'hello from the phone',
    origin: { kind: 'bridge' },
    presentation: { isFullscreen: false, columns: 40 },
  })
  const sent = calls.find(c => c.tool === 'send_message')
  expect(sent?.args.session_id).toBe('session_b')
  expect(ran).toBeDefined()
  await ui.unmount()
})

test('replies on the phone open with the lantern; other blocks pass through', async ($, on) => {
  on('ui.render', ($, e) => {
    const { Text } = $.ui.resolve(e)
    return <Text>engine</Text>
  })

  const first = await $.ui.mount({
    plugin: 'green-lantern',
    surface: 'mobile',
    component: 'AssistantMessage',
    requestId: 'msg_1',
    props: { text: 'In brightest day', isFirstOfReply: true },
  })
  expect(await first.find({ type: 'Svg' })).toBeDefined()
  expect(await first.find({ type: 'Markdown', text: /In brightest day/ })).toBeDefined()
  await first.unmount()

  const later = await $.ui.mount({
    plugin: 'green-lantern',
    surface: 'mobile',
    component: 'AssistantMessage',
    requestId: 'msg_2',
    props: { text: 'more text', isFirstOfReply: false },
  })
  expect(await later.find({ type: 'Svg' })).toBeUndefined()
  expect(await later.find({ type: 'Text', text: 'engine' })).toBeDefined()
  await later.unmount()

  const desktop = await $.ui.mount({
    plugin: 'green-lantern',
    surface: 'desktop',
    component: 'AssistantMessage',
    requestId: 'msg_3',
    props: { text: 'desk', isFirstOfReply: true },
  })
  expect(await desktop.find({ type: 'Svg' })).toBeUndefined()
  await desktop.unmount()

  const card = await $.ui.mount({
    plugin: 'green-lantern',
    surface: 'mobile',
    component: 'CommandOutput',
    requestId: 'cmd_1',
    props: { command: 'ring', args: '', text: 'Ring console opened.', isErrored: false },
  })
  expect(await card.find({ type: 'Text', text: 'Ring console opened.' })).toBeDefined()
  await card.unmount()
})
