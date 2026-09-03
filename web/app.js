(() => {
  "use strict";

  const layerA = document.getElementById("layer-a");
  const layerB = document.getElementById("layer-b");
  const textCard = document.getElementById("text-card");
  const textMessage = document.getElementById("text-message");
  const textAuthor = document.getElementById("text-author");
  const emptyState = document.getElementById("empty-state");

  const DEFAULT_SLIDE_MS = 8000;
  const DEFAULT_POLL_MS = 30000;
  const MANIFEST_URL = "data/manifest.json";

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

  async function showSlide(index) {
    if (items.length === 0) return;
    const item = items[index];

    if (item.kind === "text") {
      textMessage.textContent = item.text || "";
      textAuthor.textContent = item.author ? "— " + item.author : "";
      textCard.classList.add("visible");
      frontLayer.classList.remove("visible");
      backLayer.classList.remove("visible");
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
      [frontLayer, backLayer] = [backLayer, frontLayer];
      currentIndex = index;
    } catch (err) {
      // Broken/missing image: skip it and try the next one shortly.
      console.warn("Masthead: failed to load", item.src, err);
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
    window.__masthead_poll_seconds = manifest.poll_seconds || DEFAULT_POLL_MS / 1000;
    const newItems = Array.isArray(manifest.items) ? manifest.items : [];

    if (newItems.length === 0) {
      items = [];
      emptyState.classList.add("visible");
      frontLayer.classList.remove("visible");
      backLayer.classList.remove("visible");
      textCard.classList.remove("visible");
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
      console.warn("Masthead: manifest poll failed", err);
    } finally {
      const nextPollMs = (window.__masthead_poll_seconds || DEFAULT_POLL_MS / 1000) * 1000;
      setTimeout(pollManifest, nextPollMs);
    }
  }

  // Kick things off.
  emptyState.classList.add("visible");
  pollManifest();
})();
