/* Grounded frontend — plain ES modules-free JS, no build step.
   Talks to the FastAPI backend over fetch. Deliberately holds no derived state:
   the server is the source of truth for provenance, so after every mutation we
   re-render from what the API returns rather than guessing locally. */

const API = window.GROUNDED_API || "http://127.0.0.1:8000";

const state = {
  notes: [],
  selected: new Set(),
  briefing: null,
  editing: null,
  view: "workspace",
};

const $ = (id) => document.getElementById(id);
const esc = (s) =>
  String(s ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

// ------------------------------------------------------------------ transport

async function api(path, options = {}) {
  const res = await fetch(API + path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (res.status === 204) return null;
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new Error(data.detail || `${res.status} ${res.statusText}`);
  }
  return data;
}

let toastTimer;
function toast(message, isError = false) {
  document.querySelector(".toast")?.remove();
  const el = document.createElement("div");
  el.className = "toast" + (isError ? " err" : "");
  el.setAttribute("role", "status");
  el.textContent = message;
  document.body.appendChild(el);
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.remove(), 5000);
}

// --------------------------------------------------------------------- notes

async function loadNotes(query = "") {
  const path = query.trim()
    ? `/api/notes/search?q=${encodeURIComponent(query.trim())}`
    : "/api/notes";
  state.notes = await api(path);
  renderNotes();
}

function renderNotes() {
  const list = $("note-list");
  $("note-count").textContent =
    `${state.notes.length} note${state.notes.length === 1 ? "" : "s"}`;

  if (!state.notes.length) {
    list.innerHTML =
      `<li class="note-item"><div class="note-body"><p class="note-text">
       No notes yet. Paste something above — a standup dump works fine.
       </p></div></li>`;
    return;
  }

  list.innerHTML = state.notes
    .map((n) => {
      const on = state.selected.has(n.id);
      return `
      <li class="note-item ${on ? "is-selected" : ""}">
        <input type="checkbox" id="note-cb-${n.id}" data-note="${n.id}" ${on ? "checked" : ""} />
        <div class="note-body">
          <label class="note-title" for="note-cb-${n.id}">${esc(n.title)}</label>
          <p class="note-text">${esc(n.body)}</p>
          <div class="note-meta">
            <span>Added ${new Date(n.created_at).toLocaleDateString()}</span>
            <button class="btn btn-sm" data-delete="${n.id}"
                    aria-label="Delete note: ${esc(n.title)}">Delete</button>
          </div>
        </div>
      </li>`;
    })
    .join("");
}

// ------------------------------------------------------------------ briefing

const ALWAYS_SHOWN = ["bullets", "cited", "invented"];

function statStrip(s) {
  const items = [
    ["bullets", s.total],
    ["cited", s.cited],
    ["invented", s.invented],
    ["downgraded", s.downgraded],
    ["re-attributed", s.reattributed],
    ["duplicates", s.duplicates],
    ["accepted", s.accepted],
    ["rejected", s.rejected],
  ].filter(([k, v]) => v > 0 || ALWAYS_SHOWN.includes(k));
  return `<div class="stat-row">${items
    .map(([k, v]) => `<span class="stat">${k} <b>${v}</b></span>`)
    .join("")}</div>`;
}

function contradictionBanner(list) {
  if (!list.length) return "";
  return `
    <div class="banner banner-warn">
      <h3>${list.length} source conflict${list.length === 1 ? "" : "s"} detected</h3>
      <p style="margin:0 0 4px">
        These notes disagree with each other. Bullets drawn from either side may be
        stating one half of a dispute as settled fact.
      </p>
      ${list
        .map(
          (c) => `
        <div class="contradiction">
          <div><span class="values">${esc(c.value_a)}</span> vs
               <span class="values">${esc(c.value_b)}</span>
               <span class="badge badge-plain">${esc(c.subject)}</span></div>
          <blockquote>Note ${c.note_a_id}: ${esc(c.excerpt_a)}</blockquote>
          <blockquote>Note ${c.note_b_id}: ${esc(c.excerpt_b)}</blockquote>
        </div>`
        )
        .join("")}
    </div>`;
}

