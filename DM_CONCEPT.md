# Concept: gate ingestion on an @messtvbot mention

Idea from conversation on 2026-09-28: instead of (or alongside) trusting
every message in the channel, only treat a message as signage content if
it explicitly @-mentions the bot -- e.g. a channel member types:

    @messtvbot cake this Friday at 10am

Anything posted without the mention (casual chat, off-topic messages,
accidental image drops) is ignored, even though everyone can still post
in the channel. Solves the "avoid accidental non-announcement messages"
problem without needing a separate restricted-posters channel or an
author allow-list.

## Why this works

Bots with `chat:write` automatically get a normal, mentionable Slack
profile once they're a channel member (already required today for
`conversations.history` to see anything). When someone types `@messtvbot`
and Slack autocompletes it, the raw message text Slack hands back via
the API is literally:

    <@U0BOTID> cake this Friday at 10am

No new OAuth scope needed -- this is just string content already present
in the `text` field we already read.

## Config

Add one new env var, following the existing pattern of
`KIOSK_SLACK_CHANNEL` (a Slack ID you copy from the UI):

    # The bot's own Slack member ID. If set, only messages that
    # @-mention the bot are treated as content -- everything else in
    # the channel is ignored. Find it via the bot's Slack profile ->
    # "Copy member ID". Leave unset to process every message (current
    # behavior).
    KIOSK_SLACK_MENTION_USER_ID=

Unset by default => fully backward compatible with today's "every
message counts" behavior. Note the poll loop already resolves the
bot's own user ID at the start of each tick via `auth_test()` (see
`bin/slack_source.py`) to exclude the bot's own messages -- this
mention gate is a separate, opt-in mechanism layered on top of that.

## Implementation sketch (bin/slack_source.py)

- `SlackConfig` gains an optional `mention_user_id: str | None` field.
- New pure helper, unit-testable without network:

  ```python
  def has_required_mention(text: str, mention_user_id: str | None) -> bool:
      """True if no mention is required, or the text contains it."""
      if not mention_user_id:
          return True
      return f"<@{mention_user_id}>" in (text or "")

  def strip_mention(text: str, mention_user_id: str | None) -> str:
      if not mention_user_id:
          return text
      return re.sub(rf"<@{mention_user_id}>\s*", "", text or "").strip()
  ```

- In `poll_slack`'s per-message loop, gate *before* `classify_message`
  runs (covers attachment messages too -- "here's a flyer" with no
  mention should NOT go up, matching the "avoid accidental" goal):

  ```python
  if not has_required_mention(msg.get("text", ""), cfg.mention_user_id):
      continue  # not addressed to messtvbot -- ignore silently
  ```

- When storing `entry["text"]` for a text-kind message, run it through
  `strip_mention()` so the slide shows "cake this Friday at 10am", not
  the raw `<@U...>` token.
- Everything downstream (accept/cancel/expire Slack replies, TTL sweep,
  command-word thread replies) is unaffected -- those already operate on
  `ts`/`state`, not on whether a mention was present.

## Open questions / decisions to make before implementing

1. **Anywhere in the message vs. must lead the message?** Leaning
   "anywhere" -- matches how people naturally type mentions mid-sentence
   ("please see @messtvbot re: cake Friday").
2. **Combine with the earlier allowed-authors idea?** Could layer both
   (mention required AND author must be in an allow-list) if even
   tighter control is wanted later, but starting with mention-only
   keeps the surface area small.
3. **Silent ignore vs. some kind of feedback for a "close but no
   mention" post?** Current lean: stay silent -- matches existing
   "ignored message" behavior for system messages, no new noise.
4. **Docs to update when this ships:** README's Slack app setup section
   and `docs/SETUP.md`, same places touched for the accept/cancel/expiry
   Slack replies feature.

## Status

Not implemented. This file exists purely to capture the idea and
implementation shape before building it, per user request on
2026-09-28. Updated 2026-09-28 for the project rename to Mess TV Bot
(file/env names refreshed; concept unchanged).
