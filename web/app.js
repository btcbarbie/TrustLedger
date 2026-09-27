"use strict";
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const naira = (kobo) => kobo == null ? "-" : "₦" + Math.floor(kobo / 100).toLocaleString("en-NG") + (kobo % 100 ? "." + String(kobo % 100).padStart(2, "0") : "");
const fmtDate = (iso) => iso ? new Date(iso.slice(0, 10) + "T12:00:00").toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" }) : "-";
const STATUS = { verified: "Verified", documented: "Documented", reported: "Reported", needs_review: "Needs review", rejected: "Rejected" };
const chip = (s) => `<span class="chip s-${esc(s)}">${STATUS[s] || esc(s)}</span>`;
const ROLE = { president: "President", treasurer: "Treasurer", member: "Member" };
const CAT = { weekly: "Weekly", monthly: "Monthly", medical: "Medical", wedding: "Wedding", inventory: "Business", goal: "Goal", property: "Property", fees: "Fees", insurance: "Insurance" };
const reduced = matchMedia("(prefers-reduced-motion: reduce)").matches;
const initials = (n) => n.split(" ").map((w) => w[0]).slice(0, 2).join("");
const sleep = (ms) => new Promise((r) => setTimeout(r, reduced ? 0 : ms));

const state = { groupId: null, overview: null, entries: [], filter: "all", tab: "overview", intro: true, me: null, lastAttn: null };

async function api(path, opts = {}) {
  const res = await fetch(path, { credentials: "same-origin", ...opts });
  const body = res.headers.get("content-type")?.includes("json") ? await res.json() : null;
  if (!res.ok) throw new Error(body?.detail || `Request failed (${res.status})`);
  return body;
}
const post = (path, data) => api(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(data) });

function countUp(el, kobo) {
  if (reduced || !state.intro) { el.textContent = naira(kobo); return; }
  const t0 = performance.now(), dur = 900;
  const step = (t) => {
    const p = Math.min(1, (t - t0) / dur), e = 1 - Math.pow(1 - p, 3);
    el.textContent = naira(Math.round(kobo * e / 100) * 100);
    if (p < 1) requestAnimationFrame(step);
  };
  requestAnimationFrame(step);
}

function fillBars(root) {
  const go = () => $$(".bar i[data-w]", root).forEach((el) => (el.style.width = el.dataset.w + "%"));
  if (state.intro && !reduced) requestAnimationFrame(() => requestAnimationFrame(go)); else go();
}
const rise = (i) => (state.intro ? ` rise" style="--i:${i}` : "");

const va = { people: [], open: false, active: -1 };

function vaSet(p) {
  $("#vaAvatar").textContent = p ? initials(p.name) : "?";
  $("#vaAvatar").className = `avatar sm${p ? " r-" + p.role : ""}`;
  $("#vaName").textContent = p ? p.name : "Choose a person";
  $("#vaRole").innerHTML = p ? `${ROLE[p.role] || "Member"}<span class="grp"> - ${esc(p.group_name)}${p.groups > 1 ? ` +${p.groups - 1}` : ""}</span>` : "No login in this demo";
}

function vaRender(selectedId) {
  const groups = new Map();
  for (const p of va.people) for (const m of p.memberships) {
    if (!groups.has(m.group_id)) groups.set(m.group_id, { name: m.group_name, people: [] });
    groups.get(m.group_id).people.push({ ...p, role: m.role, gid: m.group_id });
  }
  const order = { president: 0, treasurer: 1, member: 2 };
  const sections = [...groups.values()].map((g) => [g.name, g.people.sort((a, b) => order[a.role] - order[b.role] || a.name.localeCompare(b.name))]);
  const loners = va.people.filter((p) => !p.memberships.length).map((p) => ({ ...p, gid: 0 }));
  if (loners.length) sections.push(["Not in a group yet", loners]);
  let i = 0;
  $("#vaMenu").innerHTML = sections.map(([title, list]) => `<li class="va-head" role="presentation">${esc(title)}</li>` + list.map((p) => `
      <li class="va-opt" role="option" id="va-${p.id}-${p.gid}" data-id="${p.id}" data-idx="${i}" style="--i:${Math.min(i++, 12)}" aria-selected="${p.id === selectedId}">
        <span class="avatar sm r-${p.role}" aria-hidden="true">${esc(initials(p.name))}</span>
        <span class="who"><b>${esc(p.name)}</b><small>${p.gid ? ROLE[p.role] : "Signed up"}${p.groups > 1 ? ` - in ${p.groups} groups` : ""}</small></span><span class="tick" aria-hidden="true">&#10003;</span>
      </li>`).join("")).join("") + `<li class="va-more" aria-hidden="true">Scroll for more people</li>`;
  const menu = $("#vaMenu");
  const atEnd = () => menu.classList.toggle("at-end", menu.scrollTop + menu.clientHeight >= menu.scrollHeight - 12);
  menu.onscroll = atEnd;
  requestAnimationFrame(atEnd);
}

function vaOpts() { return $$("#vaMenu .va-opt"); }
function vaHighlight(idx) {
  const opts = vaOpts();
  va.active = (idx + opts.length) % opts.length;
  opts.forEach((o, n) => o.classList.toggle("active", n === va.active));
  $("#vaMenu").setAttribute("aria-activedescendant", opts[va.active].id);
  opts[va.active].scrollIntoView({ block: "nearest" });
}
function vaOpen() {
  const menu = $("#vaMenu");
  vaRender(state.me?.user.id);
  menu.hidden = false; va.open = true;
  $("#vaBtn").setAttribute("aria-expanded", "true");
  const sel = vaOpts().findIndex((o) => o.getAttribute("aria-selected") === "true");
  vaHighlight(sel >= 0 ? sel : 0);
  menu.focus();
}
function vaClose(focusBtn = true) {
  $("#vaMenu").hidden = true; va.open = false;
  $("#vaBtn").setAttribute("aria-expanded", "false");
  if (focusBtn) $("#vaBtn").focus();
}
async function vaChoose(id) {
  vaClose();
  if (id === state.me?.user.id) return;
  await post("/api/view-as", { user_id: id });
  await load();
}

async function init() {
  va.people = await api("/api/people");
  $("#vaBtn").addEventListener("click", () => (va.open ? vaClose() : vaOpen()));
  $("#vaMenu").addEventListener("click", (ev) => { const o = ev.target.closest(".va-opt"); if (o) vaChoose(+o.dataset.id); });
  $("#vaMenu").addEventListener("mousemove", (ev) => { const o = ev.target.closest(".va-opt"); if (o) vaHighlight(+o.dataset.idx); });
  $("#vaMenu").addEventListener("keydown", (ev) => {
    if (ev.key === "ArrowDown") { ev.preventDefault(); vaHighlight(va.active + 1); }
    else if (ev.key === "ArrowUp") { ev.preventDefault(); vaHighlight(va.active - 1); }
    else if (ev.key === "Home") { ev.preventDefault(); vaHighlight(0); }
    else if (ev.key === "End") { ev.preventDefault(); vaHighlight(-1); }
    else if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); vaChoose(+vaOpts()[va.active].dataset.id); }
    else if (ev.key === "Escape" || ev.key === "Tab") vaClose(ev.key === "Escape");
  });
  $("#vaBtn").addEventListener("keydown", (ev) => { if (ev.key === "ArrowDown") { ev.preventDefault(); vaOpen(); } });
  document.addEventListener("click", (ev) => { if (va.open && !ev.target.closest("#viewAs")) vaClose(false); });
  const join = new URLSearchParams(location.search).get("join");
  let me = null;
  try { me = await api("/api/me"); } catch { /* not signed in yet */ }
  if (me) await load(me); else { state.me = null; showLanding(); }
  if (join) openJoin(join);
}

let showcaseCache = null;
const revealer = "IntersectionObserver" in window && !reduced
  ? new IntersectionObserver((es) => es.forEach((e) => { if (e.isIntersecting) { e.target.classList.add("shown"); revealer.unobserve(e.target); } }), { threshold: 0.12 })
  : null;
function reveal(root) { $$(".reveal", root).forEach((el) => (revealer ? revealer.observe(el) : el.classList.add("shown"))); }

async function renderShowcase() {
  try { showcaseCache = showcaseCache || await api("/api/showcase"); } catch { showcaseCache = []; }
  $("#showcase").innerHTML = showcaseCache.map((g) => {
    const t = g.people.find((p) => p.role === "treasurer") || g.people[0];
    return `<article class="sc">
      <span class="cat">${esc(g.kind || "Group")}</span>
      <h3>${esc(g.name)}</h3>
      <p class="sc-desc">${esc(g.blurb || "")}</p>
      <div class="sc-members">
        <span class="sc-label">Members</span>
        <div class="sc-mrow"><div class="faces">${g.people.map((p) => `<span class="avatar sm r-${p.role}" title="${esc(p.name)}, ${ROLE[p.role].toLowerCase()}">${esc(initials(p.name))}</span>`).join("")}</div>
          <span class="sc-count">${g.people.length} members</span></div>
      </div>
      <hr class="sc-div">
      <div class="sc-stats">
        <div><b>${naira(g.balance_kobo)}</b><small>Current balance</small></div>
        <div><b>${g.verified_entries}</b><small>Verified records</small></div>
      </div>
      <button type="button" class="primary sc-open" data-demo-as="${t.id}" data-demo-group="${g.id}">Open as ${esc(t.name.split(" ")[0])}, treasurer</button>
      <button type="button" class="sc-alt" data-demo-pick="${g.id}">View as another member <span aria-hidden="true">&#8594;</span></button>
    </article>`;
  }).join("");
}

function showLanding() {
  if (!state.me) vaSet(null);
  $("#app").classList.add("hidden"); $("#flow").classList.add("hidden"); $("#groupRow").classList.add("hidden");
  $("#chatWrap").classList.add("hidden"); chatClose();
  $("#groupTitle").textContent = "Every contribution, in the open.";
  $("#groupMeta").textContent = "A shared ledger for savings groups and cooperatives.";
  $("#chooser").classList.remove("hidden");
  const me = state.me, groups = me?.groups || [];
  $("#btnSignupStart").textContent = me ? "Create a group" : "Sign up and create a group";
  $("#signoutRow").classList.toggle("hidden", !me);
  if (me) $("#signedInName").textContent = me.user.name;
  $("#yourGroupsSec").classList.toggle("hidden", !groups.length);
  $("#welcomeTitle").textContent = me ? `Welcome back, ${me.user.name.split(" ")[0]}` : "Your groups";
  $("#myGroups").innerHTML = groups.map((g, i) => `<div class="card rise" style="--i:${i}" data-open-group="${g.id}" role="button" tabindex="0">
      <span class="cat">${ROLE[g.role]}</span><h4>${esc(g.name)}</h4><div class="gcard-go">Open ledger &#8594;</div></div>`).join("");
  renderShowcase();
  reveal($("#chooser"));
}

