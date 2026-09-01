const RESULTS_URL = "../data/results.json";

let allResults = [];

function formatDate(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  return d.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}

function sortedParticipants(participants) {
  // Best-effort sort by score ascending (golf: lower is better).
  // Falls back to original order if scores aren't numeric.
  return [...participants].sort((a, b) => {
    const sa = parseFloat(a.score);
    const sb = parseFloat(b.score);
    if (Number.isNaN(sa) || Number.isNaN(sb)) return 0;
    return sa - sb;
  });
}

function renderLatest(round) {
  const section = document.getElementById("latest-round");
  if (!round) return;
  section.classList.remove("hidden");

  section.querySelector(".latest-map").textContent = round.map_name || "Map unknown";
  section.querySelector(".latest-meta").textContent =
    `${round.channel} · ${formatDate(round.published_at)}`;

  const list = section.querySelector(".latest-standings");
  list.innerHTML = "";
  sortedParticipants(round.participants || []).forEach((p) => {
    const li = document.createElement("li");
    li.innerHTML = `<span>${p.name}</span><span>${p.score}</span>`;
    list.appendChild(li);
  });
}

function renderList(rounds) {
  const container = document.getElementById("round-list");
  const emptyState = document.getElementById("empty-state");
  container.innerHTML = "";

  if (rounds.length === 0) {
    emptyState.classList.remove("hidden");
    return;
  }
  emptyState.classList.add("hidden");

  rounds.forEach((round) => {
    const row = document.createElement("div");
    row.className = "round-row";

    const needsReview = round.extraction_method === "manual_review_needed";

    row.innerHTML = `
      <div class="round-row-head">
        <div>
          <div class="round-row-map">${round.map_name || "Map unknown"}</div>
          <div class="round-row-channel">${round.channel}</div>
        </div>
        <div class="round-row-date">${formatDate(round.published_at)}</div>
      </div>
      ${needsReview ? '<div class="needs-review">Needs manual review — results not auto-detected</div>' : ""}
      <ol class="round-row-standings"></ol>
      <a class="round-row-link" href="${round.url}" target="_blank" rel="noopener">Watch on YouTube ↗</a>
    `;

    const list = row.querySelector(".round-row-standings");
    sortedParticipants(round.participants || []).forEach((p) => {
      const li = document.createElement("li");
      li.innerHTML = `<span>${p.name}</span><span>${p.score}</span>`;
      list.appendChild(li);
    });

    row.addEventListener("click", (e) => {
      if (e.target.tagName === "A") return;
      row.classList.toggle("open");
    });

    container.appendChild(row);
  });
}

function populateChannelFilter(rounds) {
  const select = document.getElementById("channel-filter");
  const channels = [...new Set(rounds.map((r) => r.channel))].sort();
  channels.forEach((c) => {
    const opt = document.createElement("option");
    opt.value = c;
    opt.textContent = c;
    select.appendChild(opt);
  });
}

function applyFilters() {
  const channel = document.getElementById("channel-filter").value;
  const query = document.getElementById("search").value.trim().toLowerCase();

  const filtered = allResults.filter((r) => {
    if (channel && r.channel !== channel) return false;
    if (!query) return true;
    const haystack = [
      r.map_name || "",
      ...(r.participants || []).map((p) => p.name),
    ]
      .join(" ")
      .toLowerCase();
    return haystack.includes(query);
  });

  renderList(filtered);
}

async function init() {
  const res = await fetch(RESULTS_URL);
  const data = await res.json();
  allResults = [...(data.results || [])].sort(
    (a, b) => new Date(b.published_at) - new Date(a.published_at)
  );

  renderLatest(allResults[0]);
  populateChannelFilter(allResults);
  renderList(allResults);

  document.getElementById("channel-filter").addEventListener("change", applyFilters);
  document.getElementById("search").addEventListener("input", applyFilters);
}

init().catch((err) => {
  console.error("Failed to load results:", err);
  document.getElementById("empty-state").classList.remove("hidden");
});