const OUTCOME_LABEL = {
  verified: null,
  reattributed: "Re-attributed",
  unverified_quote: "Downgraded — quote not found",
  claimed_note_missing: "Downgraded — cited a note not in this briefing",
  no_quote_offered: null,
};

function evidenceBlock(b) {
  if (b.provenance === "cited" && b.citation) {
    const c = b.citation;
    return `
      <details class="evidence">
        <summary>Show the evidence</summary>
        <div class="evidence-body">
          <div class="src">Note ${c.note_id} · ${esc(c.note_title)} · match ${Math.round(c.match_score)}%</div>
          <span class="quote-context">…${esc(c.context_before)}</span><mark class="quote-hit">${esc(c.quote)}</mark><span class="quote-context">${esc(c.context_after)}…</span>
        </div>
      </details>`;
  }
  if (b.verification_detail) {
    return `
      <details class="evidence">
        <summary>Why this is marked invented</summary>
        <div class="evidence-body">${esc(b.verification_detail)}</div>
      </details>`;
  }
  return "";
}

function diffBlock(b) {
  if (!b.edited || !b.diff) return "";
  const html = b.diff
    .map((o) =>
      o.op === "equal" ? esc(o.text)
        : o.op === "insert" ? `<ins>${esc(o.text)}</ins>`
        : `<del>${esc(o.text)}</del>`)
    .join(" ");
  return `
    <details class="evidence">
      <summary>Edited by you — show changes</summary>
      <div class="evidence-body diff">${html}</div>
    </details>`;
}

function bulletItem(b, locked) {
  if (state.editing === b.id) {
    return `
      <li class="bullet p-${b.provenance}">
        <div class="editor">
          <label class="sr-only" for="edit-${b.id}">Edit bullet text</label>
          <textarea id="edit-${b.id}" rows="3">${esc(b.text)}</textarea>
          <div class="editor-actions">
            <button class="btn btn-primary btn-sm" data-save-edit="${b.id}">Save change</button>
            <button class="btn btn-sm" data-cancel-edit="1">Cancel</button>
          </div>
        </div>
      </li>`;
  }

  const badges = [];
  if (b.provenance === "cited") {
    badges.push(`<span class="badge badge-cited">✓ Cited · Note ${b.citation?.note_id ?? "?"}</span>`);
  } else {
    badges.push(`<span class="badge badge-invented">⚠ Invented — not in any note</span>`);
  }
  const outcome = OUTCOME_LABEL[b.verification_outcome];
  if (outcome) badges.push(`<span class="badge badge-warn">${esc(outcome)}</span>`);
  if (b.duplicate_of_id) badges.push(`<span class="badge badge-plain">Near-duplicate</span>`);
  if (b.edited) badges.push(`<span class="badge badge-plain">Edited</span>`);
  if (b.status !== "pending")
    badges.push(`<span class="badge badge-plain">${b.status}</span>`);

  const actions = locked
    ? ""
    : `<div class="bullet-actions">
         <button class="btn btn-sm" data-edit="${b.id}"
                 aria-label="Edit bullet ${b.position + 1}">Edit</button>
         <button class="btn btn-sm" data-status="accepted" data-id="${b.id}"
                 aria-pressed="${b.status === "accepted"}"
                 aria-label="Accept bullet ${b.position + 1}">Accept</button>
         <button class="btn btn-sm" data-status="rejected" data-id="${b.id}"
                 aria-pressed="${b.status === "rejected"}"
                 aria-label="Reject bullet ${b.position + 1}">Reject</button>
       </div>`;

  return `
    <li class="bullet p-${b.provenance} is-${b.status}">
      <div class="badges">${badges.join("")}</div>
      <div class="bullet-top">
        <p class="bullet-text">${esc(b.text)}</p>
        ${actions}
      </div>
      ${evidenceBlock(b)}
      ${diffBlock(b)}
    </li>`;
}