const lastGroupKey = (uid) => `tl.lastGroup.${uid}`;
function rememberGroup(uid, gid) { try { localStorage.setItem(lastGroupKey(uid), gid); } catch { /* storage unavailable */ } }
function recalledGroup(uid) { try { return +localStorage.getItem(lastGroupKey(uid)) || null; } catch { return null; } }

async function load(me, groupId) {
  me = me || await api("/api/me");
  va.people = await api("/api/people");
  state.me = me;
  vaSet(va.people.find((p) => p.id === me.user.id) || { ...me.user, role: "member", group_name: "No group yet", groups: 0 });
  if (!me.groups.length) {
    showLanding();
    vaSet(va.people.find((p) => p.id === me.user.id));
    return;
  }
  $("#chooser").classList.add("hidden");
  const ids = me.groups.map((g) => g.id);
  state.groupId = [groupId, recalledGroup(me.user.id), state.groupId].find((g) => ids.includes(g)) || ids[0];
  rememberGroup(me.user.id, state.groupId);
  $("#groupRow").classList.remove("hidden");
  const sw = $("#groupSwitch");
  sw.classList.toggle("hidden", me.groups.length < 2);
  if (me.groups.length > 1) {
    makeSelect($(".cselect", sw), me.groups.map((g) => ({ value: g.id, label: g.name, sub: ROLE[g.role], group: "Your groups" })),
      state.groupId, async (v) => { state.groupId = +v; rememberGroup(me.user.id, +v); state.intro = true; await refresh(); setTimeout(() => (state.intro = false), 50); });
  }
  state.intro = true;
  $("#askLog").innerHTML = ""; $("#chatLog").innerHTML = "";
  state.ledgerPage = 1; state.ledgerQ = ""; $("#ledgerSearch").value = "";
  $("#chatWrap").classList.remove("hidden");
  $("#app").classList.remove("hidden");
  await refresh();
  setTimeout(() => (state.intro = false), 50);
}

async function refresh() {
  const g = state.groupId;
  [state.overview, state.entries] = await Promise.all([api(`/api/groups/${g}`), api(`/api/groups/${g}/entries`)]);
  const o = state.overview;
  $("#groupTitle").textContent = o.group.name;
  $("#groupMeta").textContent = `${o.members.length} members - you are viewing as ${state.me.user.name}, ${ROLE[o.my_role].toLowerCase()}`;
  const leader = ["president", "treasurer"].includes(o.my_role);
  $("#btnOut").classList.toggle("hidden", !leader);
  $("#btnAddOb").classList.toggle("hidden", !leader);
  $("#btnOut2").classList.toggle("hidden", !leader);
  renderFlow(); renderOverview(); renderAttention(); renderLedger(); renderMembers();
  if (state.tab === "activity") renderActivity();
}

function renderFlow() {
  const t = state.overview.totals, f = $("#flow");
  f.classList.remove("hidden");
  f.innerHTML = `
    <div class="node"><small>Total inflow</small><b id="fIn"></b></div>
    <div class="op" aria-hidden="true">&minus;</div>
    <div class="node out"><small>Total outflow</small><b id="fOut"></b></div>
    <div class="op" aria-hidden="true">=</div>
    <div class="node pot"><small>In the pot now</small><b id="fPot"></b></div>
    ${t.awaiting ? `<button class="waiting" data-goto="attention">${t.awaiting} waiting for a second person to confirm</button>` : ""}`;
  countUp($("#fIn"), t.in_kobo); countUp($("#fOut"), t.out_kobo); countUp($("#fPot"), t.balance_kobo);
}

function renderOverview() {
  const { obligations, today } = state.overview;
  const card = (ob, i) => {
    const s = ob.summary, pct = (x) => s.target_kobo ? Math.min(100, (x / s.target_kobo) * 100).toFixed(1) : 0;
    const past = ob.due_date < today;
    return `<div class="card${rise(i)}">
      <span class="cat">${CAT[ob.category] || "Goal"}</span>
      <h4>${esc(ob.title)}</h4>
      <div class="meta">${naira(ob.amount_due_kobo)} per member - ${past ? "was due" : "due"} ${fmtDate(ob.due_date)}</div>
      <div class="bar"><i class="v" data-w="${pct(s.collected_kobo)}"></i><i class="p" data-w="${pct(s.collected_pending_kobo)}"></i></div>
      <div class="row"><span>Collected and verified</span><b>${naira(s.collected_kobo)} of ${naira(s.target_kobo)}</b></div>
      ${s.collected_pending_kobo ? `<div class="row"><span>Waiting to be confirmed</span><b>${naira(s.collected_pending_kobo)}</b></div>` : ""}
      <div class="row"><span>Spent</span><b>${naira(s.spent_kobo)}${s.spent_pending_kobo ? ` (+${naira(s.spent_pending_kobo)} pending)` : ""}</b></div>
      <div class="row"><span>Left in this pot</span><b>${naira(s.balance_kobo)}</b></div>
    </div>`;
  };
  const seriesCard = (name, list, i) => {
    const sum = (k) => list.reduce((a, o) => a + o.summary[k], 0);
    const past = list.filter((o) => o.due_date < today), next = list.filter((o) => o.due_date >= today);
    const shown = [...past.slice(-6), ...next.slice(0, 2)];
    const hidden = list.length - shown.length;
    const freq = list[0].category === "monthly" ? "every month" : "every week";
    return `<div class="card${rise(i)}">
      <span class="cat">${list[0].category === "monthly" ? "Monthly" : "Weekly"}</span><h4>${esc(name)}</h4>
      <div class="meta">${naira(list[0].amount_due_kobo)} per member ${freq} - ${past.length} of ${list.length} due so far${next[0] ? `, next ${fmtDate(next[0].due_date)}` : ""}</div>
      <div class="row" style="margin-top:10px"><span>Collected and verified</span><b>${naira(sum("collected_kobo"))} of ${naira(past.reduce((a, o) => a + o.summary.target_kobo, 0))} due</b></div>
      ${sum("collected_pending_kobo") ? `<div class="row"><span>Waiting to be confirmed</span><b>${naira(sum("collected_pending_kobo"))}</b></div>` : ""}
      <div class="row"><span>Left in this pot</span><b>${naira(sum("balance_kobo"))}</b></div>
      <div style="margin-top:8px">${shown.map((o) => { const s = o.summary, p = s.target_kobo ? Math.min(100, s.collected_kobo / s.target_kobo * 100).toFixed(1) : 0,
          q = s.target_kobo ? Math.min(100, s.collected_pending_kobo / s.target_kobo * 100).toFixed(1) : 0;
        return `<div class="week"><span>${esc(o.title.replace(name + " - ", ""))}</span><div class="bar"><i class="v" data-w="${p}"></i><i class="p" data-w="${q}"></i></div><small>${o.due_date >= today ? "upcoming" : naira(s.collected_kobo)}</small></div>`; }).join("")}</div>
      ${hidden > 0 ? `<div class="series-more">+${hidden} more ${list[0].category === "monthly" ? "months" : "weeks"} in the schedule</div>` : ""}
    </div>`;
  };
  const goals = obligations.filter((o) => !o.series);
  const series = [...new Set(obligations.filter((o) => o.series).map((o) => o.series))];
  $("#obligations").innerHTML = goals.length || series.length
    ? goals.map(card).join("") + series.map((n, i) => seriesCard(n, obligations.filter((o) => o.series === n), goals.length + i)).join("")
    : `<div class="empty"><h2>No contributions yet</h2><p>Add a recurring contribution or a one-off goal to start tracking money in.</p></div>`;
  fillBars($("#obligations"));
}

function aiLine(e) {
  if (e.source === "whatsapp_import") {
    return `<div class="ai"><span>From the chat: <b>"${esc((e.source_text || "").slice(0, 140))}"</b></span><small>${esc(e.read_by || "")}</small></div>`;
  }
  if (!e.read_by) return "";
  const x = e.extracted;
  if (!x) return `<div class="ai">Checked by ${esc(e.read_by)}</div>`;
  const parts = [x.amount_text, x.date_text, e.direction === "in" ? x.sender_name : x.recipient_name].filter(Boolean).map(esc);
  return `<div class="ai"><span>Read on the receipt: <b>${parts.join(" - ") || "nothing readable"}</b></span><small>${esc(e.read_by)}${e.read_ms ? `, ${(e.read_ms / 1000).toFixed(1)}s` : ""}</small></div>`;
}

function whoLine(e) {
  return e.direction === "in"
    ? `<b>${esc(e.member)}</b>${e.matched ? "" : " (not a member yet)"} paid <b>${esc(e.amount)}</b> for ${esc(e.obligation)}`
    : `<b>${esc(e.created_by)}</b> paid out <b>${esc(e.amount)}</b> to ${esc(e.counterparty)} from ${esc(e.obligation)}${e.description ? ` (${esc(e.description)})` : ""}`;
}

const ATTN = {
  needs_review: ["Needs review", "Something does not match. Look at the reasons and the receipt before deciding."],
  documented: ["Ready to confirm", "The receipt matches what was entered. A second person just needs to confirm it."],
  reported: ["No proof yet", "Recorded on the member's word, with no receipt. Confirm only if you know it was paid."],
};
state.attnFilter = "all";

