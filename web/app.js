(() => {
  "use strict";

  const stage = document.getElementById("stage");
  const layerA = document.getElementById("layer-a");
  const layerB = document.getElementById("layer-b");
  const textCard = document.getElementById("text-card");
  const textMessage = document.getElementById("text-message");
  const textAuthor = document.getElementById("text-author");
  const imageCaption = document.getElementById("image-caption");
  const imageCaptionText = document.getElementById("image-caption-text");
  const gridLayer = document.getElementById("grid-layer");
  const videoLayer = document.getElementById("video-layer");
  const emptyState = document.getElementById("empty-state");

  const DEFAULT_SLIDE_MS = 8000;
  const DEFAULT_POLL_MS = 30000;
  const MANIFEST_URL = "data/manifest.json";

  // ?ts=<slack-ts> opens this same page as a review page for one post --
  // the bot's acceptance reply links here so a poster can see how their
  // post actually renders without walking up to the TV. Set once at load;
  // never cleared, so a later manifest update still re-filters correctly.
  const reviewTs = new URLSearchParams(location.search).get("ts");
  const emptyStateSub = document.querySelector("#empty-state .sub");
  const emptyStateSubDefault = emptyStateSub ? emptyStateSub.textContent : "";

  let items = [];
  let currentIndex = -1;
  let frontLayer = layerA;
  let backLayer = layerB;
  let slideTimer = null;
  let slideMs = DEFAULT_SLIDE_MS;
  let lastManifestRaw = "";

  function cacheBustedUrl(src) {
    // Prevent the browser from serving a stale cached image after a
    // Slack re-poll replaces a file with the same name.
    return src + (src.includes("?") ? "&" : "?") + "t=" + Date.now();
  }

  function preload(src) {
    return new Promise((resolve, reject) => {
      const img = new Image();
      img.onload = () => resolve(img.src);
      img.onerror = reject;
      img.src = cacheBustedUrl(src);
    });
  }

  function escapeHtml(str) {
    return str.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  }

  // Minimal, safe Slack mrkdwn -> HTML: escape first, then only ever wrap
  // already-escaped text in a fixed set of tags, so no unescaped input
  // ever reaches innerHTML. Not a full markdown parser -- just the marks
  // people actually use in short notices (bold/italic/strike/code/links).
  function slackMrkdwnToHtml(text) {
    let html = escapeHtml(text || "");

    // <url|label> or bare <url> -- shown as plain text; a link isn't
    // clickable on a kiosk with no pointer, so just drop the wrapper.
    html = html.replace(/&lt;(https?:\/\/[^|&]*)\|([^&]*?)&gt;/g, "$2");
    html = html.replace(/&lt;(https?:\/\/[^&]*)&gt;/g, "$1");

    html = html.replace(/`([^`\n]+)`/g, "<code>$1</code>");
    html = html.replace(/(?<![A-Za-z0-9*])\*(\S(?:[^*\n]*\S)?)\*(?![A-Za-z0-9*])/g, "<strong>$1</strong>");
    html = html.replace(/(?<![A-Za-z0-9_])_(\S(?:[^_\n]*\S)?)_(?![A-Za-z0-9_])/g, "<em>$1</em>");
    html = html.replace(/(?<![A-Za-z0-9~])~(\S(?:[^~\n]*\S)?)~(?![A-Za-z0-9~])/g, "<s>$1</s>");

    return html;
  }

  // Short messages should fill the available space with large type; long
  // ones shrink to fit rather than overflow. Tuned by eye, not derived.
  // This is only a starting guess -- it goes by character count, which
  // looks "short" even for text forced onto many short lines (explicit
  // newlines, e.g. a numbered list), so shrinkFontToFit() below corrects
  // it against the real rendered height rather than trusting the formula.
  function scaledFontSizeVw(text, minVw, maxVw, k) {
    const scaled = k / Math.max(text.length, 20);
    return Math.max(minVw, Math.min(maxVw, scaled));
  }

  // Backstop for scaledFontSizeVw: shrink el's font size step-by-step
  // until its rendered content actually fits container's height, or we
  // hit minVw. Needed because no character-count formula can predict how
  // many lines text with explicit "\n"s will force.
  function shrinkFontToFit(el, container, minVw) {
    if (!el || !container) return;
    let vw = parseFloat(el.style.fontSize) || minVw;
    let guard = 60;
    // container.clientHeight includes its own padding, but a centered
    // flex child only has clientHeight minus top+bottom padding to fit
    // in -- comparing against the unadjusted clientHeight let content
    // stay too large and overflow past the padding, clipped off-screen
    // by body's overflow:hidden (found live: #text-card's 4vw padding
    // alone was ~150px, enough that "fits" by the old check still spilled
    // the title line above the top edge of the screen).
    const style = getComputedStyle(container);
    const availableHeight =
      container.clientHeight -
      parseFloat(style.paddingTop || "0") -
      parseFloat(style.paddingBottom || "0");
    while (el.scrollHeight > availableHeight && vw > minVw && guard-- > 0) {
      vw = Math.max(minVw, vw - 0.25);
      el.style.fontSize = vw + "vw";
    }
  }

  // Full-width text-only slide.
  function textFontSizeVw(text) {
    return scaledFontSizeVw(text, 2.4, 9, 900);
  }

  // Caption panel is ~46% of the screen width, so it gets a smaller cap
  // than the full-width text slide -- sized so a ~100-char caption (a
  // realistic length) comfortably wraps within the panel's height.
  function captionFontSizeVw(text) {
    return scaledFontSizeVw(text, 2, 4.6, 380);
  }

  // Multi-image grid: near-square layout that scales for any region count.
  function gridDims(n) {
    const cols = Math.ceil(Math.sqrt(n));
    const rows = Math.ceil(n / cols);
    return { cols, rows };
  }

  // Text region in a grid cell is scaled down from captionFontSizeVw's
  // ~46vw-wide tuning, proportional to how much narrower this cell is.
  function gridTextFontSizeVw(text, cols) {
    const cellVw = 100 / cols;
    const scale = cellVw / 46;
    return scaledFontSizeVw(text, 1.4, Math.max(2, 4.6 * scale), 380 * scale);
  }

  async function showGridSlide(item) {
    const regions = Array.isArray(item.regions) ? item.regions : [];
    const loaded = await Promise.all(regions.map(async (region) => {
      if (region.kind !== "image") return region;
      try {
        const url = await preload(region.src);
        return { ...region, url };
      } catch (err) {
        console.warn("Mess TV Bot: failed to load grid image", region.src, err);
        return null;
      }
    }));
    const usable = loaded.filter(Boolean);
    if (usable.length === 0) return false;

    const { cols, rows } = gridDims(usable.length);
    gridLayer.style.gridTemplateColumns = `repeat(${cols}, 1fr)`;
    gridLayer.style.gridTemplateRows = `repeat(${rows}, 1fr)`;
    gridLayer.replaceChildren();
    const textCells = [];
    for (const region of usable) {
      const cell = document.createElement("div");
      cell.className = "grid-cell";
      if (region.kind === "text") {
        cell.classList.add("text-cell");
        const p = document.createElement("p");
        p.innerHTML = slackMrkdwnToHtml(region.text || "");
        p.style.fontSize = gridTextFontSizeVw(region.text || "", cols) + "vw";
        cell.appendChild(p);
        textCells.push({ p, cell });
      } else {
        const img = document.createElement("img");
        img.src = region.url;
        img.alt = region.name || "";
        cell.appendChild(img);
      }
      gridLayer.appendChild(cell);
    }
    // Only measurable (clientHeight) once every cell is actually in the
    // DOM and the grid has laid out, hence a second pass after the loop.
    for (const { p, cell } of textCells) {
      shrinkFontToFit(p, cell, 1.4);
    }
    return true;
  }

  function hideVideoLayer() {
    videoLayer.classList.remove("visible");
    videoLayer.pause();
    videoLayer.removeAttribute("src");
    videoLayer.load();
  }

  async function showSlide(index) {
    if (items.length === 0) return;
    const item = items[index];

    if (item.kind === "text") {
      const text = item.text || "";
      textMessage.innerHTML = slackMrkdwnToHtml(text);
      textAuthor.textContent = item.author ? "— " + item.author : "";
      const messageVw = textFontSizeVw(text);
      textMessage.style.fontSize = messageVw + "vw";
      textAuthor.style.fontSize = Math.max(1.2, messageVw * 0.35) + "vw";
      textCard.classList.add("visible");
      shrinkFontToFit(textMessage, textCard, 2.4);
      frontLayer.classList.remove("visible");
      backLayer.classList.remove("visible");
      stage.classList.remove("split");
      imageCaption.classList.remove("visible");
      gridLayer.classList.remove("visible");
      hideVideoLayer();
      currentIndex = index;
      return;
    }

    if (item.kind === "grid") {
      const ok = await showGridSlide(item);
      if (!ok) {
        console.warn("Mess TV Bot: grid slide had no loadable images", item);
        // advance() computes the next slide from currentIndex -- without
        // updating it here too, a permanently-broken item would be
        // retried forever instead of actually moving on.
        currentIndex = index;
        scheduleNext(300);
        return;
      }
      gridLayer.classList.add("visible");
      textCard.classList.remove("visible");
      frontLayer.classList.remove("visible");
      backLayer.classList.remove("visible");
      stage.classList.remove("split");
      imageCaption.classList.remove("visible");
      hideVideoLayer();
      currentIndex = index;
      return;
    }

    if (item.kind === "video") {
      hideVideoLayer();
      videoLayer.src = cacheBustedUrl(item.src);
      videoLayer.loop = true;
      videoLayer.classList.add("visible");
      videoLayer.play().catch((err) => {
        console.warn("Mess TV Bot: video playback failed", item.src, err);
      });
      textCard.classList.remove("visible");
      frontLayer.classList.remove("visible");
      backLayer.classList.remove("visible");
      gridLayer.classList.remove("visible");
      if (item.caption) {
        imageCaptionText.innerHTML = slackMrkdwnToHtml(item.caption);
        imageCaptionText.style.fontSize = captionFontSizeVw(item.caption) + "vw";
        stage.classList.add("split");
        imageCaption.classList.add("visible");
        shrinkFontToFit(imageCaptionText, imageCaption, 2);
      } else {
        stage.classList.remove("split");
        imageCaption.classList.remove("visible");
      }
      currentIndex = index;
      return;
    }

    try {
      const url = await preload(item.src);
      backLayer.src = url;
      backLayer.alt = item.name || "";
      // Force layout so the opacity transition actually runs.
      // eslint-disable-next-line no-unused-expressions
      backLayer.offsetHeight;
      backLayer.classList.add("visible");
      frontLayer.classList.remove("visible");
      textCard.classList.remove("visible");
      gridLayer.classList.remove("visible");
      hideVideoLayer();
      if (item.caption) {
        imageCaptionText.innerHTML = slackMrkdwnToHtml(item.caption);
        imageCaptionText.style.fontSize = captionFontSizeVw(item.caption) + "vw";
        stage.classList.add("split");
        imageCaption.classList.add("visible");
        shrinkFontToFit(imageCaptionText, imageCaption, 2);
      } else {
        stage.classList.remove("split");
        imageCaption.classList.remove("visible");
      }
      [frontLayer, backLayer] = [backLayer, frontLayer];
      currentIndex = index;
    } catch (err) {
      // Broken/missing image: skip it and try the next one shortly.
      // advance() computes the next slide from currentIndex -- without
      // updating it here too, a permanently-broken image would be
      // retried forever instead of actually moving on (found live: one
      // bad image froze the whole slideshow on that slide indefinitely).
      console.warn("Mess TV Bot: failed to load", item.src, err);
      currentIndex = index;
      scheduleNext(300);
    }
  }

  function scheduleNext(delayMs) {
    clearTimeout(slideTimer);
    slideTimer = setTimeout(advance, delayMs != null ? delayMs : slideMs);
  }

  function advance() {
    if (items.length === 0) return;
    const next = (currentIndex + 1) % items.length;
    showSlide(next).then(() => scheduleNext());
  }

  function applyManifest(manifest) {
    slideMs = (manifest.slide_seconds || DEFAULT_SLIDE_MS / 1000) * 1000;
    window.__kiosk_poll_seconds = manifest.poll_seconds || DEFAULT_POLL_MS / 1000;
    const allItems = Array.isArray(manifest.items) ? manifest.items : [];
    // In review mode, scope the whole slideshow (cycling included) down to
    // just this post's item(s) -- a multi-page PDF still cycles its pages,
    // but nothing else from the display ever shows on this page.
    const newItems = reviewTs ? allItems.filter((item) => item.ts === reviewTs) : allItems;

    if (newItems.length === 0) {
      items = [];
      if (emptyStateSub) {
        emptyStateSub.textContent = reviewTs
          ? "Message not found — it may have expired or been removed."
          : emptyStateSubDefault;
      }
      emptyState.classList.add("visible");
      frontLayer.classList.remove("visible");
      backLayer.classList.remove("visible");
      textCard.classList.remove("visible");
      stage.classList.remove("split");
      imageCaption.classList.remove("visible");
      gridLayer.classList.remove("visible");
      hideVideoLayer();
      clearTimeout(slideTimer);
      currentIndex = -1;
      return;
    }

    emptyState.classList.remove("visible");

    const wasEmpty = items.length === 0;
    items = newItems;

    if (wasEmpty) {
      currentIndex = -1;
      advance();
    } else if (currentIndex >= items.length) {
      // List shrank; wrap around on the next tick rather than jumping now.
      currentIndex = -1;
    }
    // If the list changed but we're mid-cycle, just let the running
    // timer pick up the new list on its next advance() call -- avoids
    // restarting the slideshow every time someone posts to Slack.
  }

  async function pollManifest() {
    try {
      const res = await fetch(cacheBustedUrl(MANIFEST_URL));
      if (!res.ok) throw new Error("HTTP " + res.status);
      const raw = await res.text();
      if (raw !== lastManifestRaw) {
        lastManifestRaw = raw;
        applyManifest(JSON.parse(raw));
      }
    } catch (err) {
      console.warn("Mess TV Bot: manifest poll failed", err);
    } finally {
      const nextPollMs = (window.__kiosk_poll_seconds || DEFAULT_POLL_MS / 1000) * 1000;
      setTimeout(pollManifest, nextPollMs);
    }
  }

  // Kick things off.
  if (reviewTs) document.title = "Review — " + document.title;
  emptyState.classList.add("visible");
  pollManifest();
})();
