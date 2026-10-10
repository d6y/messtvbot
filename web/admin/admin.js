(() => {
  "use strict";

  const tbody = document.getElementById("entries-body");
  const empty = document.getElementById("empty");
  const POLL_MS = 5000;

  const dateFormatter = new Intl.DateTimeFormat("en-GB", {
    timeZone: "Europe/London",
    year: "numeric", month: "2-digit", day: "2-digit",
    hour: "2-digit", minute: "2-digit", hour12: false,
  });

  // "2026-09-28T12:34:56+00:00" -> "2026-09-28 12:34" (London time).
  function formatDate(iso) {
    if (!iso) return "";
    const date = new Date(iso);
    if (Number.isNaN(date.getTime())) return iso;
    const parts = Object.fromEntries(dateFormatter.formatToParts(date).map(p => [p.type, p.value]));
    return `${parts.year}-${parts.month}-${parts.day} ${parts.hour}:${parts.minute}`;
  }

  async function loadEntries() {
    try {
      const res = await fetch("/api/entries");
      if (!res.ok) throw new Error("HTTP " + res.status);
      const entries = await res.json();
      render(entries);
    } catch (err) {
      console.warn("Mess TV Bot admin: failed to load entries", err);
    } finally {
      setTimeout(loadEntries, POLL_MS);
    }
  }

  function render(entries) {
    tbody.innerHTML = "";
    empty.hidden = entries.length > 0;
    for (const entry of entries) {
      const row = document.createElement("tr");

      const thumbCell = document.createElement("td");
      if (entry.thumb) {
        const img = document.createElement("img");
        img.className = "thumb";
        img.src = "/" + entry.thumb;
        img.alt = "";
        thumbCell.appendChild(img);
      }

      const author = document.createElement("td");
      author.textContent = entry.author;
      const summary = document.createElement("td");
      summary.textContent = entry.summary;
      const posted = document.createElement("td");
      posted.textContent = formatDate(entry.posted_at);
      const removeAt = document.createElement("td");
      removeAt.textContent = formatDate(entry.remove_at);

      // Same page/CSS/JS a poster's own review link opens (see the bot's
      // acceptance reply in slack_source.py) -- lets an admin see exactly
      // how an entry renders without leaving this page.
      const reviewCell = document.createElement("td");
      const reviewLink = document.createElement("a");
      reviewLink.className = "review-link";
      reviewLink.href = "/index.html?ts=" + encodeURIComponent(entry.ts);
      reviewLink.target = "_blank";
      reviewLink.rel = "noopener";
      reviewLink.textContent = "Review";
      reviewCell.appendChild(reviewLink);

      const actionCell = document.createElement("td");
      const button = document.createElement("button");
      button.textContent = "Remove";
      button.addEventListener("click", () => removeEntry(entry.ts));
      actionCell.appendChild(button);

      row.append(thumbCell, author, summary, reviewCell, posted, removeAt, actionCell);
      tbody.appendChild(row);
    }
  }

  async function removeEntry(ts) {
    try {
      const res = await fetch(`/api/entries/${encodeURIComponent(ts)}/remove`, { method: "POST" });
      if (!res.ok) throw new Error("HTTP " + res.status);
      loadEntries();
    } catch (err) {
      console.warn("Mess TV Bot admin: failed to remove entry", ts, err);
    }
  }

  loadEntries();
})();