function attnCard(e, i) {
  const icon = (r) => /^Proof matches/.test(r) ? "ok" : /^No proof/.test(r) ? "info" : "warn";
  const who = e.direction === "in" ? `<b>${esc(e.member)}</b>${e.matched ? "" : " <span class=\"meta\">(not a member yet)</span>"}`
                                   : `<b>${esc(e.created_by)}</b> paid <b>${esc(e.counterparty)}</b>`;
  return `<article class="att ${e.status}${rise(i)}" data-entry="${e.id}">
    <div class="att-proof">${e.has_proof
      ? `<img src="/api/groups/${state.groupId}/entries/${e.id}/proof" alt="Receipt for entry ${e.id}" data-proof="${e.id}">`
      : `<span class="noproof">No receipt</span>`}</div>
    <div class="att-body">
      <div class="att-title">${who} <span class="att-for">${e.direction === "in" ? "for" : "from"} ${esc(e.obligation)}</span></div>
      <div class="meta">${e.direction === "in" ? "Money in" : "Money out"} - ${fmtDate(e.occurred_on)} - entry #${e.id} - recorded by ${esc(e.created_by)}</div>
      <ul class="reasons">${e.reasons.map((r) => `<li class="${icon(r)}">${esc(r)}</li>`).join("")}</ul>
      ${aiLine(e)}
    </div>
    <div class="att-side">
      <div class="att-amt ${e.direction}">${e.direction === "in" ? "+" : "-"}${esc(e.amount)}</div>
      ${e.can_decide
        ? `<div class="att-btns"><button class="secondary sm" data-reject="${e.id}">Reject</button><button class="primary sm" data-verify="${e.id}">Verify</button></div>`
        : `<div class="lock">${esc(e.cannot_decide_reason)}</div>`}
    </div>
  </article>`;
}

function renderAttention() {
  const items = state.entries.filter((e) => e.status in ATTN).sort((a, b) => b.occurred_on.localeCompare(a.occurred_on) || b.id - a.id);
  const badge = $("#attnCount");
  if (state.lastAttn !== null && state.lastAttn !== items.length) { badge.classList.remove("bump"); void badge.offsetWidth; badge.classList.add("bump"); }
  state.lastAttn = items.length;
  badge.textContent = items.length;
  if (!items.length) {
    $("#attention").innerHTML = `<div class="empty"><h2>All clear</h2><p>Every payment and payout has been confirmed by a second person.</p></div>`;
    return;
  }
  const count = (k) => items.filter((e) => e.status === k).length;
  const f = state.attnFilter in ATTN && count(state.attnFilter) ? state.attnFilter : "all";
  const tabs = [["all", "All", items.length], ...Object.keys(ATTN).map((k) => [k, ATTN[k][0], count(k)])]
    .map(([k, l, n]) => `<button class="${k === f ? "active" : ""} f-${k}" data-attn="${k}" ${n ? "" : "disabled"}>${l} <span>${n}</span></button>`).join("");
  let i = 0;
  const sections = Object.keys(ATTN).filter((k) => (f === "all" || f === k) && count(k)).map((k) => `
    <section class="att-sec">
      <header><h3><span class="chip s-${k}">${ATTN[k][0]}</span> <span class="n">${count(k)}</span></h3><p>${ATTN[k][1]}</p></header>
      ${items.filter((e) => e.status === k).map((e) => attnCard(e, i++)).join("")}
    </section>`).join("");
  $("#attention").innerHTML = `<div class="filters att-filters">${tabs}</div>${sections}`;
}

function renderLedger() {
  const asc = [...state.entries].sort((a, b) => a.occurred_on.localeCompare(b.occurred_on) || a.id - b.id);
  let bal = 0; const after = {};
  for (const e of asc) {
    if (e.status === "verified") bal += (e.direction === "in" ? 1 : -1) * e.amount_kobo;
    after[e.id] = e.status === "verified" ? bal : null;
  }
  const t = state.overview.totals;
  const waiting = state.entries.filter((e) => ["reported", "documented", "needs_review"].includes(e.status))
    .reduce((a, e) => a + (e.direction === "in" ? 1 : -1) * e.amount_kobo, 0);
  $("#ledgerSummary").innerHTML = [["Verified balance", naira(t.balance_kobo), "hl"], ["Money in (verified)", naira(t.in_kobo)],
    ["Money out (verified)", naira(t.out_kobo)], ["Waiting to be confirmed", `${waiting < 0 ? "-" : ""}${naira(Math.abs(waiting))}`]]
    .map(([k, v, c]) => `<div class="${c || ""}"><small>${k}</small><b>${v}</b></div>`).join("");
  const q = (state.ledgerQ || "").toLowerCase();
  const rows = state.entries.filter((e) => (state.filter === "all" || e.direction === state.filter) &&
    (!q || [e.member, e.counterparty, e.obligation, e.description, e.created_by].some((v) => (v || "").toLowerCase().includes(q))));
  const per = 10, pages = Math.max(1, Math.ceil(rows.length / per));
  state.ledgerPage = Math.min(Math.max(1, state.ledgerPage || 1), pages);
  const start = (state.ledgerPage - 1) * per, pageRows = rows.slice(start, start + per);
  const roleOf = Object.fromEntries(state.overview.members.map((m) => [m.id, m.role]));
  const RC = `<svg viewBox="0 0 24 24"><path d="M6 3h12v18l-3-2-3 2-3-2-3 2z"/><path d="M9 8h6M9 12h6"/></svg>`;
  $("#ledgerBody").innerHTML = pageRows.length ? pageRows.map((e, i) => {
    const d = new Date(e.occurred_on + "T12:00:00");
    const name = e.direction === "in" ? e.member : e.counterparty;
    const av = e.direction === "in" ? `avatar sm r-${roleOf[e.member_id] || "member"}` : "avatar sm out-av";
    return `<tr style="--i:${i}">
      <td class="d"><b>${d.toLocaleDateString("en-GB", { day: "numeric", month: "short" })}</b><small>${d.getFullYear()}</small></td>
      <td class="who"><div class="who-cell"><span class="${av}">${esc(initials(name || "?"))}</span><div><b>${esc(name)}</b>
        <small>${e.direction === "in" ? "Paid for" : "Paid out from"} ${esc(e.obligation)}${e.description ? ` - ${esc(e.description)}` : ""}</small></div></div></td>
      <td class="st">${chip(e.status)}${e.decided_by ? `<small>by ${esc(e.decided_by)}</small>` : ""}</td>
      <td class="num amt ${e.direction}">${e.direction === "in" ? "+" : "-"}${esc(e.amount)}</td>
      <td class="num bal">${after[e.id] === null ? `<span class="nc">not counted yet</span>` : naira(after[e.id])}</td>
      <td class="c">${e.has_proof ? `<a class="rcpt" href="/api/groups/${state.groupId}/entries/${e.id}/proof" target="_blank" rel="noopener" title="View receipt" aria-label="View receipt for entry ${e.id}">${RC}</a>` : `<span class="norcpt">None</span>`}</td></tr>`;
  }).join("") : `<tr class="lempty"><td colspan="6">No entries match. Try another name or clear the search.</td></tr>`;
  const nums = [];
  for (let n = 1; n <= pages; n++) if (n === 1 || n === pages || Math.abs(n - state.ledgerPage) <= 1) nums.push(n); else if (nums[nums.length - 1] !== "gap") nums.push("gap");
  $("#ledgerPager").innerHTML = rows.length ? `<span class="count">Showing ${start + 1}-${start + pageRows.length} of ${rows.length}</span>
    <div class="pages"><button data-lpage="${state.ledgerPage - 1}" ${state.ledgerPage === 1 ? "disabled" : ""} aria-label="Previous page">&#8249;</button>
    ${nums.map((n) => n === "gap" ? `<span class="gap">...</span>` : `<button data-lpage="${n}" class="${n === state.ledgerPage ? "on" : ""}" ${n === state.ledgerPage ? 'aria-current="page"' : ""}>${n}</button>`).join("")}
    <button data-lpage="${state.ledgerPage + 1}" ${state.ledgerPage === pages ? "disabled" : ""} aria-label="Next page">&#8250;</button></div>` : "";
}

function renderMembers() {
  $("#members").innerHTML = state.overview.members.map((m, i) =>
    `<div class="card member${rise(i)}" data-member="${m.id}" tabindex="0" role="button"><span class="avatar">${esc(initials(m.name))}</span>
      <div><h4>${esc(m.name)}</h4><div class="meta">${ROLE[m.role]}</div></div></div>`).join("");
}

async function showRecord(id) {
  $$("#members .member").forEach((c) => c.classList.toggle("sel", c.dataset.member === String(id)));
  const r = await api(`/api/groups/${state.groupId}/members/${id}/record`);
  const c = r.counts;
  const label = { on_time: "Paid on time", late: "Paid late", partial: "Part paid", missed: "Missed", upcoming: "Upcoming" };
  const cls = { on_time: "verified", late: "needs_review", partial: "needs_review", missed: "rejected", upcoming: "reported" };
  $("#record").innerHTML = `<div class="card record rise" style="margin-top:16px">
    <h3>${esc(r.member.name)}'s payment record</h3>
    <p class="hint" style="margin-top:4px">Facts only, counted from verified payments. No score, no judgement.</p>
    <div class="counts">${Object.keys(label).map((k, i) => `<span class="chip s-${cls[k]} rise" style="--i:${i}">${label[k]}: ${c[k]}</span>`).join("")}</div>
    <div class="table-wrap"><table class="ledger"><thead><tr><th>Obligation</th><th>Due</th><th class="num">Due amount</th><th class="num">Paid</th><th>Status</th></tr></thead><tbody>
    ${r.rows.map((x) => `<tr><td>${esc(x.title)}</td><td>${fmtDate(x.due_date)}</td><td class="num">${naira(x.due_kobo)}</td>
      <td class="num">${naira(x.paid_kobo)}${x.pending_kobo ? ` <small>(+${naira(x.pending_kobo)} waiting)</small>` : ""}</td>
      <td><span class="chip s-${cls[x.state]}">${label[x.state]}</span></td></tr>`).join("")}
    </tbody></table></div></div>`;
  $("#record").scrollIntoView({ behavior: reduced ? "auto" : "smooth", block: "start" });
}

function pagerHtml(total, page, per, attr) {
  const pages = Math.max(1, Math.ceil(total / per));
  if (!total) return "";
  const start = (page - 1) * per, nums = [];
  for (let n = 1; n <= pages; n++) if (n === 1 || n === pages || Math.abs(n - page) <= 1) nums.push(n); else if (nums[nums.length - 1] !== "gap") nums.push("gap");
  return `<span class="count">Showing ${start + 1}-${Math.min(start + per, total)} of ${total}</span>
    <div class="pages"><button ${attr}="${page - 1}" ${page === 1 ? "disabled" : ""} aria-label="Previous page">&#8249;</button>
    ${nums.map((n) => n === "gap" ? `<span class="gap">...</span>` : `<button ${attr}="${n}" class="${n === page ? "on" : ""}" ${n === page ? 'aria-current="page"' : ""}>${n}</button>`).join("")}
    <button ${attr}="${page + 1}" ${page === pages ? "disabled" : ""} aria-label="Next page">&#8250;</button></div>`;
}

