---
layout: default
title: FAQ — Mess TV Bot
description: Frequently asked questions about Mess TV Bot.
nav: faq
---

# FAQ

<div class="faq-item" markdown="1">
### I posted something and nothing happened. What's wrong?

Check the thread under your message — the bot replies either way. An unsupported attachment (video, an image format it doesn't recognise like TIFF, or a file that's too large) gets a reply explaining why it wasn't added, rather than being shown partially or silently dropped. No reply at all usually means the message was genuinely empty, or a download failed (a flaky network, usually) — try posting again.
</div>

<div class="faq-item" markdown="1">
### I edited my message and the display didn't change. Why not?

Edits aren't picked up — the bot only reads what your message said the moment it first arrived. Remove the old message (see [Commands](commands.html)) and post the corrected version.
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

Yes, Slack's normal formatting works: `*bold*`, `_italic_`, `~strikethrough~`, and `` `code` ``. A link is shown as plain text rather than something clickable.
</div>

<div class="faq-item" markdown="1">
### Do emojis work?

Yes, mostly, but there issome Slack-specific weirdness. If you see anything that looks wonky, let us know (type `help` to see who)
</div>

<div class="faq-item" markdown="1">
### How long does a message stay up?

The bot's reply to your message states the exact date and time it'll come down. That's always accurate for your message specifically — the default length of time can vary between deployments.
</div>

<div class="faq-item" markdown="1">
### How do I take my message down early, or push it back?

Reply to it in its thread — see [Commands](commands.html) for the exact wording.

But `remove now` schedules it for immediate removal. 


</div>

<div class="faq-item" markdown="1">
### Something seems broken — who do I ask?

Post `help` as a new message, or reply `help` in a message's thread, to find out who.
</div>
