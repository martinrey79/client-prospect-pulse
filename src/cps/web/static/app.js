const state = {
  entities: [],
  selectedId: null,
  detail: null,
};

const $ = (id) => document.getElementById(id);

async function fetchJson(path) {
  const res = await fetch(path);
  if (!res.ok) throw new Error(`${path} → ${res.status}`);
  return res.json();
}

function fmtWhen(value) {
  if (!value) return "";
  try {
    return new Date(value).toLocaleString(undefined, {
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return String(value);
  }
}

function renderMeters(overview) {
  const c = overview.counts || {};
  const s = overview.simulator || {};
  const ls = overview.langsmith || {};
  const meters = [
    ["Entities", c.entities ?? 0],
    ["Documents", c.documents ?? 0],
    ["Material", c.material_conclusions ?? 0],
    ["Sim conversations", s.conversations ?? 0],
    [
      "LangSmith",
      ls.enabled ? "on" : "off",
    ],
  ];
  $("meters").innerHTML = meters
    .map(
      ([label, value]) =>
        `<div class="meter"><strong>${value}</strong><span>${label}</span></div>`
    )
    .join("");

  const footExtra = ls.enabled
    ? `LangSmith · ${escapeHtml(ls.project || "default")}`
    : `LangSmith off${ls.reason ? ` · ${escapeHtml(ls.reason)}` : ""}`;
  const clock = $("clock");
  if (clock) {
    clock.dataset.langsmith = footExtra;
  }
}

function renderEntityList() {
  const list = $("entity-list");
  list.innerHTML = state.entities
    .map((e) => {
      const active = e.id === state.selectedId ? "active" : "";
      const material =
        e.material_count > 0
          ? `<span class="badge-material"> · ${e.material_count} material</span>`
          : "";
      return `<li>
        <button type="button" class="${active}" data-id="${e.id}">
          <span class="ename">${escapeHtml(e.name)}</span>
          <span class="emeta">${escapeHtml(e.type)} · ${escapeHtml(e.importance)}${material}</span>
        </button>
      </li>`;
    })
    .join("");

  list.querySelectorAll("button").forEach((btn) => {
    btn.addEventListener("click", () => selectEntity(btn.dataset.id));
  });
}

function buildActivity(detail) {
  const items = [];

  for (const c of detail.conclusions || []) {
    items.push({
      at: c.created_at,
      kind: c.is_material ? "Material conclusion" : "Conclusion",
      title: c.llm_text || c.manual_text || "Conclusion",
      body: c.metadata?.reason || "",
      cls: c.is_material ? "material" : "",
    });
  }

  for (const d of detail.documents || []) {
    const isPublic = d.type !== "manual";
    items.push({
      at: d.created_at,
      kind: isPublic ? `Public · ${d.type}` : "Private · conversation",
      title: d.summary || "Document",
      body: d.extracted_content || d.source_url || "",
      cls: isPublic ? "public" : "",
    });
  }

  for (const c of detail.conversations || []) {
    items.push({
      at: c.date,
      kind: c.triggers_refresh ? "Private · refresh trigger" : `Private · ${c.type}`,
      title: c.summary || "Conversation",
      body: c.notes || "",
      cls: c.triggers_refresh ? "material" : "",
    });
  }

  items.sort((a, b) => String(b.at).localeCompare(String(a.at)));
  return items.slice(0, 20);
}

function renderDetail() {
  const detail = state.detail;
  if (!detail) {
    $("empty-state").classList.remove("hidden");
    $("detail").classList.add("hidden");
    return;
  }

  $("empty-state").classList.add("hidden");
  $("detail").classList.remove("hidden");

  const e = detail.entity;
  $("entity-name").textContent = e.name;
  $("entity-meta").textContent = `${e.type} · ${e.status} · interests: ${(e.interests || []).join(", ") || "—"}`;
  $("entity-importance").textContent = e.importance;
  $("private-summary").textContent = e.private_summary || "No private summary yet.";
  $("public-summary").textContent = e.public_summary || "No public summary yet.";

  const stream = $("activity-stream");
  const items = buildActivity(detail);
  stream.innerHTML = items
    .map(
      (item, i) => `<li class="${item.cls}" style="animation-delay:${i * 0.04}s">
        <span class="kind">${escapeHtml(item.kind)} · ${escapeHtml(fmtWhen(item.at))}</span>
        <p class="title">${escapeHtml(item.title)}</p>
        ${item.body ? `<p class="body">${escapeHtml(truncate(item.body, 220))}</p>` : ""}
      </li>`
    )
    .join("");

  const portfolio = detail.portfolio;
  if (portfolio) {
    const positions = (portfolio.positions || [])
      .map(
        (p) =>
          `${p.symbol}: ${p.quantity} (${p.market_value ?? "—"} ${p.currency || portfolio.currency || ""})`
      )
      .join("<br>");
    $("portfolio").innerHTML = `
      <p>Cash: <strong>${portfolio.cash ?? 0}</strong> ${portfolio.currency || "EUR"}</p>
      <p class="muted">As of ${escapeHtml(fmtWhen(portfolio.as_of))}</p>
      <p>${positions || '<span class="muted">No positions</span>'}</p>
      <p class="muted">${(portfolio.orders || []).length} orders · ${(portfolio.transactions || []).length} transactions</p>
    `;
  } else {
    $("portfolio").innerHTML = `<p class="muted">No portfolio in simulator</p>`;
  }

  const qs = detail.questions || [];
  $("questions").innerHTML = qs.length
    ? qs.map((q) => `<p>${escapeHtml(q.text)}</p>`).join("")
    : `<p class="muted">No open questions</p>`;
}

async function selectEntity(id) {
  state.selectedId = id;
  renderEntityList();
  state.detail = await fetchJson(`/api/entities/${id}`);
  renderDetail();
}

async function refresh() {
  const [overview, entities] = await Promise.all([
    fetchJson("/api/overview"),
    fetchJson("/api/entities"),
  ]);
  renderMeters(overview);
  state.entities = entities;

  if (!state.selectedId && entities.length) {
    state.selectedId = entities[0].id;
  }
  if (state.selectedId && !entities.find((e) => e.id === state.selectedId)) {
    state.selectedId = entities[0]?.id || null;
  }

  renderEntityList();
  if (state.selectedId) {
    state.detail = await fetchJson(`/api/entities/${state.selectedId}`);
    renderDetail();
  } else {
    state.detail = null;
    renderDetail();
  }

  $("clock").textContent = [
    $("clock").dataset.langsmith,
    `Updated ${new Date().toLocaleTimeString()}`,
  ]
    .filter(Boolean)
    .join(" · ");
  $("live-label").textContent = "Live";
}

function truncate(text, n) {
  const s = String(text);
  return s.length > n ? `${s.slice(0, n - 1)}…` : s;
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

refresh().catch((err) => {
  $("live-label").textContent = "Offline";
  console.error(err);
});

setInterval(() => {
  refresh().catch(() => {
    $("live-label").textContent = "Offline";
  });
}, 5000);