async function renderActivity(keepPage) {
  const all = await api(`/api/groups/${state.groupId}/events`);
  const per = 12, pages = Math.max(1, Math.ceil(all.length / per));
  state.eventsPage = keepPage ? Math.min(Math.max(1, state.eventsPage || 1), pages) : 1;
  const offset = (state.eventsPage - 1) * per;
  const ev = all.slice(offset, offset + per);
  $("#eventsPager").innerHTML = pagerHtml(all.length, state.eventsPage, per, "data-epage");
  const ent = Object.fromEntries(state.entries.map((e) => [e.id, e]));
  $("#events").classList.remove("sealing", "broken");
  $("#verifyResult").innerHTML = "";
  $("#events").innerHTML = ev.map((x, i) => {
    const e = ent[x.entry_id];
    const plain = (h) => h.replace(/<[^>]+>/g, "");
    const d = x.detail;
    const what = {
      entry_recorded: () => `recorded: ${e ? plain(whoLine(e)) : "an entry"}`,
      entry_imported: () => `imported from WhatsApp: ${e ? plain(whoLine(e)) : "a payment claim"}`,
      entry_decided: () => `${d.decision === "verified" ? "verified" : "rejected"} entry #${x.entry_id}${d.note ? ` - "${d.note}"` : ""}`,
      group_created: () => `created the group${d.from === "whatsapp" ? ` from a WhatsApp chat of ${d.messages} messages` : ""}`,
      member_added: () => `added a ${d.role}`,
      obligation_added: () => d.series ? `added ${d.series}: ${naira(d.amount_kobo)} x ${d.periods}` : `added the goal "${d.title}" (${naira(d.amount_kobo)} each)`,
    }[x.action]?.() || x.action;
    return `<li style="--i:${i}" class="rise"><b>${esc(x.actor)}</b> ${esc(what)} <span class="meta">- ${new Date(x.created_at).toLocaleString("en-GB", { dateStyle: "medium", timeStyle: "short" })}</span><br><code>seal ${esc(x.hash)}</code></li>`;
  }).join("");
}

// Redraw part of the page without the scroll position jumping: keep `anchorSel` fixed on screen.
function keepPlace(anchorSel, redraw) {
  const a = $(anchorSel), before = a ? a.getBoundingClientRect().top : null;
  redraw();
  const b = $(anchorSel);
  if (b && before !== null) scrollBy({ top: b.getBoundingClientRect().top - before, behavior: "instant" });
}

// ---------- confirmation box ----------
function confirmBox({ title, body, ok = "Confirm", tone = "info" }) {
  return new Promise((resolve) => {
    const d = $("#dlgConfirm");
    $("#cfTitle").textContent = title;
    $("#cfBody").innerHTML = body;
    $("#cfIcon").className = `cf-icon ${tone}`;
    $("#cfOk").textContent = ok;
    $("#cfOk").className = tone === "danger" ? "danger" : "primary";
    d.returnValue = "";
    d.addEventListener("close", () => resolve(d.returnValue === "ok"), { once: true });
    d.showModal();
    $("#cfOk").focus();
  });
}
const sumList = (pairs) => `<dl class="cf-sum">${pairs.filter(([, v]) => v).map(([k, v]) => `<dt>${esc(k)}</dt><dd>${esc(v)}</dd>`).join("")}</dl>`;

// ---------- custom controls: select, date picker, file drop ----------
const CHEV = `<svg class="va-chev" width="12" height="8" viewBox="0 0 12 8" aria-hidden="true"><path d="M1 1l5 5 5-5" fill="none" stroke="currentColor" stroke-width="2"/></svg>`;
const popovers = new Set();
function closeAllPopovers() { for (const p of [...popovers]) p.close(); }
function placePopover(anchor, pop) {
  // Float the popup at viewport level so no form or dialog edge can clip it.
  const r = anchor.getBoundingClientRect(), gap = 6, pad = 8;
  Object.assign(pop.style, { position: "fixed", right: "auto", bottom: "auto", maxHeight: "" });
  if (pop.classList.contains("cs-menu")) pop.style.width = `${r.width}px`;
  const w = pop.offsetWidth, h = pop.offsetHeight;
  const below = innerHeight - r.bottom - gap - pad, above = r.top - gap - pad;
  let top;
  if (h <= below || below >= above) {
    top = r.bottom + gap;
    if (h > below) pop.style.maxHeight = `${Math.max(160, below)}px`;
  } else {
    top = Math.max(pad, r.top - gap - Math.min(h, above));
    if (h > above) pop.style.maxHeight = `${above}px`;
  }
  pop.style.top = `${top}px`;
  pop.style.left = `${Math.max(pad, Math.min(r.left, innerWidth - w - pad))}px`;
}
// A floating popup would drift away from its field if the page scrolls, so close it instead.
addEventListener("scroll", (ev) => {
  if ([...popovers].some((p) => p.root.contains(ev.target) && ev.target !== p.root && ev.target.closest?.(".cs-menu, .cal, .va-menu, .chat-panel"))) return;
  for (const p of [...popovers]) if (p.root.id !== "chatWrap") p.close();
}, true);
addEventListener("resize", () => { for (const p of [...popovers]) if (p.root.id !== "chatWrap") p.close(); });
document.addEventListener("pointerdown", (ev) => {
  for (const p of [...popovers]) if (!p.root.contains(ev.target)) p.close();
}, true);
const uidOf = () => "c" + Math.random().toString(36).slice(2, 8);
const pad = (n) => String(n).padStart(2, "0");
const isoOf = (d) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
const dateOf = (s) => { const [y, m, d] = s.split("-").map(Number); return new Date(y, m - 1, d); };

function makeSelect(root, options, value, onChange) {
  const uid = uidOf(), lbl = root.dataset.labelledby || "";
  root.innerHTML = `<input type="hidden" name="${esc(root.dataset.name)}">
    <button type="button" class="cs-btn" aria-haspopup="listbox" aria-expanded="false" aria-labelledby="${lbl} ${uid}-v">
      <span class="cs-dot"></span><span class="cs-val" id="${uid}-v"><b></b><small></small></span>${CHEV}</button>
    <ul class="cs-menu" role="listbox" tabindex="-1" hidden aria-labelledby="${lbl}"></ul>`;
  const input = $("input", root), btn = $(".cs-btn", root), menu = $(".cs-menu", root);
  let active = -1, pop = null;
  const set = (v) => {
    const o = options.find((x) => String(x.value) === String(v)) || options[0];
    const changed = input.value !== String(o.value);
    input.value = o.value; $("b", btn).textContent = o.label; $("small", btn).textContent = o.sub || "";
    $(".cs-dot", btn).className = `cs-dot ${o.cat || "none"}`;
    if (changed && onChange) onChange(o.value);
  };
  const render = () => {
    let i = 0;
    menu.innerHTML = [...new Set(options.map((o) => o.group))].map((g) => `<li class="va-head" role="presentation">${esc(g)}</li>` +
      options.filter((o) => o.group === g).map((o) => `<li class="cs-opt" role="option" id="${uid}-${i}" data-idx="${i}" data-v="${esc(o.value)}" style="--i:${i++}" aria-selected="${String(o.value) === input.value}">
        ${o.cat ? `<span class="cs-dot ${o.cat}"></span>` : ""}<span class="who"><b>${esc(o.label)}</b><small>${esc(o.sub || "")}</small></span><span class="tick" aria-hidden="true">&#10003;</span></li>`).join("")).join("");
  };
  const opts = () => $$(".cs-opt", menu);
  const hi = (n) => {
    const os = opts(); active = (n + os.length) % os.length;
    os.forEach((o, k) => o.classList.toggle("active", k === active));
    menu.setAttribute("aria-activedescendant", os[active].id);
    const o = os[active];
    if (o.offsetTop < menu.scrollTop) menu.scrollTop = o.offsetTop;
    else if (o.offsetTop + o.offsetHeight > menu.scrollTop + menu.clientHeight) menu.scrollTop = o.offsetTop + o.offsetHeight - menu.clientHeight;
  };
  const close = (focus = true) => {
    menu.hidden = true; btn.setAttribute("aria-expanded", "false");
    if (pop) { popovers.delete(pop); pop = null; }
    if (focus) btn.focus();
  };
  const open = () => {
    closeAllPopovers(); render(); menu.hidden = false; btn.setAttribute("aria-expanded", "true"); placePopover(btn, menu);
    pop = { root, close: () => close(false) }; popovers.add(pop);
    const s = opts().findIndex((o) => o.getAttribute("aria-selected") === "true");
    hi(s < 0 ? 0 : s); menu.focus({ preventScroll: true });
  };
  btn.onclick = () => (menu.hidden ? open() : close());
  btn.onkeydown = (e) => { if (e.key === "ArrowDown" || e.key === "ArrowUp") { e.preventDefault(); open(); } };
  menu.onclick = (e) => { const o = e.target.closest(".cs-opt"); if (o) { set(o.dataset.v); close(); } };
  menu.onmousemove = (e) => { const o = e.target.closest(".cs-opt"); if (o && +o.dataset.idx !== active) hi(+o.dataset.idx); };
  menu.onkeydown = (e) => {
    if (e.key === "ArrowDown") { e.preventDefault(); hi(active + 1); }
    else if (e.key === "ArrowUp") { e.preventDefault(); hi(active - 1); }
    else if (e.key === "Home") { e.preventDefault(); hi(0); }
    else if (e.key === "End") { e.preventDefault(); hi(-1); }
    else if (e.key === "Enter" || e.key === " ") { e.preventDefault(); set(opts()[active].dataset.v); close(); }
    else if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); close(); }
    else if (e.key === "Tab") close(false);
  };
  set(value);
  root._set = set;
}

