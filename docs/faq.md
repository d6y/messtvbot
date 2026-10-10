---
layout: default
title: FAQ — Mess TV Bot
description: Frequently asked questions about Mess TV Bot.
nav: faq
---

# FAQ

<div class="faq-item" markdown="1">
### I posted something and nothing happened. What's wrong?

Check the thread under your post — the bot replies either way. An unsupported attachment (video, an image format it doesn't recognise like TIFF, or a file that's too large) gets a reply explaining why it wasn't added, rather than being shown partially or silently dropped. No reply at all usually means the message was genuinely empty, or a download failed (a flaky network, usually) — try posting again.
</div>

<div class="faq-item" markdown="1">
### I edited my post and the display didn't change. Why not?

Edits aren't picked up — the bot only reads what your post said the moment it first arrived. Remove the old post (see [Commands](commands.html)) and post the corrected version.
</div>

<div class="faq-item" markdown="1">
### Can I post more than one image at once?

Yes — attach several images to the same message and they'll be shown together on one slide, laid out in a grid rather than cycling one at a time. Add a caption too and it becomes one more tile in that grid.
</div>

<div class="faq-item" markdown="1">
### Can I post a PDF?

Yes — each page becomes its own slide, shown in order. Just the one PDF per message though: posting two or more PDFs together isn't supported and rejects the whole message. If you need to share pages from more than one PDF, convert them to images first and post those as a multi-image message instead.
</div>

<div class="faq-item" markdown="1">
### Can I use bold, italic, or other formatting?

Yes, Slack's normal formatting works: `*bold*`, `_italic_`, `~strikethrough~`, and `` `code` ``. A link is shown as plain text rather than something clickable, since there's no pointer on a TV screen.
</div>

<div class="faq-item" markdown="1">
### Does emoji work?

Yes, mostly, but there issome Slack-specific weirdness. If you see anything that looks wonky, let us know (type `help` to see who)
</div>

<div class="faq-item" markdown="1">
### How long does a post stay up?

The bot's reply to your post states the exact date and time it'll come down. That's always accurate for your post specifically — the default length of time can vary between deployments.
</div>

<div class="faq-item" markdown="1">
### How do I take my post down early, or push it back?

Reply to it in its thread — see [Commands](commands.html) for the exact wording.
</div>

<div class="faq-item" markdown="1">
### I typed "help" or "remove" as a new message and got an odd reply instead of it showing up. Why?

That's expected. A short new message starting with one of those words is treated as someone looking for instructions, not content for the screen — see [Commands](commands.html).
</div>

<div class="faq-item" markdown="1">
### Something seems broken — who do I ask?

Post `help` as a new message, or reply `help` in a post's thread.
</div>