function renderBriefing() {
  const body = $("briefing-body");
  const b = state.briefing;
  $("save-btn").disabled = !b || b.status === "saved";
  $("briefing-model").textContent = b?.model_name ? `model: ${b.model_name}` : "";

  if (!b) {
    body.innerHTML = `
      <div class="empty">
        <strong>No briefing yet</strong>
        Add a few notes, then generate.
      </div>`;
    return;
  }

  const locked = b.status === "saved";
  const coverage = b.coverage_note
    ? `<div class="banner banner-info"><h3>Coverage</h3>${esc(b.coverage_note)}</div>`
    : "";
  const savedNote = locked
    ? `<div class="banner banner-info"><h3>Saved</h3>This briefing is locked.
       Decisions and citations are preserved as they were.</div>`
    : "";

  body.innerHTML =
    savedNote +
    statStrip(b.stats) +
    coverage +
    contradictionBanner(b.contradictions) +
    `<ul class="bullet-list">${b.bullets.map((x) => bulletItem(x, locked)).join("")}</ul>`;
}

// ------------------------------------------------------------------- history

async function loadHistory() {
  const items = await api("/api/briefings");
  $("history-list").innerHTML = items.length
    ? items
        .map(
          (b) => `
      <li><button class="history-item" data-open="${b.id}">
        <span>
          <strong>${esc(b.title)}</strong><br />
          <span class="tagline">${b.stats.cited} cited · ${b.stats.invented} invented ·
          ${b.stats.accepted} accepted · ${b.stats.rejected} rejected</span>
        </span>
        <span class="badge badge-plain">${b.status}</span>
      </button></li>`
        )
        .join("")
    : `<li class="note-item"><div class="note-body">
       <p class="note-text">No briefings saved yet.</p></div></li>`;
}

function setView(view) {
  state.view = view;
  $("view-workspace").hidden = view !== "workspace";
  $("view-history").hidden = view !== "history";
  $("tab-workspace").setAttribute("aria-current", view === "workspace" ? "page" : "false");
  $("tab-history").setAttribute("aria-current", view === "history" ? "page" : "false");
  if (view === "history") loadHistory().catch((e) => toast(e.message, true));
}

// -------------------------------------------------------------------- events

$("note-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const input = $("note-input");
  const body = input.value.trim();
  if (!body) return toast("Nothing to add — paste some text first.", true);
  try {
    await api("/api/notes", { method: "POST", body: JSON.stringify({ body }) });
    input.value = "";
    $("note-search").value = "";
    await loadNotes();
    toast("Note saved.");
  } catch (err) {
    toast(err.message, true);
  }
});

$("note-list").addEventListener("click", async (e) => {
  const del = e.target.closest("[data-delete]");
  if (del) {
    const id = Number(del.dataset.delete);
    try {
      await api(`/api/notes/${id}`, { method: "DELETE" });
      state.selected.delete(id);
      await loadNotes($("note-search").value);
      toast("Note deleted.");
    } catch (err) {
      toast(err.message, true);
    }
  }
});

$("note-list").addEventListener("change", (e) => {
  const cb = e.target.closest("[data-note]");
  if (!cb) return;
  const id = Number(cb.dataset.note);
  cb.checked ? state.selected.add(id) : state.selected.delete(id);
  const n = state.selected.size;
  $("generate-hint").textContent = n
    ? `Will use ${n} selected note${n === 1 ? "" : "s"}.`
    : "Uses all notes unless you tick specific ones.";
  renderNotes();
});

let searchTimer;
$("note-search").addEventListener("input", (e) => {
  clearTimeout(searchTimer);
  const q = e.target.value;
  searchTimer = setTimeout(() => loadNotes(q).catch((err) => toast(err.message, true)), 220);
});
$("search-clear").addEventListener("click", () => {
  $("note-search").value = "";
  loadNotes().catch((e) => toast(e.message, true));
});