function makeDate(root, value, max) {
  root.innerHTML = `<input type="hidden" name="${esc(root.dataset.name)}">
    <button type="button" class="cs-btn" aria-haspopup="dialog" aria-expanded="false">
      <svg width="18" height="18" viewBox="0 0 24 24" aria-hidden="true" style="color:var(--indigo)"><rect x="3" y="5" width="18" height="16" rx="3" fill="none" stroke="currentColor" stroke-width="2"/><path d="M3 10h18M8 3v4M16 3v4" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>
      <span class="cs-val"><b></b><small></small></span>${CHEV}</button>
    <div class="cal" role="dialog" aria-label="Choose the date paid" hidden></div>`;
  const input = $("input", root), btn = $(".cs-btn", root), cal = $(".cal", root);
  const todayD = dateOf(state.overview?.today || isoOf(new Date()));
  const maxD = max ? dateOf(max) : null;
  let sel = dateOf(value), view = new Date(sel.getFullYear(), sel.getMonth(), 1), focusD = sel, pop = null;
  const same = (a, b) => isoOf(a) === isoOf(b);
  const rel = (d) => { const n = Math.round((todayD - d) / 864e5);
    return n === 0 ? "Today" : n === 1 ? "Yesterday" : n === -1 ? "Tomorrow" : n > 0 ? `${n} days ago` : `In ${-n} days`; };
  const set = (d) => {
    sel = d; input.value = isoOf(d);
    $("b", btn).textContent = d.toLocaleDateString("en-GB", { weekday: "short", day: "numeric", month: "short", year: "numeric" });
    $("small", btn).textContent = rel(d);
  };
  const render = (dir = 0) => {
    const first = new Date(view.getFullYear(), view.getMonth(), 1);
    const days = new Date(view.getFullYear(), view.getMonth() + 1, 0).getDate();
    const lead = (first.getDay() + 6) % 7;
    const nextOk = !maxD || new Date(view.getFullYear(), view.getMonth() + 1, 1) <= maxD;
    let cells = ["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"].map((d) => `<span class="dow">${d}</span>`).join("") + "<span></span>".repeat(lead);
    for (let n = 1; n <= days; n++) {
      const d = new Date(view.getFullYear(), view.getMonth(), n);
      const cls = ["cal-day", same(d, todayD) && "today", same(d, sel) && "sel", same(d, focusD) && "focus"].filter(Boolean).join(" ");
      cells += `<button type="button" class="${cls}" data-d="${isoOf(d)}" ${maxD && d > maxD ? "disabled" : ""} tabindex="${same(d, focusD) ? 0 : -1}" aria-label="${d.toLocaleDateString("en-GB", { weekday: "long", day: "numeric", month: "long" })}" aria-pressed="${same(d, sel)}">${n}</button>`;
    }
    cal.innerHTML = `<div class="cal-head"><button type="button" class="cal-nav" data-m="-1" aria-label="Previous month">&#8249;</button>
      <b>${first.toLocaleDateString("en-GB", { month: "long", year: "numeric" })}</b>
      <button type="button" class="cal-nav" data-m="1" aria-label="Next month" ${nextOk ? "" : "disabled"}>&#8250;</button></div>
      <div class="cal-grid ${dir ? "cal-slide" : ""}" style="--dir:${dir * 14}px">${cells}</div>
      <div class="cal-quick">${maxD ? `<button type="button" data-q="0">Today</button><button type="button" data-q="1">Yesterday</button>`
        : `<button type="button" data-q="0">Today</button><button type="button" data-q="-7">In a week</button><button type="button" data-q="-30">In a month</button>`}</div>`;
  };
  const focusDay = () => $(`.cal-day[data-d="${isoOf(focusD)}"]`, cal)?.focus({ preventScroll: true });
  const moveFocus = (d) => {
    if (maxD && d > maxD) d = maxD;
    const dir = d.getMonth() !== view.getMonth() || d.getFullYear() !== view.getFullYear() ? (d > focusD ? 1 : -1) : 0;
    focusD = d; if (dir) view = new Date(d.getFullYear(), d.getMonth(), 1);
    render(dir); focusDay();
  };
  const close = (focus = true) => {
    cal.hidden = true; btn.setAttribute("aria-expanded", "false");
    if (pop) { popovers.delete(pop); pop = null; }
    if (focus) btn.focus();
  };
  const open = () => {
    closeAllPopovers(); focusD = sel; view = new Date(sel.getFullYear(), sel.getMonth(), 1);
    render(); cal.hidden = false; btn.setAttribute("aria-expanded", "true"); placePopover(btn, cal);
    pop = { root, close: () => close(false) }; popovers.add(pop); focusDay();
  };
  btn.onclick = () => (cal.hidden ? open() : close());
  cal.onclick = (e) => {
    const t = e.target.closest("button"); if (!t || t.disabled) return;
    if (t.dataset.m) { const m = +t.dataset.m; view = new Date(view.getFullYear(), view.getMonth() + m, 1); render(m); }
    else if (t.dataset.d) { set(dateOf(t.dataset.d)); close(); }
    else if (t.dataset.q) { set(new Date(todayD.getFullYear(), todayD.getMonth(), todayD.getDate() - +t.dataset.q)); close(); }
  };
  cal.onkeydown = (e) => {
    const step = { ArrowLeft: -1, ArrowRight: 1, ArrowUp: -7, ArrowDown: 7 }[e.key];
    if (step && e.target.classList.contains("cal-day")) { e.preventDefault(); moveFocus(new Date(focusD.getFullYear(), focusD.getMonth(), focusD.getDate() + step)); }
    else if (e.key === "PageUp" || e.key === "PageDown") { e.preventDefault(); moveFocus(new Date(focusD.getFullYear(), focusD.getMonth() + (e.key === "PageUp" ? -1 : 1), focusD.getDate())); }
    else if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); close(); }
  };
  set(sel);
}

function setupDrop(label) {
  const input = $("input[type=file]", label), img = $(".drop-full img", label);
  const err = document.createElement("div"); err.className = "drop-err"; err.hidden = true; label.after(err);
  let url = null;
  const show = () => {
    const f = input.files[0];
    if (url) { URL.revokeObjectURL(url); url = null; }
    err.hidden = true;
    if (!f) { label.classList.remove("has-file"); return; }
    const chat = label.dataset.kind === "chat";
    const bad = chat
      ? (!/\.txt$/i.test(f.name) ? "Choose the .txt file that WhatsApp exported." : f.size > 1024 * 1024 ? "That chat export is larger than 1 MB." : "")
      : !["image/png", "image/jpeg", "image/webp"].includes(f.type) ? "Choose a PNG, JPG or WEBP image."
      : f.size > 5 * 1024 * 1024 ? "That image is larger than 5 MB. Choose a smaller one." : "";
    if (bad) { input.value = ""; label.classList.remove("has-file"); err.textContent = bad; err.hidden = false; return; }
    if (!chat) { url = URL.createObjectURL(f); img.src = url; }
    $(".drop-meta b", label).textContent = f.name;
    $(".drop-meta small", label).textContent = `${Math.max(1, Math.round(f.size / 1024))} KB - ${chat ? "ready to read" : "the AI will read it when you submit"}`;
    label.classList.add("has-file");
    label.dispatchEvent(new CustomEvent("filechosen", { detail: f }));
  };
  input.addEventListener("change", show);
  $(".drop-x", label).addEventListener("click", (e) => { e.preventDefault(); e.stopPropagation(); input.value = ""; show(); });
  label.addEventListener("dragover", (e) => { e.preventDefault(); label.classList.add("over"); });
  label.addEventListener("dragleave", () => label.classList.remove("over"));
  label.addEventListener("drop", (e) => {
    e.preventDefault(); label.classList.remove("over");
    const f = e.dataTransfer.files[0]; if (!f) return;
    const dt = new DataTransfer(); dt.items.add(f); input.files = dt.files; show();
  });
  label._reset = () => { input.value = ""; show(); };
}

function openForm(dlg, obligationId) {
  const f = $("form", dlg), today = state.overview.today;
  f.reset(); closeAllPopovers();
  $(".result", dlg).innerHTML = "";
  const obs = state.overview.obligations;
  const sub = (o) => `${naira(o.amount_due_kobo)} per member - ${o.due_date < today ? "was due" : "due"} ${fmtDate(o.due_date)}`;
  const options = [
    ...obs.filter((o) => o.category !== "weekly").sort((a, b) => a.due_date.localeCompare(b.due_date))
      .map((o) => ({ value: o.id, label: o.title, sub: sub(o), group: "Goals", cat: o.category })),
    ...obs.filter((o) => o.category === "weekly").sort((a, b) => b.due_date.localeCompare(a.due_date))
      .map((o) => ({ value: o.id, label: o.title.replace("Weekly contribution - ", "Weekly - "), sub: sub(o), group: "Weekly contributions", cat: "weekly" })),
  ];
  makeSelect($(".cselect", f), options, obligationId || options[0].value);
  makeDate($(".cdate", f), today, today);
  const ai = state.overview.ai;
  $(".ai-note", dlg).textContent = `Your ${dlg.id === "dlgOut" ? "receipt" : "screenshot"} is read by AI (${ai.primary}${ai.fallback ? `, backup ${ai.fallback}` : ""}) and checked against what you enter. A person always makes the final call.`;
  $(".drop", f)?._reset?.();
  dlg.showModal();
}

async function submitEntry(ev, dlg, url) {
  if (ev.submitter?.value === "cancel") return;
  ev.preventDefault();
  const f = ev.target, out = $(".result", dlg), btn = $("button.primary", f);
  const file = $("[name=proof_file]", f).files[0];
  const isOut = dlg.id === "dlgOut";
  const okGo = await confirmBox({
    title: isOut ? "Record this money out?" : "Record this payment?",
    tone: file ? "info" : "warn",
    ok: "Yes, record it",
    body: sumList([["Amount", `₦${f.amount.value}`], [isOut ? "From" : "For", $(".cselect .cs-btn b", f).textContent],
      ["Paid to", isOut ? f.counterparty.value : ""], ["Date", $(".cdate .cs-btn b", f).textContent],
      ["Receipt", file ? file.name : "None attached"]]) +
      `<p class="meta">${file ? "AI will read the receipt and check it against these details." : "Without a receipt this is recorded on your word only."} A second person must confirm it before it counts.</p>`,
  });
  if (!okGo) return;
  btn.disabled = true;
  let preview = null;
  if (file) {
    preview = URL.createObjectURL(file);
    out.innerHTML = `<div class="scan"><img src="${preview}" alt=""><i></i></div><div class="scanning">AI is reading the receipt<span class="dots"></span></div>`;
  } else out.innerHTML = `<div class="scanning">Saving<span class="dots"></span></div>`;
  try {
    const r = await api(url, { method: "POST", body: new FormData(f) });
    const tone = r.status === "documented" ? "ok" : r.status === "needs_review" ? "warn" : "grey";
    const x = r.extracted;
    out.innerHTML = `<div class="box ${tone}">${chip(r.status)} <b>Entry #${r.id} saved.</b>
      <ul>${r.reasons.map((s) => `<li>${esc(s)}</li>`).join("")}</ul>
      ${x ? `<div class="meta">Read on the receipt: ${esc([x.amount_text, x.date_text, x.sender_name, x.recipient_name].filter(Boolean).join(" - "))} (${esc(r.read_by)})</div>` : ""}
      <div class="meta" style="margin-top:6px">A second person must confirm it before it counts as verified.</div></div>`;
    await refresh();
  } catch (e) {
    out.innerHTML = `<div class="box err">${esc(e.message)}</div>`;
  } finally { btn.disabled = false; if (preview) URL.revokeObjectURL(preview); }
}

