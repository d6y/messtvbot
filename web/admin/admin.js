(() => {
  "use strict";

  const tbody = document.getElementById("entries-body");
  const empty = document.getElementById("empty");
  const POLL_MS = 5000;

  async function loadEntries() {
    try {
      const res = await fetch("/api/entries");
      if (!res.ok) throw new Error("HTTP " + res.status);
      const entries = await res.json();
      render(entries);
    } catch (err) {
      console.warn("Masthead admin: failed to load entries", err);
    } finally {
      setTimeout(loadEntries, POLL_MS);
    }
  }

  function render(entries) {
    tbody.innerHTML = "";
    empty.hidden = entries.length > 0;
    for (const entry of entries) {
      const row = document.createElement("tr");

      const author = document.createElement("td");
      author.textContent = entry.author;
      const summary = document.createElement("td");
      summary.textContent = entry.summary;
      const posted = document.createElement("td");
      posted.textContent = entry.posted_at;
      const removeAt = document.createElement("td");
      removeAt.textContent = entry.remove_at || "";

      const actionCell = document.createElement("td");
      const button = document.createElement("button");
      button.textContent = "Remove";
      button.addEventListener("click", () => removeEntry(entry.ts));
      actionCell.appendChild(button);

      row.append(author, summary, posted, removeAt, actionCell);
      tbody.appendChild(row);
    }
  }

  async function removeEntry(ts) {
    try {
      const res = await fetch(`/api/entries/${encodeURIComponent(ts)}/remove`, { method: "POST" });
      if (!res.ok) throw new Error("HTTP " + res.status);
      loadEntries();
    } catch (err) {
      console.warn("Masthead admin: failed to remove entry", ts, err);
    }
  }

  loadEntries();
})();
