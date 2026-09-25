// Renders a page of site/ without a browser: a minimal document stub, a fetch
// that reads files from disk, the shared assets/site.js and then the page's own
// inline script, run as they are.
//
//   node tests/site/harness.js <page.html> <site root> [<location.search>] [<course> <position>] [<expression>]
//
// <site root> is the directory the page's relative fetches ("data/meta.json")
// resolve against; assets/site.js is read next to the page. Prints one JSON
// object: every element the page touched (innerHTML, hidden, textContent,
// value), the document title, and, when an expression is given, its value
// evaluated in the page's context (e.g. "BWO.findCourse(...)"). Used by
// tests/test_site.py; not part of the site.
"use strict";
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const [htmlPath, root, search = "", course = "", position = "", expression = ""] = process.argv.slice(2);
if (!htmlPath || !root) {
  console.error("usage: harness.js <page.html> <site root> [search] [course position] [expression]");
  process.exit(2);
}

const html = fs.readFileSync(htmlPath, "utf8");

class Element {
  constructor(id, tag, attrs) {
    this.id = id;
    this.tagName = (tag || "div").toUpperCase();
    this.innerHTML = "";
    this.textContent = "";
    this.value = attrs.value || "";
    this.hidden = "hidden" in attrs;
    this.attrs = { ...attrs };
    this.listeners = {};
    this.classes = new Set((attrs.class || "").split(/\s+/).filter(Boolean));
    this.style = {};
    this.parentNode = null;
    this.classList = {
      add: (c) => this.classes.add(c),
      remove: (c) => this.classes.delete(c),
      contains: (c) => this.classes.has(c),
      toggle: (c, on) => (on === undefined ? (this.classes.has(c) ? this.classes.delete(c) : this.classes.add(c)) : on ? this.classes.add(c) : this.classes.delete(c)),
    };
  }
  addEventListener(type, fn) { (this.listeners[type] = this.listeners[type] || []).push(fn); }
  removeEventListener(type, fn) { this.listeners[type] = (this.listeners[type] || []).filter((f) => f !== fn); }
  dispatch(type, ev) { for (const fn of this.listeners[type] || []) fn({ preventDefault() {}, target: this, key: "", ...(ev || {}) }); }
  requestSubmit() { this.dispatch("submit"); }
  setAttribute(k, v) { this.attrs[k] = String(v); if (k === "hidden") this.hidden = true; }
  getAttribute(k) { return k in this.attrs ? this.attrs[k] : null; }
  removeAttribute(k) { delete this.attrs[k]; if (k === "hidden") this.hidden = false; }
  hasAttribute(k) { return k in this.attrs; }
  focus() {}
  blur() {}
  scrollIntoView() {}
  getBoundingClientRect() { return { left: 0, top: 0, width: 640, height: 260 }; }
}