async function decide(id, decision, note) {
  const item = $(`.att[data-entry="${id}"]`);
  await post(`/api/groups/${state.groupId}/entries/${id}/decide`, { decision, note: note || "" });
  if (item && !reduced) {
    const who = state.me.user.name.split(" ")[0];
    item.insertAdjacentHTML("beforeend", `<div class="stamp ${decision === "reject" ? "reject" : ""}">${decision === "reject" ? "REJECTED" : "VERIFIED"}<small>by ${esc(who)} - ${fmtDate(state.overview.today)}</small></div>`);
    item.classList.add("thud", "leaving");
    await sleep(1250);
  }
  await refresh();
}

// ---------- Ask TrustLedger ----------
function renderSuggestions() {
  const o = state.overview, me = state.me.user.name.split(" ")[0];
  const goal = o.obligations.find((x) => !x.series);
  const other = o.members.find((m) => m.name !== state.me.user.name);
  const qs = ["What have I paid?", "Who has not paid the latest contribution?", "What is waiting to be confirmed?",
    goal ? `How much is in the ${goal.title.split(" - ")[0].toLowerCase()} fund?` : "How much money does the group have?",
    other ? `Has ${other.name.split(" ")[0]} paid everything?` : "What happened this week?"];
  const chips = qs.map((q) => `<button type="button" data-ask="${esc(q)}">${esc(q)}</button>`).join("");
  $("#askSuggest").innerHTML = chips;
  $("#chatSuggest").innerHTML = chips;
  $("#chatGroup").textContent = o.group.name;
  $("#askForm").q.placeholder = `Ask about ${o.group.name}'s money, ${me}`;
}

async function typeOut(el, text) {
  if (reduced) { el.textContent = text; return; }
  const words = text.split(" ");
  for (let i = 0; i < words.length; i++) { el.textContent = words.slice(0, i + 1).join(" "); await sleep(18); }
}

async function askQuestion(q, log = $("#askLog")) {
  q = q.trim(); if (q.length < 3) return;
  log.insertAdjacentHTML("beforeend", `<div class="q-bubble">${esc(q)}</div>`);
  log.insertAdjacentHTML("beforeend", `<div class="a-card"><span class="typing" aria-label="Looking it up"><i></i><i></i><i></i></span></div>`);
  const card = log.lastElementChild;
  card.scrollIntoView({ behavior: reduced ? "auto" : "smooth", block: "nearest" });
  try {
    const r = await post(`/api/groups/${state.groupId}/ask`, { question: q });
    card.innerHTML = `<div class="a-text"></div>`;
    await typeOut($(".a-text", card), r.answer);
    const u = r.understood_as, byId = Object.fromEntries(state.entries.map((e) => [e.id, e]));
    const how = [u.intent.replace(/_/g, " "), u.member && u.member !== "ME" ? u.member : u.member ? "you" : null, u.obligation].filter(Boolean).join(" - ");
    const src = r.sources.map((id) => byId[id]).filter(Boolean);
    card.insertAdjacentHTML("beforeend", `${src.length ? `<ul class="a-src"><li class="src-h">From these entries</li>${src.map((e, i) => `<li style="--i:${i}">${chip(e.status)} <span>${whoLine(e)}</span> <span class="meta">${fmtDate(e.occurred_on)}</span>${e.has_proof ? ` <a href="/api/groups/${state.groupId}/entries/${e.id}/proof" target="_blank" rel="noopener">Receipt</a>` : ""}</li>`).join("")}</ul>` : ""}
      <div class="a-meta">Understood as: ${esc(how)} <span>- ${esc(r.read_by)}</span></div>`);
  } catch (e) { card.innerHTML = `<div class="a-text">${esc(e.message)}</div>`; }
  card.scrollIntoView({ behavior: reduced ? "auto" : "smooth", block: "end" });
}
$("#askForm").addEventListener("submit", (ev) => { ev.preventDefault(); const v = ev.target.q.value; ev.target.q.value = ""; askQuestion(v); });
$("#chatForm").addEventListener("submit", (ev) => { ev.preventDefault(); const v = ev.target.q.value; ev.target.q.value = ""; askQuestion(v, $("#chatLog")); });
let chatPop = null;
function chatOpen() {
  closeAllPopovers();
  renderSuggestions();
  $("#chatPanel").hidden = false; $("#chatFab").setAttribute("aria-expanded", "true");
  chatPop = { root: $("#chatWrap"), close: chatClose }; popovers.add(chatPop);
  $("#chatForm").q.focus();
}
function chatClose() {
  $("#chatPanel").hidden = true; $("#chatFab").setAttribute("aria-expanded", "false");
  if (chatPop) { popovers.delete(chatPop); chatPop = null; }
}
$("#chatFab").addEventListener("click", () => ($("#chatPanel").hidden ? chatOpen() : chatClose()));
$("#chatClose").addEventListener("click", chatClose);
$("#chatPanel").addEventListener("keydown", (ev) => { if (ev.key === "Escape") { chatClose(); $("#chatFab").focus(); } });

function switchTab(tab) {
  state.tab = tab;
  $$("#tabs button").forEach((b) => b.classList.toggle("active", b.dataset.tab === tab));
  $$("[data-panel]").forEach((p) => p.classList.toggle("hidden", p.dataset.panel !== tab));
  if (tab === "activity") renderActivity();
  if (tab === "ask") { renderSuggestions(); $("#askForm").q.focus(); }
}

let rejectId = null;
document.addEventListener("click", async (ev) => {
  const t = ev.target.closest("button, [data-member], img[data-proof]") || ev.target;
  if (t.dataset.tab) switchTab(t.dataset.tab);
  else if (t.dataset.goto) { switchTab(t.dataset.goto); $("#tabs").scrollIntoView({ behavior: reduced ? "auto" : "smooth" }); }
  else if (t.dataset.lpage) {
    state.ledgerPage = +t.dataset.lpage; renderLedger();
    $("#ledgerSummary").scrollIntoView({ behavior: reduced ? "auto" : "smooth", block: "start" });
  }
  else if (t.dataset.epage) {
    state.eventsPage = +t.dataset.epage; await renderActivity(true);
    $("#btnVerify").scrollIntoView({ behavior: reduced ? "auto" : "smooth", block: "start" });
  }
  else if (t.dataset.f) {
    state.filter = t.dataset.f; state.ledgerPage = 1;
    $$("#ledgerFilters button").forEach((b) => b.classList.toggle("active", b === t));
    keepPlace(".ledger-tools", renderLedger);
  } else if (t.dataset.member) showRecord(t.dataset.member);
  else if (t.dataset.ask) askQuestion(t.dataset.ask, t.closest("#chatPanel") ? $("#chatLog") : $("#askLog"));
  else if (t.dataset.attn) { state.attnFilter = t.dataset.attn; keepPlace(".att-filters", renderAttention); $(`.att-filters [data-attn="${t.dataset.attn}"]`)?.focus({ preventScroll: true }); }
  else if (t.dataset.demoAs) { if ($("#dlgDemo").open) $("#dlgDemo").close(); await post("/api/view-as", { user_id: +t.dataset.demoAs }); await load(null, +t.dataset.demoGroup); }
  else if (t.dataset.openGroup) load(null, +t.dataset.openGroup);
  else if (t.dataset.demoPick) openDemoPicker(+t.dataset.demoPick);
  else if (t.dataset.verify) {
    const e = state.entries.find((x) => x.id === +t.dataset.verify);
    const flagged = e.status === "needs_review";
    const okGo = await confirmBox({
      title: flagged ? "Verify a flagged entry?" : "Verify this entry?",
      tone: flagged || e.status === "reported" ? "warn" : "ok",
      ok: "Yes, verify",
      body: sumList([["Who", e.direction === "in" ? e.member : `${e.created_by} to ${e.counterparty}`], ["Amount", e.amount],
        [e.direction === "in" ? "For" : "From", e.obligation], ["Date", fmtDate(e.occurred_on)], ["Receipt", e.has_proof ? "Attached" : "None"]]) +
        (flagged ? `<div class="cf-flag"><b>This entry was flagged:</b><ul>${e.reasons.map((r) => `<li>${esc(r)}</li>`).join("")}</ul></div>` : "") +
        `<p class="meta">Once verified it counts in the balance and is sealed into the group's history.</p>`,
    });
    if (!okGo) return;
    t.disabled = true;
    try { await decide(t.dataset.verify, "verify"); } catch (e) { alert(e.message); t.disabled = false; }
  } else if (t.dataset.reject) { rejectId = t.dataset.reject; $("#formReject").reset(); $("#dlgReject").showModal(); }
  else if (t.dataset.proof) window.open(t.src, "_blank", "noopener");
});
document.addEventListener("keydown", (ev) => {
  if (ev.key === "Enter" && ev.target.dataset?.member) showRecord(ev.target.dataset.member);
});

