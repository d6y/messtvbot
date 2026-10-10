---
layout: default
title: Mess TV Bot
description: Post to a Slack channel, it shows up on the display. How to use Mess TV Bot.
nav: home
---

# Mess TV Bot

Post to the #mess-tv Slack channel. It shows up on the display.
{:.lede}

Post `help` to get a reminder of these instructions.

## What you can post

- **Text** — a plain message becomes a full-screen slide.
- **An image** — shown full-screen. Add a caption (just type a message alongside it) and the image and text share the slide side by side.
- **Several images in one post** — they're shown together on one slide, laid out in a grid. A caption becomes one more tile in that grid.

<div class="callout" markdown="1">
When your post is accepted, the bot replies in a thread confirming it's up, and tells you exactly when it'll come back down.
</div>

## Formatting

Most of  Slack's usual text formatting works: `*bold*`, `_italic_`, `~strikethrough~`, and `` `code` ``. Not underline though. Not sure why yet.

Emoji usually work, except for custom ones added to Slack. Maybe one day.

Links: you can't click on the TV, so link don't nake sense. You'll just see the text you've written. Maybe a QR code would be better?

## How long a post stays up

Every post has an expiry date, set automatically when it's accepted (your bot's reply tells you exactly when). After that, it's removed on its own. You can also remove it sooner, or push the date back — see [Commands](commands.html).

## One thing to know

**Editing your original message doesn't update the display.** The bot reads your post once, when you first send it. If you need to change something, remove the old post (see [Commands](commands.html)) and post again.

<div class="callout" markdown="1">
This is not an AI bot. Don't expect deep conversation. Post a message to display, `help`, or reply to a message with `remove`. That's about it.
</div>
