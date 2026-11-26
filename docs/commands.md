---
layout: default
title: Commands — Mess TV Bot
description: How to remove or reschedule a message, see what's on the display, and get help, with Mess TV Bot.
nav: commands
---

# Commands

There are three:


1. `remove` in message's thread to remove it or schedule removal.
2. `list` in a new message on its own, to see what's on the display.
3. `help` in a new message on its own, or a reply in a message's thread.

{:.lede}

<div class="callout" markdown="1">
For `remove`: find the message you posted, open its thread, and reply there. A reply posted anywhere else (a new top-level message, or a reply on someone else's message) doesn't count.
</div>

## Removing a message

Reply with `remove`.

| Reply | What happens |
| --- | --- |
| `remove` | Removed immediately. |
| `remove now` | Same as above — "now" is optional. |
| `remove tonight` | Scheduled for the end of today (23:59). |
| `remove in 2 hours` | Scheduled for 2 hours from now. |
| `remove in 1 week` | Scheduled for the end of the day, 7 days from now. |
| `remove thursday` | Scheduled for the end of next Thursday. |
| `remove 3 Sept` | Scheduled for the end of that day. |
| `remove 3 Sept 10am` | Scheduled for that date and time. |

A date with no time means the end of that day (23:59), so a post about something on the 3rd is still up on the 3rd. Dates are day first: `3/9` is 3 September.

If a date/time phrase can't be understood (e.g. a typo), nothing is removed — the bot replies saying it didn't understand and restates the message's current removal date, so a garbled reply can't accidentally take something down.

Times are always in UK local time, adjusting automatically for GMT/BST.

Scheduling a removal doesn't take the message down early — it stays up until the new date arrives. The bot confirms the date in a thread reply either way, so you always have something to check back against — and that confirmation always includes how far off the date is, e.g. "14 Aug 2026 09:00 (in 13 days)".

## Choosing how long a message stays up

To set the removal date when you post, make the message's text **only** `until` and a date. Put it in the image's caption, or in the note when you forward a message:

| Text | What happens |
| --- | --- |
| `until 11 Dec` | Up until the end of 11 Dec (23:59). |
| `show until Friday` | Up until the end of Friday. |
| `Show now until 11 Dec 26` | Up until the end of 11 Dec 2026. |
| `until 11 Dec 5pm` | Up until 5pm on 11 Dec. |

As with `remove`, a date with no time means the end of that day, and dates are day first: `11/12/26` is 11 December.

The `until …` text itself isn't shown, so an image with this caption appears on its own. It only counts as the whole text: "Xmas party until 11 Dec" is an ordinary caption, shown as written, for the usual length of time.

If the bot can't understand the date, or it's in the past, the message goes up for the usual length of time, the text is shown as an ordinary caption, and the bot's reply says it couldn't understand the date. `until 11 Dec` on its own, with no image, has nothing to show: the bot suggests replying `remove 11 Dec` in the thread of the post you meant instead.

## Seeing what's on the display

Post `list` as a new message on its own (`what's on` works too) and the bot replies in that message's thread with a numbered list of everything currently on the display, oldest first. For each one you get:

- the text of the message, shortened if it's long — or, for a message that's only an image, the image itself (the first one, if there are several);
- who posted it;
- when it's due to come down, e.g. "until 14 Aug 2026 09:00 (in 13 days)";
- a link to the original message, which is where you'd reply `remove`.

The `list` message itself is never shown on the display. It has to be the whole message: a notice that merely starts with "What's on…" or "List of…" is shown normally.

## Getting help

Post `help` as a new message, or reply `help` in any message's thread, and the bot replies with a quick summary: what it does, how long a message stays up, how to remove one, and who to contact if something's broken.

A short new message that happens to start with `help` or `remove` is treated the same way — it won't be shown on the display, since it's almost certainly someone looking for instructions rather than content meant for the screen. For `help` the bot replies with the summary. For `remove` it replies that the message won't be shown, and that to remove a post you reply in that post's own thread. A longer message that happens to start with one of those words (a real notice, not a command) is shown normally.