$("#btnPaid").addEventListener("click", () => openForm($("#dlgPaid")));
$("#btnOut").addEventListener("click", () => openForm($("#dlgOut")));
$("#btnOut2").addEventListener("click", () => openForm($("#dlgOut")));
$("#ledgerSearch").addEventListener("input", (ev) => { state.ledgerQ = ev.target.value.trim(); state.ledgerPage = 1; keepPlace(".ledger-tools", renderLedger); });
$("#formPaid").addEventListener("submit", (e) => submitEntry(e, $("#dlgPaid"), `/api/groups/${state.groupId}/entries/in`));
$("#formOut").addEventListener("submit", (e) => submitEntry(e, $("#dlgOut"), `/api/groups/${state.groupId}/entries/out`));
$("#formReject").addEventListener("submit", async (ev) => {
  if (ev.submitter?.value === "cancel") return;
  ev.preventDefault();
  const note = ev.target.note.value;
  $("#dlgReject").close();
  try { await decide(rejectId, "reject", note); } catch (e) { alert(e.message); }
});
$("#btnVerify").addEventListener("click", async () => {
  const r = await api(`/api/groups/${state.groupId}/verify`);
  const list = $("#events");
  list.classList.remove("sealing", "broken"); void list.offsetWidth;
  list.classList.add(r.intact ? "sealing" : "broken");
  const n = Math.min($$("li", list).length, 60);
  await sleep(n * 35 + 350);
  $("#verifyResult").innerHTML = r.intact
    ? `<span class="chip s-verified">Intact - ${r.events} actions sealed, none altered</span>`
    : `<span class="chip s-rejected">Tampering detected at action #${esc(r.broken_at_event)}</span>`;
});

// ---------- sign up, new group, contributions, invites ----------
let afterSignup = null;
function openSignup(next) {
  afterSignup = next;
  $("#formSignup").reset(); $("#dlgSignup .result").innerHTML = "";
  $("#dlgSignup").showModal();
}
$("#formSignup").addEventListener("submit", async (ev) => {
  if (ev.submitter?.value === "cancel") return;
  ev.preventDefault();
  try {
    await post("/api/signup", { name: ev.target.name.value });
    $("#dlgSignup").close();
    await load();
    if (afterSignup) afterSignup();
  } catch (e) { $("#dlgSignup .result").innerHTML = `<div class="box err">${esc(e.message)}</div>`; }
});

const ng = { mode: "fresh", members: [], token: null, preview: null };
const ROLE_OPTS = [{ value: "treasurer", label: "Treasurer", sub: "Records money in and out", group: "Your role" },
                   { value: "president", label: "President", sub: "Confirms the treasurer's entries", group: "Your role" }];
const FREQ_OPTS = [{ value: "weekly", label: "Weekly", sub: "Every 7 days", group: "How often" },
                   { value: "monthly", label: "Monthly", sub: "Same date each month", group: "How often" }];
const other = (r) => (r === "treasurer" ? "President" : "Treasurer");
const plusDays = (n) => { const d = dateOf(state.overview?.today || isoOf(new Date())); d.setDate(d.getDate() + n); return isoOf(d); };

function ngLeaderSelect() {
  const role = $("[name=my_role]", $("#formNewGroup")).value || "treasurer";
  $("#lblLeader").textContent = `${other(role)} - confirms your entries`;
  const opts = ng.members.map((m) => ({ value: m, label: m, sub: `Will be the ${other(role).toLowerCase()}`, group: "Your members" }));
  const root = $("[data-name=second_leader]", $("#formNewGroup"));
  if (!opts.length) { root.innerHTML = `<div class="hint" style="margin:0">Add at least one member first.</div>`; return; }
  const cur = $("input", root)?.value;
  makeSelect(root, opts, opts.some((o) => o.value === cur) ? cur : opts[0].value);
}
function ngRenderChips() {
  $("#memberChips").innerHTML = ng.members.map((m, i) => `<span class="mchip">${esc(m)}<button type="button" data-rm="${i}" aria-label="Remove ${esc(m)}">&times;</button></span>`).join("");
  ngLeaderSelect();
}
function ngAddMember() {
  const inp = $("#memberInput"), name = inp.value.trim().replace(/\s+/g, " ");
  if (name.length < 2) return;
  if (ng.members.some((m) => m.toLowerCase() === name.toLowerCase())) { inp.select(); return; }
  ng.members.push(name); inp.value = ""; inp.focus(); ngRenderChips();
}
function ngMode(mode) {
  ng.mode = mode;
  $$("#formNewGroup .seg button").forEach((b) => { b.classList.toggle("on", b.dataset.mode === mode); b.setAttribute("aria-selected", b.dataset.mode === mode); });
  $$("#formNewGroup [data-pane]").forEach((p) => p.classList.toggle("hidden", p.dataset.pane !== mode));
  $("#ngSubmit").textContent = mode === "fresh" ? "Create group" : ng.token ? "Create group and read the chat" : "Upload the chat first";
  $("#ngSubmit").disabled = mode === "import" && !ng.token;
  $("#dlgNewGroup .result").innerHTML = "";
}
function openNewGroup(mode = "fresh") {
  if (!state.me) return openSignup(() => openNewGroup(mode));
  closeAllPopovers();
  const f = $("#formNewGroup"); f.reset();
  Object.assign(ng, { members: [], token: null, preview: null });
  makeSelect($("[data-name=my_role]", f), ROLE_OPTS, "treasurer", ngLeaderSelect);
  makeSelect($("[data-name=c_frequency]", f), FREQ_OPTS, "weekly");
  makeDate($("[data-name=c_first_due]", f), plusDays(6), null);
  makeDate($("[data-name=g_due]", f), plusDays(60), null);
  $("#goalBox").classList.add("hidden");
  $$(".import-step", f).forEach((st) => st.classList.toggle("hidden", st.dataset.step !== "1"));
  $(".drop[data-kind=chat]", f)._reset?.();
  ngRenderChips(); ngMode(mode);
  $("#dlgNewGroup").showModal();
}
$("#formNewGroup").addEventListener("click", (ev) => {
  const t = ev.target.closest("button"); if (!t) return;
  if (t.dataset.mode) ngMode(t.dataset.mode);
  else if (t.id === "btnAddMember") ngAddMember();
  else if (t.dataset.rm !== undefined) { ng.members.splice(+t.dataset.rm, 1); ngRenderChips(); }
});
$("#memberInput").addEventListener("keydown", (ev) => { if (ev.key === "Enter") { ev.preventDefault(); ngAddMember(); } });
$("#goalToggle").addEventListener("change", (ev) => $("#goalBox").classList.toggle("hidden", !ev.target.checked));

$(".drop[data-kind=chat]").addEventListener("filechosen", async (ev) => {
  const out = $("#dlgNewGroup .result");
  out.innerHTML = `<div class="scanning">Opening the chat<span class="dots"></span></div>`;
  const fd = new FormData(); fd.append("chat_file", ev.detail);
  try {
    const p = await api("/api/import/whatsapp/preview", { method: "POST", body: fd });
    ng.token = p.token; ng.preview = p; out.innerHTML = "";
    const f = $("#formNewGroup"), names = p.participants.map((x) => x.name);
    $("#importSummary").innerHTML = `<b>${p.messages} messages from ${names.length} people</b>, ${fmtDate(p.first_date)} to ${fmtDate(p.last_date)}.
      ${p.flagged ? `<div class="meta" style="margin-top:4px">${p.flagged} message${p.flagged > 1 ? "s look" : " looks"} like an instruction to the AI and will be ignored.</div>` : ""}`;
    f.i_name.value = "";
    const people = p.participants.map((x) => ({ value: x.name, label: x.name, sub: `${x.messages} messages`, group: "People in the chat" }));
    makeSelect($("[data-name=i_me]", f), [...people, { value: "", label: "I'm not in this chat", sub: "Add me as a separate person", group: "Other" }], people[0].value, iLeader);
    makeSelect($("[data-name=i_role]", f), ROLE_OPTS, "treasurer", iLeader);
    makeSelect($("[data-name=i_frequency]", f), FREQ_OPTS, "weekly");
    iLeader();
    $$(".import-step", f).forEach((st) => st.classList.toggle("hidden", st.dataset.step !== "2"));
    ngMode("import");
    f.i_name.focus();
  } catch (e) { out.innerHTML = `<div class="box err">${esc(e.message)}</div>`; $(".drop[data-kind=chat]")._reset?.(); }
});
function iLeader() {
  const f = $("#formNewGroup");
  const me = $("input", $("[data-name=i_me]", f))?.value, role = $("input", $("[data-name=i_role]", f))?.value || "treasurer";
  $("#lblILeader").textContent = `${other(role)} - confirms your entries`;
  const opts = ng.preview.participants.filter((x) => x.name !== me).map((x) => ({ value: x.name, label: x.name, sub: `Will be the ${other(role).toLowerCase()}`, group: "People in the chat" }));
  const root = $("[data-name=i_leader]", f), cur = $("input", root)?.value;
  makeSelect(root, opts, opts.some((o) => o.value === cur) ? cur : opts[0]?.value);
}

