# green-lantern

A Claude Code mod with a Green Lantern theme:

- **Header band above the prompt:** the lantern, "GREEN LANTERN CORPS · Sector 2814" and the oath.
- **Spinner and turn line:** they speak the Corps' language ("Charging the ring", "Channeled for 12s").
- **Ring console:** a pane docked on the right with a **💍 Menu** button at its top. The menu offers:
  1. **New session:** starts a new cloud session with your task.
  2. **Link & message an old session:** pick one of your sessions and send it a message, even while it is running.

  Both can attach this session's info: its id and its last 6 messages.

Open the console any time with `/ring`.

## Install

```
/plugin install green-lantern --marketplace braingood632-coder/cloud
```

Answer `y` to add the marketplace, then pick a scope.

## Notes

- The pane docks on the right in the fullscreen terminal from 110 columns. Below that it shows above the prompt.
- New sessions and session messages use the `claude-code-remote` MCP server, which cloud sessions have.

## Test

```
claude plugin validate green-lantern
claude plugin test green-lantern
```