// The attributes an element starts with in the markup (class, hidden, value).
function initialAttrs(id) {
  const m = html.match(new RegExp("<([a-z]+)([^>]*)\\bid=\"" + id + "\"([^>]*)>"));
  if (!m) return { tag: "div", attrs: {} };
  const attrs = {};
  for (const part of [m[2], m[3]]) {
    for (const a of part.matchAll(/\b([a-zA-Z-]+)(?:="([^"]*)")?/g)) attrs[a[1]] = a[2] === undefined ? "" : a[2];
  }
  return { tag: m[1], attrs };
}

const elements = {};
const document = {
  title: (html.match(/<title>([^<]*)<\/title>/) || [, ""])[1],
  getElementById(id) {
    if (!elements[id]) { const { tag, attrs } = initialAttrs(id); elements[id] = new Element(id, tag, attrs); }
    return elements[id];
  },
  addEventListener() {},
  querySelector() { return null; },
  querySelectorAll() { return []; },
};

// Relative URLs are files under <site root>. The one absolute URL a page fetches
// is the live file on the data branch (LIVE_URL in course.html): it is served
// from HARNESS_LIVE_FILE, and 404s when that variable is unset, as it does in a
// checkout with no data branch. Any other absolute URL stays a 404.
const LIVE_URL = "https://raw.githubusercontent.com/oliver139-chinesemole/berkeley-waitlist-odds/data/live/latest.json";

async function fetchStub(url) {
  const file = url === LIVE_URL ? process.env.HARNESS_LIVE_FILE || "" : path.join(root, url.split("?")[0]);
  if (!file || !fs.existsSync(file)) return { ok: false, status: 404, json: async () => { throw new Error("404"); } };
  if (process.env.HARNESS_FAIL_FETCH) throw new TypeError("Failed to fetch");
  const text = fs.readFileSync(file, "utf8");
  return { ok: true, status: 200, json: async () => JSON.parse(text) };
}

const scripts = [...html.matchAll(/<script(?:\s+src="([^"]+)")?>([\s\S]*?)<\/script>/g)];
if (!scripts.length) {
  console.error("no <script> in " + htmlPath);
  process.exit(2);
}

// Built-ins (Math, Date, JSON, Promise, ...) exist in the new context on their
// own; only the browser globals the pages use are supplied.
const sandbox = {
  document,
  fetch: fetchStub,
  location: { search, pathname: "/" + path.basename(htmlPath), origin: "https://example.test", href: "https://example.test/" + path.basename(htmlPath) + search },
  history: { replaceState(_s, _t, url) { sandbox.location.href = url; } },
  URLSearchParams,
  console,
  setTimeout,
  clearTimeout,
  encodeURIComponent,
  decodeURIComponent,
};
sandbox.window = sandbox;
// HARNESS_NOW (an ISO timestamp) pins Date.now(), so the ages a page prints from
// observed_at are fixed numbers; without it the real clock is used, as in a browser.
// A typo must not fall back to the real clock and fail as a baffling age.
if (process.env.HARNESS_NOW) {
  const pinnedNow = Date.parse(process.env.HARNESS_NOW);
  if (Number.isNaN(pinnedNow)) throw new Error("HARNESS_NOW is not a date Date.parse understands: " + process.env.HARNESS_NOW);
  sandbox.Date = class extends Date {
    constructor(...args) { super(...(args.length ? args : [pinnedNow])); }
    static now() { return pinnedNow; }
  };
}
vm.createContext(sandbox);
for (const s of scripts) {
  if (s[1]) {
    const src = path.join(path.dirname(htmlPath), s[1]);
    vm.runInContext(fs.readFileSync(src, "utf8"), sandbox, { filename: s[1] });
  } else if (s[2].trim()) {
    vm.runInContext(s[2], sandbox, { filename: path.basename(htmlPath) });
  }
}

const tick = () => new Promise((resolve) => setImmediate(resolve));
async function settle(n) { for (let i = 0; i < n; i++) await tick(); }

(async () => {
  const status = document.getElementById("status");
  for (let i = 0; i < 200 && /Loading/.test(status.innerHTML); i++) await tick();
  await settle(10);
  if (course) {
    document.getElementById("course").value = course;
    document.getElementById("position").value = position;
    document.getElementById("form").requestSubmit();
    await settle(20);
  }
  const out = { title: document.title, elements: {} };
  for (const [id, el] of Object.entries(elements)) {
    out.elements[id] = { html: el.innerHTML, hidden: !!el.hidden || el.classes.has("hidden"), text: el.textContent, value: el.value, attrs: el.attrs };
  }
  const get = (id) => elements[id] || document.getElementById(id);
  out.status = get("status").innerHTML;
  out.form_hidden = !!get("form").hidden || get("form").classes.has("hidden");
  out.result = get("result").innerHTML;
  out.result_hidden = !!get("result").hidden || get("result").classes.has("hidden");
  out.stamp = get("stamp").textContent;
  out.location = sandbox.location.href;
  if (expression) {
    try {
      const value = vm.runInContext(expression, sandbox);
      out.eval = value && typeof value.then === "function" ? await value : value;
    } catch (err) {
      out.eval_error = String(err && err.message ? err.message : err);
    }
  }
  process.stdout.write(JSON.stringify(out));
})().catch((err) => {
  console.error(err && err.stack ? err.stack : String(err));
  process.exit(1);
});