$("#formNewGroup").addEventListener("submit", async (ev) => {
  if (ev.submitter?.value === "cancel") return;
  ev.preventDefault();
  const f = ev.target, out = $("#dlgNewGroup .result"), btn = $("#ngSubmit");
  const val = (n) => $(`[name="${n}"]`, f)?.value;
  const okGo = await confirmBox(ng.mode === "fresh"
    ? { title: "Create this group?", ok: "Yes, create it",
        body: sumList([["Group", f.name.value], ["You are", val("my_role") === "president" ? "President" : "Treasurer"],
          ["Members", ng.members.join(", ")], ["Confirms your entries", val("second_leader")],
          ["Contribution", f.c_amount.value ? `₦${f.c_amount.value}, ${val("c_frequency")}, ${f.c_periods.value} times` : "None yet"]]) }
    : { title: "Create the group from this chat?", ok: "Yes, read the chat",
        body: sumList([["Group", f.i_name.value], ["Messages", String(ng.preview?.messages || "")], ["People", String(ng.preview?.participants.length || "")],
          ["Contribution", `₦${f.i_amount.value}, ${val("i_frequency")}`]]) +
          `<p class="meta">AI will look for payments in the messages. Nothing is verified automatically.</p>` });
  if (!okGo) return;
  btn.disabled = true;
  try {
    let gid;
    if (ng.mode === "fresh") {
      if (!f.name.value.trim()) throw new Error("Give your group a name.");
      if (!ng.members.length) throw new Error("Add at least one member, so someone else can confirm your entries.");
      const body = { name: f.name.value, my_role: val("my_role"), members: ng.members, second_leader: val("second_leader"),
        contribution: f.c_amount.value.trim() ? { amount: f.c_amount.value, frequency: val("c_frequency"), first_due: val("c_first_due"), periods: +f.c_periods.value || 12 } : null,
        goal: $("#goalToggle").checked ? { title: f.g_title.value, amount: f.g_amount.value, due_date: val("g_due") } : null };
      gid = (await post("/api/groups", body)).group_id;
      $("#dlgNewGroup").close();
    } else {
      if (!f.i_name.value.trim()) throw new Error("Give your group a name.");
      out.innerHTML = `<div class="chatscan" aria-hidden="true"><div class="feed">${Array.from({ length: 16 }, (_, i) => `<span class="b${i % 3 === 1 ? " me" : ""}${i % 4 === 2 ? " pay" : ""}"></span>`).join("")}</div><i></i></div>
        <div class="scanning">AI is reading ${ng.preview.messages} messages for payments<span class="dots"></span></div>`;
      const r = await post("/api/import/whatsapp/create", { token: ng.token, group_name: f.i_name.value, me: val("i_me") || null,
        my_role: val("i_role"), second_leader: val("i_leader"), amount: f.i_amount.value, frequency: val("i_frequency") });
      gid = r.group_id; ng.token = null;
      out.innerHTML = `<div class="box ok"><b>Group created from the chat.</b>
        <div class="sumgrid">${[[r.participants, "members added"], [r.payments_found, "payments found"], [r.needs_review, "need review"],
          [r.reported, "claims to confirm"], [r.flagged.length, "hidden instructions ignored"], [r.dropped.length, "AI claims rejected"]]
          .map(([n, l], i) => `<div style="--i:${i}"><b>${n}</b><small>${l}</small></div>`).join("")}</div>
        <div class="meta">Read by ${esc(r.read_by)}. Nothing is verified yet: each payment needs a second person to confirm it, or a receipt.</div></div>`;
      $$("menu button", f).forEach((b) => b.classList.add("hidden"));
      out.insertAdjacentHTML("beforeend", `<menu><button type="button" class="primary" id="ngOpen">Open the group</button></menu>`);
      $("#ngOpen").onclick = () => { $("#dlgNewGroup").close(); $$("menu button", f).forEach((b) => b.classList.remove("hidden")); switchTab("attention"); };
    }
    await load(null, gid);
    if (ng.mode === "fresh") switchTab("overview");
  } catch (e) { out.innerHTML = `<div class="box err">${esc(e.message)}</div>`; }
  finally { btn.disabled = ng.mode === "import" && !ng.token; }
});

let obKind = "recurring";
function openAddOb() {
  const f = $("#formAddOb"); f.reset(); closeAllPopovers(); $("#dlgAddOb .result").innerHTML = "";
  makeSelect($("[data-name=r_frequency]", f), FREQ_OPTS, "monthly");
  makeDate($("[data-name=r_first_due]", f), plusDays(30), null);
  makeDate($("[data-name=a_due]", f), plusDays(30), null);
  obSet("recurring");
  $("#dlgAddOb").showModal();
}
function obSet(kind) {
  obKind = kind;
  $$("#formAddOb .seg button").forEach((b) => { b.classList.toggle("on", b.dataset.kind === kind); b.setAttribute("aria-selected", b.dataset.kind === kind); });
  $$("#formAddOb [data-kpane]").forEach((p) => p.classList.toggle("hidden", p.dataset.kpane !== kind));
}
$("#formAddOb .seg").addEventListener("click", (ev) => { const b = ev.target.closest("button"); if (b) obSet(b.dataset.kind); });
$("#formAddOb").addEventListener("submit", async (ev) => {
  if (ev.submitter?.value === "cancel") return;
  ev.preventDefault();
  const f = ev.target, val = (n) => $(`[name="${n}"]`, f).value;
  const okGo = await confirmBox({
    title: "Add this contribution?", ok: "Yes, add it",
    body: obKind === "goal"
      ? sumList([["Goal", f.a_title.value], ["Per member", `₦${f.a_amount.value}`], ["Due", $("[data-name=a_due] .cs-btn b", f).textContent]])
      : sumList([["Name", f.series_name.value], ["Per member", `₦${f.r_amount.value}`], ["How often", $("[data-name=r_frequency] .cs-btn b", f).textContent],
                 ["First due", $("[data-name=r_first_due] .cs-btn b", f).textContent], ["Times", f.r_periods.value]]) +
      `<p class="meta">Every member will see it, and it is recorded in the group's history.</p>`,
  });
  if (!okGo) return;
  const body = obKind === "goal"
    ? { kind: "goal", goal: { title: f.a_title.value, amount: f.a_amount.value, due_date: val("a_due") } }
    : { kind: "recurring", series_name: f.series_name.value, contribution: { amount: f.r_amount.value, frequency: val("r_frequency"), first_due: val("r_first_due"), periods: +f.r_periods.value || 1 } };
  try {
    await post(`/api/groups/${state.groupId}/obligations`, body);
    $("#dlgAddOb").close(); state.intro = true; await refresh(); setTimeout(() => (state.intro = false), 50); switchTab("overview");
  } catch (e) { $("#dlgAddOb .result").innerHTML = `<div class="box err">${esc(e.message)}</div>`; }
});

async function openInvite() {
  const { code } = await api(`/api/groups/${state.groupId}/invite`);
  $("#inviteLink").textContent = `${location.origin}/?join=${code}`;
  $("#btnCopy").textContent = "Copy link";
  $("#dlgInvite").showModal();
}
$("#btnCopy").addEventListener("click", async () => {
  try { await navigator.clipboard.writeText($("#inviteLink").textContent); $("#btnCopy").textContent = "Copied"; }
  catch { getSelection().selectAllChildren($("#inviteLink")); $("#btnCopy").textContent = "Press Ctrl+C"; }
});

let joinCode = null;
async function openJoin(code) {
  joinCode = code;
  const f = $("#formJoin"); f.reset(); $("#dlgJoin .result").innerHTML = "";
  try {
    const info = await api(`/api/join/${encodeURIComponent(code)}`);
    $("#joinTitle").textContent = `Join ${info.group}`;
    $("#joinHint").textContent = state.me ? `You'll join as ${state.me.user.name}. The group has ${info.members} members.`
      : `The group has ${info.members} members. Enter your name to sign up and join. No password needed in this demo.`;
    $("#joinNameRow").classList.toggle("hidden", !!state.me);
    $("#joinBtn").disabled = false;
  } catch (e) {
    $("#joinTitle").textContent = "Invite link not valid";
    $("#joinHint").textContent = "Ask the treasurer or president for a new link.";
    $("#joinNameRow").classList.add("hidden"); $("#joinBtn").disabled = true;
  }
  $("#dlgJoin").showModal();
}
$("#formJoin").addEventListener("submit", async (ev) => {
  if (ev.submitter?.value === "cancel") { history.replaceState(null, "", "/"); return; }
  ev.preventDefault();
  try {
    if (!state.me) await post("/api/signup", { name: ev.target.name.value });
    const { group_id } = await post(`/api/join/${encodeURIComponent(joinCode)}`, {});
    $("#dlgJoin").close(); history.replaceState(null, "", "/");
    await load(null, group_id);
  } catch (e) { $("#dlgJoin .result").innerHTML = `<div class="box err">${esc(e.message)}</div>`; }
});

$("#btnNewGroup").addEventListener("click", () => openNewGroup("fresh"));
async function goHome() {
  closeAllPopovers();
  if (state.me) state.me = await api("/api/me").catch(() => null);
  showLanding();
  scrollTo({ top: 0, behavior: reduced ? "auto" : "smooth" });
}
$("#homeLink").addEventListener("click", goHome);
$("#btnBack").addEventListener("click", goHome);
$("#btnSignOut").addEventListener("click", async () => {
  if (!await confirmBox({ title: "Sign out?", tone: "danger", ok: "Sign out", body: `<p>You can come back any time by picking a person or signing up again.</p>` })) return;
  await post("/api/signout", {});
  state.me = null; state.groupId = null; va.people = await api("/api/people");
  showLanding();
});
$("#btnSignupStart").addEventListener("click", () => (state.me ? openNewGroup("fresh") : openSignup(() => openNewGroup("fresh"))));
$("#btnSignupEnd").addEventListener("click", () => $("#btnSignupStart").click());
async function openDemoPicker(onlyGroup) {
  va.people = await api("/api/people");
  const groups = new Map();
  for (const p of va.people) for (const m of p.memberships) {
    if (!groups.has(m.group_id)) groups.set(m.group_id, { id: m.group_id, name: m.group_name, people: [] });
    groups.get(m.group_id).people.push({ id: p.id, name: p.name, role: m.role });
  }
  const order = { president: 0, treasurer: 1, member: 2 };
  $("#demoList").innerHTML = [...groups.values()].filter((g) => !onlyGroup || g.id === onlyGroup).sort((a, b) => a.id - b.id).map((g, i) => {
    const ppl = g.people.sort((a, b) => order[a.role] - order[b.role] || a.name.localeCompare(b.name));
    const treasurer = ppl.find((p) => p.role === "treasurer") || ppl[0];
    return `<div class="demo-g rise" style="--i:${i}">
      <div class="demo-h"><div><h4>${esc(g.name)}</h4><div class="meta">${ppl.length} members</div></div>
        <button type="button" class="primary sm" data-demo-as="${treasurer.id}" data-demo-group="${g.id}">Open as ${esc(treasurer.name.split(" ")[0])}, ${ROLE[treasurer.role].toLowerCase()}</button></div>
      <div class="demo-people">${ppl.map((p) => `<button type="button" class="pchip" data-demo-as="${p.id}" data-demo-group="${g.id}"><span class="avatar sm r-${p.role}">${esc(initials(p.name))}</span><span>${esc(p.name)}<small>${ROLE[p.role]}</small></span></button>`).join("")}</div>
    </div>`;
  }).join("");
  $("#dlgDemo").showModal();
}
$("#btnAddOb").addEventListener("click", openAddOb);
$("#btnInvite").addEventListener("click", openInvite);

$$(".drop").forEach(setupDrop);
for (const dlg of $$("dialog")) {
  let downOnBackdrop = false;  // only close if the press both started and ended on the backdrop
  dlg.addEventListener("pointerdown", (e) => { downOnBackdrop = e.target === dlg; });
  dlg.addEventListener("click", (e) => { if (e.target === dlg && downOnBackdrop) { closeAllPopovers(); dlg.close(); } });
  dlg.addEventListener("cancel", (e) => { if (popovers.size) { e.preventDefault(); closeAllPopovers(); } });
}

init();
