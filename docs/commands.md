---
layout: default
title: Commands — Mess TV Bot
description: How to remove or reschedule a post, and how to get help, with Mess TV Bot.
nav: commands
---

# Commands

All commands are replies to your own post's thread — except `help`, which is a new message on its own.
{:.lede}

<div class="callout" markdown="1">
Find the message you posted, open its thread, and reply there. A reply posted anywhere else (a new top-level message, or a reply on someone else's post) doesn't count.
</div>

## Removing a post

Reply with `remove`.

| Reply | What happens |
| --- | --- |
| `remove` | Removed immediately. |
| `remove now` | Same as above — "now" is optional. |
| `remove in 1 week` | Scheduled to come down 7 days from now. |
| `remove thursday` | Scheduled for the next Thursday. |
| `remove 3 Sept` | Scheduled for that date. |
| `remove 3 Sept 10am` | Scheduled for that date and time. |

If a date/time phrase can't be understood (e.g. a typo), nothing is removed — the bot replies saying it didn't understand and restates the post's current removal date, so a garbled reply can't accidentally take something down.

Times are always in UK local time, adjusting automatically for GMT/BST.

Scheduling a removal doesn't take the post down early — it stays up until the new date arrives. The bot confirms the date in a thread reply either way, so you always have something to check back against — and that confirmation always includes how far off the date is, e.g. "14 Aug 2026 09:00 (in 13 days)".

## Getting help

Post `help` as a new message (not a reply) and the bot replies with a quick summary: what it does, how long a post stays up, how to remove one, and who to contact if something's broken.

A short new message that happens to start with `help` or `remove` is treated the same way — it won't be shown on the display, since it's almost certainly someone looking for instructions rather than content meant for the screen. A longer message that happens to start with one of those words (a real notice, not a command) is shown normally.
