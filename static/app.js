/* MFA DealPick - single-page interface (no framework). All user text is inserted with
   textContent via h(); the only innerHTML use is for fixed, built-in SVG artwork. */
(function () {
  "use strict";

  const app = document.getElementById("app");
  let ME = null, AI = false, navId = 0, STAMP = 0, TYPES = null;

  const STAGES = ["Booked", "Agreement signed", "Delivered", "RC transferred"];
  const STATUS = {
    draft: ["Draft", "gold"], pending_review: ["With advocate", ""], changes_requested: ["Changes asked", "petal"],
    approved: ["Approved", "sea"], sent: ["Sent", "line"],
  };
  const EVENT_LABEL = {
    created: "Drafted", edited: "Edited", advocate_edited: "Advocate edited", submitted: "Sent to advocate",
    approved: "Approved", changes_requested: "Changes requested", sent: "Marked as sent",
    ai_polish: "AI tidied the wording", undo_ai: "AI tidy-up undone",
  };

  /* ---------------------------------------------------------------- helpers */

  function h(tag, attrs, ...kids) {
    const el = document.createElement(tag);
    Object.keys(attrs || {}).forEach((k) => {
      const v = attrs[k];
      if (v === null || v === undefined || v === false) return;
      if (k.slice(0, 2) === "on") el.addEventListener(k.slice(2), v);
      else if (k === "style") Object.keys(v).forEach((s) => (s.indexOf("--") === 0 ? el.style.setProperty(s, v[s]) : (el.style[s] = v[s])));
      else if (k === "value") el.value = v;
      else el.setAttribute(k, v === true ? "" : v);
    });
    (function add(list) {
      list.forEach((c) => {
        if (c === null || c === undefined || c === false) return;
        if (Array.isArray(c)) return add(c);
        el.append(c.nodeType ? c : document.createTextNode(String(c)));
      });
    })(kids);
    return el;
  }

  function svgFrom(markup) {
    const t = document.createElement("template");
    t.innerHTML = markup.trim();
    return t.content.firstChild;
  }

  async function api(path, method, body) {
    const opt = { method: method || "GET", headers: { "X-Requested-With": "DealPick" }, credentials: "same-origin" };
    if (body !== undefined) {
      opt.headers["Content-Type"] = "application/json";
      opt.body = JSON.stringify(body);
    }
    let res;
    try { res = await fetch("/api" + path, opt); }
    catch (e) { throw new Error("Can't reach the server. Check your connection and try again."); }
    let data = null;
    try { data = await res.json(); } catch (e) { /* non-JSON error page */ }
    if (res.status === 401 && ME) { ME = null; renderAuth(); throw new Error("Please log in again."); }
    if (!res.ok || !data || data.success === false) throw new Error((data && data.message) || "Something went wrong. Try again.");
    return data;
  }

  function toast(msg, bad) {
    const t = h("div", { class: "toast" + (bad ? " bad" : "") }, msg);
    document.getElementById("toasts").append(t);
    setTimeout(() => t.remove(), bad ? 6500 : 3800);
  }

  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const inr = (n) => Number(n || 0).toLocaleString("en-IN", { maximumFractionDigits: 0 });
  const today = () => new Date(Date.now() - new Date().getTimezoneOffset() * 60000).toISOString().slice(0, 10);
  const asDate = (s) => new Date(/^\d{4}-\d{2}-\d{2}$/.test(s) ? s + "T00:00:00" : s);
  const fmtDate = (s) => (s ? asDate(s).toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" }) : "");
  const fmtDT = (s) => (s ? new Date(s).toLocaleString("en-IN", { day: "numeric", month: "short", hour: "numeric", minute: "2-digit" }) : "");
  const plural = (n, one, many) => n + " " + (n === 1 ? one : many || one + "s");
  const first = (s) => String(s || "").trim().split(/\s+/)[0] || "there";

  function modal(content, wide) {
    const back = h("div", { class: "modal-back", onclick: (e) => { if (e.target === back) close(); } });
    const box = h("div", { class: "modal" + (wide ? " wide" : ""), role: "dialog", "aria-modal": "true" }, content);
    back.append(box);
    document.body.append(back);
    function esc(e) { if (e.key === "Escape") close(); }
    function close() { back.remove(); document.removeEventListener("keydown", esc); }
    document.addEventListener("keydown", esc);
    const f = box.querySelector("input,select,textarea,button");
    if (f) f.focus();
    return { close, box };
  }

  async function busy(btn, fn) {
    const label = btn.textContent;
    btn.disabled = true;
    try { return await fn(); }
    catch (e) { toast(e.message, true); }
    finally { btn.disabled = false; btn.textContent = label; }
  }

  /* ---------------------------------------------------------------- artwork (fixed markup only) */

  const logo = () => svgFrom(`<svg viewBox="0 0 40 40" aria-hidden="true"><path d="M6 34V20C6 11 12 5 20 5s14 6 14 15v14" fill="none" stroke="#0E4D57" stroke-width="3.2" stroke-linecap="round"/><path class="beat" d="M20 28c-5-3.4-7.5-6-7.5-9a4.2 4.2 0 0 1 7.5-2.2A4.2 4.2 0 0 1 27.5 19c0 3-2.5 5.6-7.5 9z" fill="#F4B63F"/></svg>`);

  const carIcon = () => svgFrom(`<svg class="car" viewBox="0 0 64 30" aria-hidden="true"><path d="M3 24V17q0-4 5-5l11-2 8-7q2-2 5-2h15q3 0 5 3l7 6 6 2q3 1 3 5v7z" fill="#0E4D57"/><path d="M24 9l-5 6h12V9zm11 0v6h16l-5-6z" fill="#D6EFE6"/><circle cx="17" cy="24" r="5" fill="#0B2E35"/><circle cx="17" cy="24" r="2" fill="#F4B63F"/><circle cx="49" cy="24" r="5" fill="#0B2E35"/><circle cx="49" cy="24" r="2" fill="#F4B63F"/></svg>`);

  function heroArt() {
    const dots = [40, 75, 110, 145, 180, 215, 250, 285, 320].map((x, i) => `<circle cx="${x}" cy="219" r="4.5" style="animation-delay:${3.4 + i * 0.12}s,${5 + i * 0.3}s"/>`).join("");
    return svgFrom(`<svg class="hero-art" viewBox="0 0 360 232" role="img" aria-label="A car sheltered under a protective arch">
      <path class="draw arch" pathLength="1" d="M22 200C22 52 100 14 180 14s158 38 158 186"/>
      <path class="heart-top" d="M180 40c-9-6-14-11-14-17a7.6 7.6 0 0 1 14-4 7.6 7.6 0 0 1 14 4c0 6-5 11-14 17z"/>
      <path class="draw" pathLength="1" d="M30 199H330"/>
      <g class="car-bob"><g transform="translate(40 80)">
        <path class="draw" pathLength="1" d="M8 100V82Q8 70 22 68L66 60L96 30Q101 25 109 25H188Q197 25 203 31L232 60L262 66Q274 69 274 82V100Z"/>
        <path class="draw glass" pathLength="1" d="M103 33L78 58H142V33ZM152 33V58H222L196 33Z"/>
        <path class="draw glass" pathLength="1" d="M147 60V96"/>
        <circle cx="266" cy="80" r="4" fill="#F4B63F"/><circle cx="15" cy="82" r="3.5" fill="#B4325A"/>
        <circle class="draw wheel" pathLength="1" cx="62" cy="100" r="17" fill="none"/><circle cx="62" cy="100" r="7" fill="#F4B63F"/>
        <circle class="draw wheel" pathLength="1" cx="222" cy="100" r="17" fill="none"/><circle cx="222" cy="100" r="7" fill="#F4B63F"/>
      </g></g>
      <g class="pulli">${dots}</g></svg>`);
  }

  function sealArt(name, enrol, date, animate) {
    const s = svgFrom(`<svg class="seal${animate ? " stamp" : ""}" viewBox="0 0 150 150" role="img" aria-label="Approved by advocate">
      <circle cx="75" cy="75" r="70" fill="#FFF7DF" stroke="#2A8C82" stroke-width="4"/>
      <circle cx="75" cy="75" r="60" fill="none" stroke="#F4B63F" stroke-width="2.5" stroke-dasharray="3 5"/>
      <path d="M75 46c-6-4-9.4-7.4-9.4-11.4a5.1 5.1 0 0 1 9.4-2.7 5.1 5.1 0 0 1 9.4 2.7c0 4-3.4 7.4-9.4 11.4z" fill="#F4B63F"/>
      <text x="75" y="76" text-anchor="middle" font-family="Bricolage Grotesque, sans-serif" font-size="22" font-weight="800" fill="#0E4D57">Approved</text>
      <path d="M42 84H108" stroke="#2A8C82" stroke-width="2"/>
      <text class="nm" x="75" y="100" text-anchor="middle" font-family="Figtree, sans-serif" font-size="11" font-weight="700" fill="#0B2E35"></text>
      <text class="en" x="75" y="113" text-anchor="middle" font-family="Figtree, sans-serif" font-size="9.5" fill="#48666C"></text>
      <text class="dt" x="75" y="126" text-anchor="middle" font-family="Figtree, sans-serif" font-size="9.5" fill="#48666C"></text></svg>`);
    s.querySelector(".nm").textContent = ("Adv. " + name).slice(0, 26);
    s.querySelector(".en").textContent = enrol ? "Enrol. " + enrol : "";
    s.querySelector(".dt").textContent = fmtDate(date);
    return s;
  }

  function road(stage, opts) {
    opts = opts || {};
    const el = h("div", { class: "road" + (opts.big ? " big" : ""), style: { "--i": 0 } }, h("div", { class: "fill" }));
    STAGES.forEach((s, n) => {
      const on = n <= stage ? " on" : "";
      el.append(opts.onPick
        ? h("button", { type: "button", class: "stop" + on, style: { "--n": n }, title: s, "aria-label": "Mark as " + s, onclick: () => opts.onPick(n) })
        : h("span", { class: "stop" + on, style: { "--n": n } }));
    });
    el.append(carIcon());
    setTimeout(() => el.style.setProperty("--i", stage), 80);          // the car drives to its stage
    return el;
  }

  /* ---------------------------------------------------------------- document preview */

  function inline(text) {
    return text.split(/(\*\*[^*]+\*\*)/).filter(Boolean).map((p) => (/^\*\*[^*]+\*\*$/.test(p) ? h("strong", null, p.slice(2, -2)) : p.replace(/\*\*/g, "")));
  }

  function renderDoc(text) {
    const root = h("div", { class: "paper" });
    const lines = String(text || "").split("\n");
    let i = 0;
    while (i < lines.length) {
      const s = lines[i].trim();
      i++;
      if (!s) continue;
      if (s === "~~") { root.append(h("hr", { class: "pb" })); continue; }
      if (s.startsWith("|")) {
        const bordered = !s.startsWith("|~"), rows = [];
        i--;
        while (i < lines.length && lines[i].trim().startsWith("|")) {
          let c = lines[i].trim();
          c = c.startsWith("|~") ? c.slice(2) : c.slice(1);
          rows.push(c.split("|").map((x) => x.trim().replace(/^~/, "")));
          i++;
        }
        root.append(h("table", { class: bordered ? "box" : "free" }, h("tbody", null, rows.map((r) => h("tr", null, r.map((c) => h("td", null, inline(c))))))));
        continue;
      }
      let m;
      if (s.startsWith("### ")) root.append(h("p", { class: "t3" }, inline(s.slice(4))));
      else if (s.startsWith("## ")) root.append(h("p", { class: "t2" }, inline(s.slice(3))));
      else if (s.startsWith("# ")) root.append(h("p", { class: "t1" }, inline(s.slice(2))));
      else if (s.startsWith(">>")) root.append(h("p", { class: "r" }, s.slice(2).trim() ? inline(s.slice(2).trim()) : "\u00a0"));
      else if ((m = s.match(/^(\d{1,3})[.)]\s+(.*)$/))) root.append(h("p", { class: "num" }, m[1] + ".\u00a0\u00a0", inline(m[2])));
      else if (/^\(([a-zA-Z]{1,3}|\d{1,2})\)\s/.test(s)) root.append(h("p", { class: "sub" }, inline(s)));
      else root.append(h("p", null, inline(s)));
    }
    return root;
  }

  function openDoc(title, text, downloadUrl) {
    const m = modal(h("div", null,
      h("div", { class: "row", style: { marginBottom: "14px" } }, h("h2", null, title), h("span", { class: "spacer" }),
        downloadUrl ? h("a", { class: "btn gold small", href: downloadUrl }, "Download Word file") : null,
        h("button", { class: "btn line small", type: "button", onclick: () => m.close() }, "Close")),
      renderDoc(text)), true);
  }

  /* ---------------------------------------------------------------- form fields */

  function field(f, val) {
    const t = f.t || "text";
    let input;
    if (t === "select") {
      input = h("select", { name: f.k }, (f.o || []).map((o) => { const a = Array.isArray(o) ? o : [o, o]; return h("option", { value: a[0] }, a[1]); }));
    } else if (t === "textarea") {
      input = h("textarea", { name: f.k, rows: f.rows || 3 });
    } else {
      input = h("input", { name: f.k, type: t === "number" ? "text" : t, inputmode: t === "number" ? "decimal" : null, autocomplete: f.ac || "off" });
    }
    input.value = val !== undefined && val !== null && val !== "" ? val : (f.d !== undefined ? f.d : "");
    if (t === "select" && input.selectedIndex < 0 && input.options.length) input.selectedIndex = 0;
    return h("label", { class: "f" + (f.span ? " span2" : ""), "data-k": f.k }, f.l, input, f.hint ? h("span", { class: "hint" }, f.hint) : null);
  }

  function collect(root) {
    const o = {};
    root.querySelectorAll("[name]").forEach((el) => { o[el.name] = el.value; });
    return o;
  }

  /* ---------------------------------------------------------------- sign in */

  function renderAuth() {
    document.title = "MFA DealPick";
    let mode = "login";
    const err = h("div", { class: "error", role: "alert", hidden: true });
    const holder = h("div");
    const tabsEl = h("div", { class: "tabs", role: "tablist" });
    const STATES = [["TN", "Tamil Nadu"], ["KL", "Kerala"]];
    const SPECS = {
      login: [{ k: "email", l: "Email", t: "email", ac: "email" }, { k: "password", l: "Password", t: "password", ac: "current-password" }],
      dealer: [
        { k: "name", l: "Your name", ac: "name" }, { k: "email", l: "Email", t: "email", ac: "email" },
        { k: "password", l: "Password", t: "password", ac: "new-password", hint: "At least 8 characters." },
        { k: "dealership_name", l: "Dealership name" }, { k: "address", l: "Dealership address", t: "textarea", rows: 2 },
        { k: "city", l: "City or town" }, { k: "state", l: "State", t: "select", o: STATES },
        { k: "phone", l: "Phone", ac: "tel" }, { k: "gstin", l: "GSTIN (optional)" }, { k: "trade_cert", l: "Trade certificate no. (optional)" }],
      advocate: [
        { k: "name", l: "Your name", ac: "name" }, { k: "email", l: "Email", t: "email", ac: "email" },
        { k: "password", l: "Password", t: "password", ac: "new-password", hint: "At least 8 characters." },
        { k: "bar_enrolment", l: "Bar Council enrolment no.", hint: "Printed on every notice you approve." },
        { k: "invite_code", l: "Invite code", hint: "Ask the person who runs this site." }, { k: "phone", l: "Phone (optional)", ac: "tel" }],
    };
    const TABS = [["login", "Log in"], ["dealer", "Dealership sign-up"], ["advocate", "Advocate sign-up"]];

    async function submit(e) {
      e.preventDefault();
      err.hidden = true;
      const btn = form.querySelector("button[type=submit]");
      btn.disabled = true;
      try {
        const body = collect(form);
        const r = await api(mode === "login" ? "/login" : "/register", "POST", mode === "login" ? body : Object.assign(body, { role: mode }));
        ME = r.user;
        const me = await api("/me");
        AI = me.ai;
        location.hash = ME.role === "advocate" ? "#/review" : "#/deals";
        route();
      } catch (ex) {
        err.textContent = ex.message;
        err.hidden = false;
        btn.disabled = false;
      }
    }

    const form = h("form", { onsubmit: submit, novalidate: true });
    function draw() {
      tabsEl.replaceChildren(...TABS.map(([k, l]) => h("button", { type: "button", role: "tab", "aria-selected": String(k === mode), onclick: () => { mode = k; err.hidden = true; draw(); } }, l)));
      form.replaceChildren(
        h("div", { class: "grid panel-in", style: { gridTemplateColumns: "repeat(auto-fit,minmax(200px,1fr))" } }, SPECS[mode].map((f) => Object.assign(field(f), {}))),
        err,
        h("div", { class: "row", style: { marginTop: "18px" } }, h("button", { class: "btn gold", type: "submit" }, mode === "login" ? "Log in" : "Create account")));
    }
    draw();
    holder.append(tabsEl, form);

    app.replaceChildren(h("div", { class: "auth" },
      h("div", null,
        h("a", { class: "logo", href: "#/", style: { marginBottom: "26px" } }, logo(), "MFA DealPick"),
        h("h1", null, "Every deal, looked after."),
        h("p", { class: "lead" }, "Record a used-car sale, get an agreement written for Tamil Nadu or Kerala, and send legal notices only once your advocate has approved them."),
        heroArt()),
      h("div", { class: "sheet auth-card" }, holder)));
  }

  /* ---------------------------------------------------------------- shell and router */

  function shell() {
    const dealer = ME.role === "dealer";
    const links = dealer
      ? [["#/deals", "Deals"], ["#/notices", "Notices"], ["#/profile", "Dealership"]]
      : [["#/review", "Review queue"], ["#/profile", "Account"]];
    app.replaceChildren(
      h("header", { class: "top" },
        h("a", { class: "logo", href: dealer ? "#/deals" : "#/review" }, logo(), "MFA DealPick"),
        h("nav", { class: "main", "aria-label": "Main" }, links.map(([href, l]) => h("a", { href }, l))),
        h("div", { class: "who" }, h("span", null, h("b", null, dealer ? ME.dealership_name : "Adv. " + ME.name)),
          h("button", { type: "button", onclick: logout }, "Log out"))),
      h("main", { id: "main" }));
  }

  async function logout() {
    try { await api("/logout", "POST", {}); } catch (e) { /* already logged out */ }
    ME = null;
    location.hash = "";
    renderAuth();
  }

  function setNav(hash) {
    document.querySelectorAll("nav.main a").forEach((a) => {
      const base = a.getAttribute("href");
      const on = hash === base || (base === "#/deals" && /^#\/deals/.test(hash)) || (base === "#/notices" && /^#\/notices/.test(hash)) ||
        (base === "#/review" && /^#\/(review|notices)/.test(hash) && ME.role === "advocate");
      if (on) a.setAttribute("aria-current", "page"); else a.removeAttribute("aria-current");
    });
  }

  const ROUTES = [
    [/^#\/deals\/new$/, () => viewDealForm(0)],
    [/^#\/deals\/(\d+)\/edit$/, (m) => viewDealForm(+m[1])],
    [/^#\/deals\/(\d+)$/, (m) => viewDeal(+m[1])],
    [/^#\/deals$/, () => viewDeals()],
    [/^#\/notices\/(\d+)$/, (m) => viewNotice(+m[1])],
    [/^#\/notices$/, () => viewNotices()],
    [/^#\/review$/, () => viewReview()],
    [/^#\/profile$/, () => viewProfile()],
  ];

  async function route() {
    const my = ++navId;
    document.title = "MFA DealPick";
    if (!ME) return renderAuth();
    if (!document.getElementById("main")) shell();
    const dealer = ME.role === "dealer";
    let hash = location.hash;
    if (!hash || hash === "#/" || hash === "#") hash = dealer ? "#/deals" : "#/review";
    setNav(hash);
    const main = document.getElementById("main");
    main.replaceChildren(h("p", { class: "muted", style: { padding: "30px 0" } }, h("span", { class: "spinner" }), "  Loading"));
    let view = null, m = null;
    for (const [re, fn] of ROUTES) { m = hash.match(re); if (m) { view = fn; break; } }
    try {
      const node = view ? await view(m) : h("div", { class: "sheet" }, h("h2", null, "We can't find that page"), h("p", null, "Use the menu above to get back on track."));
      if (my !== navId) return;
      node.classList.add("enter");
      main.replaceChildren(node);
      window.scrollTo(0, 0);
    } catch (e) {
      if (my !== navId) return;
      main.replaceChildren(h("div", { class: "sheet" }, h("h2", null, "That didn't load"), h("p", null, e.message),
        h("a", { class: "btn", href: dealer ? "#/deals" : "#/review" }, "Back to start")));
    }
  }

  /* ---------------------------------------------------------------- deals */

  const statusChip = (s) => h("span", { class: "chip " + STATUS[s][1] }, STATUS[s][0]);
  const stateChip = (s) => h("span", { class: "chip line" }, s === "KL" ? "Kerala" : "Tamil Nadu");

  async function viewDeals() {
    const { deals } = await api("/deals");
    const sum = (k) => deals.reduce((a, d) => a + d[k], 0);
    const onRoad = deals.filter((d) => d.stage < 3).length, pending = sum("pending"), approved = sum("approved"), changes = sum("changes");

    const line = [];
    if (!deals.length) line.push("No deals yet. Record your first one and we'll look after the paperwork.");
    else {
      line.push(`You have ${plural(onRoad, "deal")} on the road. `);
      const bits = [];
      if (pending) bits.push(h("span", null, plural(pending, "notice"), " ", pending === 1 ? "is" : "are", " with your advocate"));
      if (changes) bits.push(h("a", { href: "#/notices" }, plural(changes, "notice") + (changes === 1 ? " needs" : " need") + " your changes"));
      if (approved) bits.push(h("a", { href: "#/notices" }, plural(approved, "notice") + (approved === 1 ? " is" : " are") + " approved and ready to send"));
      bits.forEach((b, i) => { line.push(b); line.push(i === bits.length - 1 ? "." : i === bits.length - 2 ? ", and " : ", "); });
      if (!bits.length) line.push("Nothing is waiting on anyone.");
    }

    const list = deals.length
      ? h("div", { class: "sheet" }, deals.map((d) => h("a", { class: "deal", href: "#/deals/" + d.id },
        h("div", null, h("div", { class: "vtitle" }, d.vehicle), h("div", { class: "meta" }, d.buyer_name, d.reg_no ? ", " + d.reg_no : ""),
          h("div", { class: "row", style: { marginTop: "8px" } }, stateChip(d.state),
            d.pending ? h("span", { class: "chip" }, "With advocate") : null,
            d.changes ? h("span", { class: "chip petal" }, "Changes asked") : null,
            d.approved ? h("span", { class: "chip sea" }, "Ready to send") : null)),
        road(d.stage),
        h("div", { class: "money" }, "Rs. " + inr(d.price), h("small", null, STAGES[d.stage])))))
      : h("div", { class: "sheet empty" }, carIcon(), h("h3", null, "Your road is clear"),
        h("p", { class: "muted" }, "A deal holds the buyer, the car and the money. From it you get the agreement and any notices."),
        h("a", { class: "btn gold", href: "#/deals/new" }, "Record a deal"));

    return h("div", null,
      h("div", { class: "page-head" }, h("div", null, h("h1", null, "Hello, " + first(ME.name) + "."), h("p", { class: "care-line", style: { marginTop: "10px" } }, line)),
        h("span", { class: "spacer" }), deals.length ? h("a", { class: "btn gold", href: "#/deals/new" }, "Record a deal") : null),
      list);
  }

  const YN = [["no", "No"], ["yes", "Yes"]];
  const MODES = ["UPI", "Bank transfer", "Cheque", "Demand draft", "Cash"];
  const ST3 = [["TN", "Tamil Nadu"], ["KL", "Kerala"], ["OT", "Another state"]];
  const DEAL_STEPS = [
    { name: "Buyer", fields: [
      { k: "buyer_name", l: "Buyer's full name", req: 1, ac: "off" },
      { k: "buyer_rel", l: "Relation", t: "select", o: ["S/o", "D/o", "W/o", "C/o"] },
      { k: "buyer_rel_name", l: "Father's, mother's or spouse's name" },
      { k: "buyer_age", l: "Age", t: "number" },
      { k: "buyer_address", l: "Address", t: "textarea", span: 1, req: 1 },
      { k: "buyer_city", l: "City or town" },
      { k: "buyer_state", l: "Buyer lives in", t: "select", o: ST3 },
      { k: "buyer_phone", l: "Mobile number" },
      { k: "buyer_email", l: "Email", t: "email" },
      { k: "buyer_id_type", l: "ID shown", t: "select", o: ["Aadhaar", "Driving licence", "Voter ID", "Passport"] },
      { k: "buyer_id_no", l: "ID number", hint: "For Aadhaar, only the last 4 digits are kept." }] },
    { name: "Car", fields: [
      { k: "make", l: "Make", req: 1 }, { k: "model", l: "Model", req: 1 }, { k: "variant", l: "Variant" },
      { k: "year", l: "Year of manufacture", t: "number" },
      { k: "reg_no", l: "Registration number", req: 1 },
      { k: "reg_state", l: "Registered in", t: "select", o: ST3 },
      { k: "chassis", l: "Chassis number" }, { k: "engine_no", l: "Engine number" }, { k: "colour", l: "Colour" },
      { k: "fuel", l: "Fuel", t: "select", o: ["Petrol", "Diesel", "CNG", "Electric", "Hybrid"] },
      { k: "odometer", l: "Odometer (km)", t: "number" },
      { k: "owners", l: "Owner number", t: "select", o: [["1", "First owner"], ["2", "Second owner"], ["3", "Third owner"], ["4+", "Fourth or later"]] },
      { k: "rc_holder", l: "RC is in the name of", hint: "Leave blank if it's your dealership." },
      { k: "hypothecated", l: "Loan on the RC?", t: "select", o: YN },
      { k: "financier", l: "Lender on the RC", when: ["hypothecated", "yes"] },
      { k: "insurance_policy", l: "Insurance policy" }, { k: "insurance_valid", l: "Insurance valid until", t: "date" },
      { k: "accident_history", l: "Accident history", t: "select", o: [["none", "No major accident known"], ["minor", "Minor cosmetic repairs"], ["major", "Major repair after an accident"]] },
      { k: "known_defects", l: "Known defects you're telling the buyer about", t: "textarea", span: 1 }] },
    { name: "Money", fields: [
      { k: "price", l: "Sale price (Rs.)", t: "number", req: 1 },
      { k: "advance", l: "Advance received (Rs.)", t: "number" },
      { k: "advance_date", l: "Advance received on", t: "date" }, { k: "advance_mode", l: "Advance paid by", t: "select", o: MODES },
      { k: "balance_due_date", l: "Balance due on", t: "date" }, { k: "balance_mode", l: "Balance to be paid by", t: "select", o: MODES },
      { k: "finance_by_buyer", l: "Is the buyer taking a loan?", t: "select", o: YN },
      { k: "buyer_financier", l: "Buyer's lender", when: ["finance_by_buyer", "yes"] },
      { k: "delivery_date", l: "Delivery date", t: "date" },
      { k: "warranty_days", l: "Warranty (days, 0 for none)", t: "number" }, { k: "warranty_km", l: "Warranty (km)", t: "number" },
      { k: "warranty_scope", l: "Warranty covers" }] },
    { name: "Terms", fields: [
      { k: "deal_state", l: "This deal is made in", t: "select", o: [["TN", "Tamil Nadu"], ["KL", "Kerala"]], hint: "Decides the state clauses in the agreement." },
      { k: "place", l: "Place of signing" }, { k: "jurisdiction_city", l: "Courts at" },
      { k: "agreement_date", l: "Agreement date", t: "date" },
      { k: "transfer_cost_bearer", l: "Who pays the transfer fees?", t: "select", o: ["Buyer", "Seller"] },
      { k: "interest_rate", l: "Late payment interest (% a year)", t: "number" },
      { k: "forfeit_pct", l: "If the buyer backs out, keep up to (% of price)", t: "number", hint: "Courts allow only a reasonable amount." },
      { k: "arbitration", l: "Disputes go to", t: "select", o: [["", "Courts only"], ["1", "Arbitration first"]] },
      { k: "stamp_value", l: "Stamp paper value (Rs.)", t: "number", hint: "Your advocate can confirm this." },
      { k: "witness1", l: "Witness 1 (optional)" }, { k: "witness2", l: "Witness 2 (optional)" },
      { k: "extra_clauses", l: "Extra terms, one per line", t: "textarea", span: 1 }] },
  ];

  async function viewDealForm(id) {
    let values;
    if (id) values = (await api("/deals/" + id)).deal;
    else values = { deal_state: ME.state, place: ME.city, jurisdiction_city: ME.city, agreement_date: today(), buyer_state: ME.state, reg_state: ME.state,
      interest_rate: "12", forfeit_pct: "10", warranty_days: "0", warranty_scope: "engine and gearbox", transfer_cost_bearer: "Buyer", advance_mode: "UPI",
      balance_mode: "Bank transfer", hypothecated: "no", finance_by_buyer: "no", accident_history: "none", owners: "1" };
    let step = 0;
    const stepsEl = h("div", { class: "steps" });
    const body = h("div");
    const err = h("div", { class: "error", role: "alert", hidden: true });
    const nav = h("div", { class: "row", style: { marginTop: "22px" } });

    function applyWhen() {
      body.querySelectorAll("label[data-k]").forEach((l) => {
        const f = DEAL_STEPS[step].fields.find((x) => x.k === l.dataset.k);
        if (f && f.when) { const dep = body.querySelector(`[name="${f.when[0]}"]`); l.hidden = !dep || dep.value !== f.when[1]; }
      });
    }
    function draw() {
      stepsEl.replaceChildren(...DEAL_STEPS.map((s, n) => h("div", { class: "step" + (n < step ? " done" : n === step ? " now" : "") }, h("i", null, n < step ? "\u2713" : String(n + 1)), s.name)));
      body.replaceChildren(h("div", { class: "grid panel-in" }, DEAL_STEPS[step].fields.map((f) => field(f, values[f.k]))));
      body.querySelectorAll("select").forEach((s) => s.addEventListener("change", applyWhen));
      applyWhen();
      err.hidden = true;
      nav.replaceChildren(
        step > 0 ? h("button", { class: "btn line", type: "button", onclick: () => go(-1) }, "Back") : h("a", { class: "btn line", href: id ? "#/deals/" + id : "#/deals" }, "Cancel"),
        h("span", { class: "spacer" }),
        step < DEAL_STEPS.length - 1 ? h("button", { class: "btn", type: "button", onclick: () => go(1) }, "Next") : h("button", { class: "btn gold", type: "button", onclick: save }, id ? "Save changes" : "Save deal"));
    }
    function stash() { Object.assign(values, collect(body)); }
    function go(dir) {
      stash();
      if (dir > 0) {
        const miss = DEAL_STEPS[step].fields.find((f) => f.req && !String(values[f.k] || "").trim());
        if (miss) { err.textContent = "Fill in: " + miss.l + "."; err.hidden = false; body.querySelector(`[name="${miss.k}"]`).focus(); return; }
      }
      step += dir;
      draw();
      window.scrollTo(0, 0);
    }
    async function save(e) {
      stash();
      await busy(e.currentTarget, async () => {
        const r = await api(id ? "/deals/" + id : "/deals", id ? "PUT" : "POST", values);
        toast(id ? "Deal saved." : "Deal recorded.");
        location.hash = "#/deals/" + r.id;
      });
    }
    draw();
    return h("div", null,
      h("div", { class: "page-head" }, h("h1", null, id ? "Edit deal" : "Record a deal")),
      h("div", { class: "sheet" }, stepsEl, body, err, nav),
      id ? h("p", { class: "muted small", style: { marginTop: "12px" } }, "Agreements and notices you've already made keep the details they were written with. Create a new agreement version to use these changes.") : null);
  }

  async function viewDeal(id) {
    const r = await api("/deals/" + id);
    const d = r.deal;
    const title = [d.year, d.make, d.model, d.variant].filter(Boolean).join(" ");
    const pickLabel = h("p", { class: "muted small", style: { margin: "0" } }, "Tap a dot to move the car. Now: " + STAGES[d.stage] + ".");
    let current = d.stage;
    const rd = road(d.stage, { big: true, onPick: async (n) => {
      try {
        await api("/deals/" + id + "/stage", "POST", { stage: n });
        current = n;
        rd.style.setProperty("--i", n);
        rd.querySelectorAll(".stop").forEach((s, k) => s.classList.toggle("on", k <= n));
        rd.parentNode.querySelectorAll(".road-labels span").forEach((s, k) => s.classList.toggle("on", k <= n));
        pickLabel.textContent = "Tap a dot to move the car. Now: " + STAGES[n] + ".";
        toast("Moved to " + STAGES[n] + ".");
      } catch (e) { toast(e.message, true); }
    } });

    const checks = h("div", { class: "sheet" }, h("h2", { style: { marginBottom: "6px" } }, "Checks for a " + r.state_name + " sale"),
      h("p", { class: "muted small" }, "Based on what you entered. Fix the red and amber items before handover."),
      r.compliance.map((c) => h("div", { class: "note " + c.level }, h("span", { class: "dot" }), h("span", null, c.text))));

    const agrList = h("div", { style: { marginTop: "12px" } }, r.agreements.map((a, n) => h("div", { class: "list-row" },
      h("div", { class: "grow" }, h("b", null, "Version " + a.version), " ", n === 0 ? h("span", { class: "chip sea" }, "Latest") : null,
        h("div", { class: "muted small" }, "Created " + fmtDT(a.created_at))),
      h("button", { class: "btn soft small", type: "button", onclick: async () => { try { const x = await api("/agreements/" + a.id); openDoc("Sale agreement, version " + a.version, x.body, "/api/agreements/" + a.id + "/docx"); } catch (e) { toast(e.message, true); } } }, "Read"),
      h("a", { class: "btn line small", href: "/api/agreements/" + a.id + "/docx" }, "Download"))));
    const agr = h("div", { class: "sheet" },
      h("div", { class: "row" }, h("div", null, h("h2", null, "Sale agreement"),
        h("p", { class: "muted small", style: { margin: "4px 0 0" } }, "Written for " + r.state_name + ": stamp paper, RTO steps, tax Act, local-language read-over and courts.")),
        h("span", { class: "spacer" }),
        h("button", { class: "btn gold", type: "button", onclick: async (e) => {
          await busy(e.currentTarget, async () => {
            const x = await api("/deals/" + id + "/agreement", "POST", {});
            toast("Agreement created.");
            const doc = await api("/agreements/" + x.id);
            openDoc("Sale agreement, version " + x.version, doc.body, "/api/agreements/" + x.id + "/docx");
            route();
          });
        } }, r.agreements.length ? "Create a new version" : "Create agreement")),
      r.agreements.length ? agrList : h("p", { class: "muted", style: { marginTop: "12px" } }, "No agreement yet. It takes the details from this deal. Have your advocate look it over before first use."));

    const notes = h("div", { class: "sheet" },
      h("div", { class: "row" }, h("div", null, h("h2", null, "Legal notices"),
        h("p", { class: "muted small", style: { margin: "4px 0 0" } }, "Every notice goes to an advocate. It can't be sent until they approve it.")),
        h("span", { class: "spacer" }), h("button", { class: "btn", type: "button", onclick: () => pickNotice(id, r) }, "Draft a notice")),
      r.notices.length
        ? h("div", { style: { marginTop: "10px" } }, r.notices.map((n) => h("a", { class: "list-row", href: "#/notices/" + n.id },
          h("div", { class: "grow" }, h("b", null, n.type_label), h("div", { class: "muted small" }, n.title)), statusChip(n.status), h("span", { class: "muted small" }, fmtDate(n.updated_at)))))
        : h("p", { class: "muted", style: { marginTop: "12px" } }, "No notices on this deal."));

    return h("div", { class: "stack" },
      h("div", { class: "page-head" }, h("div", null, h("a", { href: "#/deals", class: "small" }, "All deals"), h("h1", { style: { marginTop: "6px" } }, title),
        h("div", { class: "row", style: { marginTop: "10px" } }, h("span", { class: "chip gold" }, d.reg_no), stateChip(d.state), h("span", { class: "chip line" }, d.ref),
          h("span", null, d.buyer_name + ", Rs. " + inr(d.price)))),
        h("span", { class: "spacer" }), h("a", { class: "btn line", href: "#/deals/" + id + "/edit" }, "Edit deal")),
      h("div", { class: "sheet mint" }, h("h2", { style: { marginBottom: "10px" } }, "Where this deal is"), rd,
        h("div", { class: "road-labels" }, STAGES.map((s, n) => h("span", { class: n <= current ? "on" : "" }, s))), pickLabel),
      checks, agr, notes);
  }

  async function pickNotice(dealId, r) {
    if (!TYPES) TYPES = (await api("/notice-types")).types;
    const box = h("div");
    const m = modal(box);
    function pickView() {
      box.replaceChildren(h("h2", { style: { marginBottom: "6px" } }, "What do you need to send?"),
        h("p", { class: "muted small" }, "We'll draft it from this deal. An advocate reviews it before it goes anywhere."),
        ...TYPES.map((t) => h("button", { class: "pick", type: "button", onclick: () => factsView(t) }, h("b", null, t.label), t.blurb)),
        h("div", { class: "row end", style: { marginTop: "16px" } }, h("button", { class: "btn line", type: "button", onclick: () => m.close() }, "Cancel")));
    }
    function factsView(t) {
      const err = h("div", { class: "error", role: "alert", hidden: true });
      const form = h("div", { class: "grid" }, t.fields.map((f) => field({ k: f.key, l: f.label, t: f.type, hint: f.hint, span: f.type === "textarea", d: f.default },
        r.notice_prefill[f.key] !== undefined && r.notice_prefill[f.key] !== "" ? r.notice_prefill[f.key] : undefined)));
      box.replaceChildren(h("h2", { style: { marginBottom: "14px" } }, t.label), form, err,
        h("div", { class: "row", style: { marginTop: "18px" } }, h("button", { class: "btn line", type: "button", onclick: pickView }, "Back"), h("span", { class: "spacer" }),
          h("button", { class: "btn gold", type: "button", onclick: async (e) => {
            err.hidden = true;
            const btn = e.currentTarget;
            btn.disabled = true;
            try { const x = await api("/deals/" + dealId + "/notices", "POST", { type: t.key, facts: collect(form) }); m.close(); toast("Draft created. Read it through, then send it to your advocate."); location.hash = "#/notices/" + x.id; }
            catch (ex) { err.textContent = ex.message; err.hidden = false; btn.disabled = false; }
          } }, "Create draft")));
    }
    pickView();
  }

  /* ---------------------------------------------------------------- notices */

  async function viewNotices() {
    const { notices } = await api("/notices");
    const groups = [["Needs you", (n) => n.status === "changes_requested" || n.status === "approved"], ["With your advocate", (n) => n.status === "pending_review"],
      ["Drafts", (n) => n.status === "draft"], ["Sent", (n) => n.status === "sent"]];
    const row = (n) => h("a", { class: "list-row", href: "#/notices/" + n.id }, h("div", { class: "grow" }, h("b", null, n.type_label),
      h("div", { class: "muted small" }, n.buyer_name + ", " + n.vehicle)), statusChip(n.status), h("span", { class: "muted small" }, fmtDate(n.updated_at)));
    const body = notices.length
      ? groups.map(([name, f]) => { const l = notices.filter(f); return l.length ? h("div", { class: "sheet" }, h("h2", { style: { marginBottom: "6px" } }, name), l.map(row)) : null; })
      : h("div", { class: "sheet empty" }, carIcon(), h("h3", null, "No notices yet"), h("p", { class: "muted" }, "Open a deal and choose Draft a notice. Your advocate reviews each one before it can be sent."),
        h("a", { class: "btn", href: "#/deals" }, "Go to deals"));
    return h("div", { class: "stack" }, h("div", { class: "page-head" }, h("h1", null, "Notices")), body);
  }

  async function viewReview() {
    const r = await api("/review");
    const row = (n) => h("a", { class: "list-row", href: "#/notices/" + n.id }, h("div", { class: "grow" }, h("b", null, n.title),
      h("div", { class: "muted small" }, n.dealership_name + " for " + n.buyer_name + ", " + n.vehicle)), statusChip(n.status),
      h("span", { class: "muted small" }, n.status === "pending_review" ? "Waiting since " + fmtDate(n.submitted_at) : fmtDate(n.updated_at)));
    return h("div", { class: "stack" },
      h("div", { class: "page-head" }, h("div", null, h("h1", null, "Review queue"), h("p", { class: "muted", style: { marginTop: "8px" } }, "Nothing goes out until you approve it. Your name and enrolment number appear on what you approve."))),
      h("div", { class: "sheet" }, h("h2", { style: { marginBottom: "6px" } }, "Waiting for you"),
        r.queue.length ? r.queue.map(row) : h("p", { class: "muted" }, "Nothing waiting. Notices sent by dealerships appear here.")),
      r.decided.length ? h("div", { class: "sheet" }, h("h2", { style: { marginBottom: "6px" } }, "Decided by you"), r.decided.map(row)) : null);
  }

  async function viewNotice(id) {
    const n = (await api("/notices/" + id)).notice;
    const dealer = ME.role === "dealer";
    const editable = dealer ? n.status === "draft" || n.status === "changes_requested" : n.status === "pending_review";
    const stamp = STAMP === id;
    STAMP = 0;

    const titleIn = h("input", { value: n.title, "aria-label": "Subject", readonly: !editable });
    const bodyIn = h("textarea", { class: "editor", "aria-label": "Notice text", readonly: !editable });
    bodyIn.value = n.body;
    const preview = h("div", { hidden: true });
    const tabBtns = [["Edit", "edit"], ["Preview", "preview"]].map(([l, k]) => h("button", { type: "button", role: "tab", "aria-selected": String(k === "edit"), onclick: () => {
      tabBtns.forEach((b, i) => b.setAttribute("aria-selected", String(i === (k === "edit" ? 0 : 1))));
      if (k === "preview") { preview.replaceChildren(renderDoc(bodyIn.value)); preview.hidden = false; editorWrap.hidden = true; } else { preview.hidden = true; editorWrap.hidden = false; }
    } }, l));
    const dirty = () => titleIn.value !== n.title || bodyIn.value !== n.body;
    const editorWrap = h("div", null, h("label", { class: "f", style: { marginBottom: "12px" } }, "Subject", titleIn), bodyIn);

    async function saveIfDirty() {
      if (!dirty()) return;
      await api("/notices/" + id, "PUT", { title: titleIn.value, body: bodyIn.value });
    }
    const act = (fn, done) => async (e) => { await busy(e.currentTarget, async () => { await fn(); if (done) toast(done); route(); }); };

    async function polish(e) {
      const btn = e.currentTarget;
      btn.disabled = true;
      btn.replaceChildren(h("span", { class: "spinner" }), " Tidying the wording");
      try {
        await saveIfDirty();
        const { job } = await api("/notices/" + id + "/polish", "POST", {});
        for (let i = 0; i < 80; i++) {
          await sleep(1500);
          const s = await api("/jobs/" + job);
          if (s.status === "done") { toast("Wording tidied. Check it, or undo it."); return route(); }
          if (s.status === "error") throw new Error(s.message);
        }
        throw new Error("The AI is taking too long. Your draft is unchanged.");
      } catch (ex) { toast(ex.message, true); btn.disabled = false; btn.textContent = "Tidy the wording with AI"; }
    }

    function markSent() {
      const mode = h("select", { name: "mode" }, ["Registered post A.D.", "Speed post", "Email", "Hand delivery"].map((x) => h("option", { value: x }, x)));
      const date = h("input", { type: "date", value: today(), max: today() });
      const m = modal(h("div", null, h("h2", { style: { marginBottom: "6px" } }, "Mark as sent"),
        h("p", { class: "muted small" }, "Do this after the approved notice has actually gone out. It locks the notice and records how and when."),
        h("div", { class: "grid" }, h("label", { class: "f" }, "Sent by", mode), h("label", { class: "f" }, "Sent on", date)),
        h("div", { class: "row end", style: { marginTop: "18px" } }, h("button", { class: "btn line", type: "button", onclick: () => m.close() }, "Cancel"),
          h("button", { class: "btn gold", type: "button", onclick: async (e) => { await busy(e.currentTarget, async () => { await api("/notices/" + id + "/sent", "POST", { mode: mode.value, date: date.value }); m.close(); toast("Marked as sent."); route(); }); } }, "Mark as sent"))));
    }

    /* status banner */
    let banner = null;
    const bn = (cls, mark, title, text) => h("div", { class: "status " + cls }, h("span", { class: mark }), h("div", null, h("h3", null, title), text ? h("p", null, text) : null));
    if (n.status === "draft") banner = dealer ? bn("draft", "pencil", "Draft", "Only you can see this. Read it through, then send it to your advocate. It can't go out until they approve it.") : null;
    else if (n.status === "pending_review") banner = dealer ? bn("review", "pulse", "With your advocate", "Sent " + fmtDT(n.submitted_at) + ". Their decision will show here.") : bn("review", "pulse", "Waiting for your review", "Check the facts against the deal, edit if needed, then approve it or ask for changes.");
    else if (n.status === "changes_requested") banner = bn("changes", "flag", dealer ? "Your advocate asked for changes" : "You asked for changes", n.comment);
    else if (n.status === "sent") banner = bn("", "pulse", "Sent by " + n.sent_mode + " on " + fmtDate(n.sent_on), "This notice is locked. Draft a new one if you need to send another.");

    const approvedBox = n.final ? h("div", { class: "approved-box" }, sealArt(n.advocate.name, n.advocate.enrolment, n.approved_at, stamp),
      h("div", { style: { flex: "1", minWidth: "220px" } }, h("h2", null, n.status === "sent" ? "Approved and sent" : dealer ? "Approved. Ready to send." : "You approved this notice"),
        h("p", { class: "muted small", style: { margin: "6px 0 0" } }, "Approved by Adv. " + n.advocate.name + " on " + fmtDate(n.approved_at) + ". Approval code " + n.approval_code + ". The approval covers exactly this text. Any edit withdraws it.")))
      : null;

    let s138 = null;
    if (typeof n.s138_days_left === "number") {
      const left = n.s138_days_left;
      s138 = h("div", { class: "status " + (left > 5 ? "draft" : "changes") }, h("span", { class: left >= 0 ? "pencil" : "flag" }, ""),
        h("div", null, h("h3", null, left > 0 ? plural(left, "day") + " left to send this notice" : left === 0 ? "Today is the last day to send this notice" : "The 30-day window may have passed"),
          h("p", null, "The notice must go out within 30 days of the bank telling you the cheque bounced. " + (left >= 0 ? "The buyer then has 15 days to pay." : "Ask your advocate what can still be done."))));
    }

    /* actions */
    const actions = h("div", { class: "row", style: { marginTop: "16px" } });
    const dl = (label, cls) => h("a", { class: "btn " + cls + " small", href: "/api/notices/" + id + "/docx" }, label);
    if (dealer && editable) {
      actions.append(h("button", { class: "btn gold", type: "button", onclick: act(async () => { await saveIfDirty(); const r = await api("/notices/" + id + "/submit", "POST", {}); if (!r.advocates) toast("Sent to the review queue. No advocate has signed up yet, so share your invite code with yours.", true); }, "Sent to your advocate.") }, "Send to advocate"),
        h("button", { class: "btn soft", type: "button", onclick: act(async () => { await saveIfDirty(); }, "Saved.") }, "Save changes"));
      if (AI) actions.append(h("button", { class: "btn line", type: "button", onclick: polish }, "Tidy the wording with AI"));
      if (n.can_undo) actions.append(h("button", { class: "btn line", type: "button", onclick: act(() => api("/notices/" + id + "/undo", "POST", {}), "Back to your earlier wording.") }, "Undo AI tidy-up"));
      actions.append(h("span", { class: "spacer" }), dl("Download draft", "line"));
    } else if (dealer && n.status === "approved") {
      actions.append(h("a", { class: "btn", href: "/api/notices/" + id + "/docx" }, "Download approved notice"), h("button", { class: "btn gold", type: "button", onclick: markSent }, "Mark as sent"),
        h("button", { class: "btn line small", type: "button", onclick: () => { bodyIn.readOnly = false; titleIn.readOnly = false; bodyIn.focus(); actions.append(h("button", { class: "btn alert", type: "button", onclick: act(async () => { if (!dirty()) { toast("Nothing was changed, so the approval still stands."); return; } await saveIfDirty(); toast("Saved. The approval was withdrawn."); }) }, "Save and withdraw approval")); } }, "Edit this notice"));
    } else if (dealer && n.status === "pending_review") {
      actions.append(h("button", { class: "btn line", type: "button", onclick: (e) => { bodyIn.readOnly = false; titleIn.readOnly = false; bodyIn.focus(); e.currentTarget.remove(); actions.prepend(h("button", { class: "btn alert", type: "button", onclick: act(async () => { if (!dirty()) { toast("Nothing was changed, so it stays with your advocate."); return; } await saveIfDirty(); toast("Taken back from your advocate."); }) }, "Save and take it back")); } }, "Edit this notice"),
        h("span", { class: "spacer" }), dl("Download draft", "line"));
    } else if (!dealer && editable) {
      actions.append(h("button", { class: "btn soft", type: "button", onclick: act(async () => { await saveIfDirty(); }, "Edits saved.") }, "Save my edits"), h("span", { class: "spacer" }), dl("Download draft", "line"));
    } else {
      actions.append(dl("Download " + (n.final ? "approved notice" : "draft"), n.final ? "" : "line"));
    }

    const decision = !dealer && n.status === "pending_review" ? (() => {
      const c = h("textarea", { rows: 3, placeholder: "Optional if you approve. Required if you ask for changes." });
      return h("div", { class: "sheet mint" }, h("h2", { style: { marginBottom: "6px" } }, "Your decision"),
        h("p", { class: "muted small" }, "Approving locks in exactly this text under your name and enrolment number."),
        h("label", { class: "f" }, "Note to the dealership", c),
        h("div", { class: "row", style: { marginTop: "14px" } },
          h("button", { class: "btn gold", type: "button", onclick: async (e) => { await busy(e.currentTarget, async () => { await saveIfDirty(); await api("/notices/" + id + "/decision", "POST", { action: "approve", comment: c.value }); STAMP = id; toast("Approved."); route(); }); } }, "Approve notice"),
          h("button", { class: "btn line", type: "button", onclick: async (e) => { if (!c.value.trim()) { toast("Tell the dealership what to change.", true); c.focus(); return; } await busy(e.currentTarget, async () => { await saveIfDirty(); await api("/notices/" + id + "/decision", "POST", { action: "changes", comment: c.value }); toast("Sent back with your note."); route(); }); } }, "Request changes")));
    })() : null;

    const dd = n.deal;
    const facts = h("div", { class: "sheet tight" }, h("h3", { style: { marginBottom: "10px" } }, "About this deal"),
      h("dl", { class: "facts" }, h("dt", null, "Dealership"), h("dd", null, dd.dealership), h("dt", null, "Buyer"), h("dd", null, dd.buyer), h("dt", null, "Car"), h("dd", null, dd.vehicle),
        h("dt", null, "Price"), h("dd", null, dd.price), h("dt", null, "Advance"), h("dd", null, dd.advance), h("dt", null, "Balance"), h("dd", null, dd.balance),
        dd.delivery_date ? [h("dt", null, "Delivery"), h("dd", null, dd.delivery_date)] : null, h("dt", null, "State"), h("dd", null, dd.state), h("dt", null, "Deal ref"), h("dd", null, dd.ref)),
      h("div", { class: "row", style: { marginTop: "14px" } },
        dd.agreement_id ? h("button", { class: "btn soft small", type: "button", onclick: async () => { try { const x = await api("/agreements/" + dd.agreement_id); openDoc("Sale agreement, version " + dd.agreement_version, x.body); } catch (e) { toast(e.message, true); } } }, "Read the agreement") : h("span", { class: "muted small" }, "No agreement on file."),
        dealer ? h("a", { class: "btn line small", href: "#/deals/" + n.deal_id }, "Open deal") : null));
    const hist = h("div", { class: "sheet tight" }, h("h3", { style: { marginBottom: "12px" } }, "History"),
      h("ul", { class: "tl" }, n.events.map((e) => h("li", { class: e.action }, h("b", null, EVENT_LABEL[e.action] || e.action), h("div", { class: "when" }, e.actor + ", " + fmtDT(e.at)), e.detail ? h("div", null, e.detail) : null))));

    document.title = n.title + " | MFA DealPick";
    return h("div", null,
      h("div", { class: "page-head" }, h("div", null, h("a", { class: "small", href: dealer ? "#/deals/" + n.deal_id : "#/review" }, dealer ? "Back to the deal" : "Back to the queue"),
        h("h1", { style: { marginTop: "6px", fontSize: "clamp(26px,4vw,38px)" } }, n.type_label), h("div", { class: "row", style: { marginTop: "10px" } }, statusChip(n.status), h("span", { class: "chip line" }, dd.ref)))),
      banner, approvedBox, s138,
      h("div", { class: "cols" },
        h("div", { class: "stack" }, h("div", { class: "sheet" }, h("div", { class: "tabs", role: "tablist", style: { maxWidth: "260px" } }, tabBtns), editorWrap, preview,
          dirty() ? null : null, actions), decision),
        h("div", { class: "stack" }, facts, hist)));
  }

  /* ---------------------------------------------------------------- profile */

  async function viewProfile() {
    if (ME.role === "advocate") {
      return h("div", { class: "stack" }, h("div", { class: "page-head" }, h("h1", null, "Your account")),
        h("div", { class: "sheet" }, h("dl", { class: "facts" }, h("dt", null, "Name"), h("dd", null, "Adv. " + ME.name), h("dt", null, "Email"), h("dd", null, ME.email),
          h("dt", null, "Enrolment no."), h("dd", null, ME.bar_enrolment))));
    }
    const specs = [{ k: "dealership_name", l: "Dealership name" }, { k: "signatory", l: "Authorised signatory", hint: "Signs the agreements for your dealership." },
      { k: "address", l: "Address", t: "textarea", span: 1 }, { k: "city", l: "City or town" }, { k: "state", l: "State", t: "select", o: [["TN", "Tamil Nadu"], ["KL", "Kerala"]] },
      { k: "phone", l: "Phone" }, { k: "gstin", l: "GSTIN" }, { k: "trade_cert", l: "Trade certificate no." }];
    const form = h("div", { class: "grid" }, specs.map((f) => field(f, ME[f.k])));
    return h("div", { class: "stack" }, h("div", { class: "page-head" }, h("h1", null, "Your dealership")),
      h("div", { class: "sheet" }, h("p", { class: "muted" }, "These details appear as the seller in every agreement and notice."), form,
        h("div", { class: "row", style: { marginTop: "18px" } }, h("button", { class: "btn gold", type: "button", onclick: async (e) => {
          await busy(e.currentTarget, async () => { const r = await api("/profile", "PUT", collect(form)); ME = r.user; toast("Dealership details saved."); route(); });
        } }, "Save details"))));
  }

  /* ---------------------------------------------------------------- start */

  async function boot() {
    try { const r = await api("/me"); ME = r.user; AI = r.ai; } catch (e) { ME = null; }
    route();
  }
  window.addEventListener("hashchange", route);
  boot();
})();