$("generate-btn").addEventListener("click", async () => {
  const btn = $("generate-btn");
  btn.disabled = true;
  btn.innerHTML = `<span class="spinner"></span>Verifying claims against your notes…`;
  try {
    const payload = state.selected.size ? { note_ids: [...state.selected] } : {};
    state.briefing = await api("/api/briefings/generate", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    state.editing = null;
    renderBriefing();
    const s = state.briefing.stats;
    toast(`${s.cited} cited, ${s.invented} invented${s.downgraded ? `, ${s.downgraded} downgraded` : ""}.`);
  } catch (err) {
    toast(err.message, true);
  } finally {
    btn.disabled = false;
    btn.textContent = "Generate briefing";
  }
});

$("briefing-body").addEventListener("click", async (e) => {
  const statusBtn = e.target.closest("[data-status]");
  const editBtn = e.target.closest("[data-edit]");
  const saveEdit = e.target.closest("[data-save-edit]");
  const cancel = e.target.closest("[data-cancel-edit]");

  try {
    if (statusBtn) {
      const id = Number(statusBtn.dataset.id);
      const current = state.briefing.bullets.find((b) => b.id === id);
      const next = current.status === statusBtn.dataset.status ? "pending" : statusBtn.dataset.status;
      const updated = await api(`/api/bullets/${id}/status`, {
        method: "PATCH",
        body: JSON.stringify({ status: next }),
      });
      replaceBullet(updated);
    } else if (editBtn) {
      state.editing = Number(editBtn.dataset.edit);
      renderBriefing();
      $(`edit-${state.editing}`)?.focus();
    } else if (cancel) {
      state.editing = null;
      renderBriefing();
    } else if (saveEdit) {
      const id = Number(saveEdit.dataset.saveEdit);
      const text = $(`edit-${id}`).value.trim();
      if (!text) return toast("Bullet cannot be empty.", true);
      const updated = await api(`/api/bullets/${id}`, {
        method: "PATCH",
        body: JSON.stringify({ text }),
      });
      state.editing = null;
      replaceBullet(updated);
      toast("Edit saved.");
    }
  } catch (err) {
    toast(err.message, true);
  }
});

function replaceBullet(updated) {
  const i = state.briefing.bullets.findIndex((b) => b.id === updated.id);
  if (i !== -1) state.briefing.bullets[i] = updated;
  const bs = state.briefing.bullets;
  state.briefing.stats = {
    ...state.briefing.stats,
    accepted: bs.filter((b) => b.status === "accepted").length,
    rejected: bs.filter((b) => b.status === "rejected").length,
    pending: bs.filter((b) => b.status === "pending").length,
  };
  renderBriefing();
}

$("save-btn").addEventListener("click", async () => {
  if (!state.briefing) return;
  try {
    state.briefing = await api(`/api/briefings/${state.briefing.id}/save`, {
      method: "POST",
      body: JSON.stringify({}),
    });
    renderBriefing();
    toast("Briefing saved. It is now locked.");
  } catch (err) {
    toast(err.message, true);
  }
});

$("history-list").addEventListener("click", async (e) => {
  const open = e.target.closest("[data-open]");
  if (!open) return;
  try {
    state.briefing = await api(`/api/briefings/${open.dataset.open}`);
    state.editing = null;
    setView("workspace");
    renderBriefing();
  } catch (err) {
    toast(err.message, true);
  }
});

$("tab-workspace").addEventListener("click", () => setView("workspace"));
$("tab-history").addEventListener("click", () => setView("history"));

// ---------------------------------------------------------------------- boot

(async function boot() {
  try {
    const health = await api("/api/health");
    $("composer-hint").textContent = `API up · provider: ${health.provider}`;
    await loadNotes();

    // Restore the most recent briefing so a page reload does not lose the work.
    // Prefer an unsaved draft; fall back to the latest saved one.
    const briefings = await api("/api/briefings");
    const target = briefings.find((b) => b.status === "draft") || briefings[0];
    if (target) {
      state.briefing = await api(`/api/briefings/${target.id}`);
    }
    renderBriefing();
  } catch (err) {
    toast(`Cannot reach the API at ${API}. Is the backend running?`, true);
  }
})();
