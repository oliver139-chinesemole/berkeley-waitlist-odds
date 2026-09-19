// Renders site/index.html without a browser: a minimal document stub, a fetch
// that reads files from disk, and the page's own inline script run as is.
//
//   node tests/site/harness.js <index.html> <site root> [<location.search>] [<course> <position>]
//
// Prints one JSON object: the status card, whether the form is hidden, the
// result card (and whether it is hidden), the footer stamp and the number of
// datalist options. Used by tests/test_site.py; not part of the site.
"use strict";
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const [htmlPath, root, search = "", course = "", position = ""] = process.argv.slice(2);
if (!htmlPath || !root) {
  console.error("usage: harness.js <index.html> <site root> [search] [course position]");
  process.exit(2);
}

class Element {
  constructor(id, classes) {
    this.id = id;
    this.innerHTML = "";
    this.textContent = "";
    this.value = "";
    this.listeners = {};
    this.classes = new Set(classes);
    this.classList = {
      add: (c) => this.classes.add(c),
      remove: (c) => this.classes.delete(c),
      contains: (c) => this.classes.has(c),
    };
  }
  addEventListener(type, fn) {
    (this.listeners[type] = this.listeners[type] || []).push(fn);
  }
  dispatch(type) {
    for (const fn of this.listeners[type] || []) fn({ preventDefault() {} });
  }
  requestSubmit() {
    this.dispatch("submit");
  }
  scrollIntoView() {}
}

const html = fs.readFileSync(htmlPath, "utf8");

// The classes an element starts with in the markup (e.g. the hidden result card).
function initialClasses(id) {
  const tag = html.match(new RegExp('<[a-z]+[^>]*\\bid="' + id + '"[^>]*>'));
  const cls = tag && tag[0].match(/\bclass="([^"]*)"/);
  return cls ? cls[1].split(/\s+/).filter(Boolean) : [];
}

const elements = {};
const document = {
  getElementById(id) {
    if (!elements[id]) elements[id] = new Element(id, initialClasses(id));
    return elements[id];
  },
};

async function fetchStub(url) {
  const file = path.join(root, url.split("?")[0]);
  if (!fs.existsSync(file)) return { ok: false, status: 404, json: async () => { throw new Error("404"); } };
  const text = fs.readFileSync(file, "utf8");
  return { ok: true, status: 200, json: async () => JSON.parse(text) };
}

const match = html.match(/<script>([\s\S]*?)<\/script>/);
if (!match) {
  console.error("no inline <script> in " + htmlPath);
  process.exit(2);
}

// Built-ins (Math, Date, JSON, Promise, ...) exist in the new context on their
// own; only the browser globals the page uses are supplied.
const sandbox = {
  document,
  fetch: fetchStub,
  location: { search },
  URLSearchParams,
  console,
  setTimeout,
};
vm.createContext(sandbox);
vm.runInContext(match[1], sandbox, { filename: "index.html" });

const tick = () => new Promise((resolve) => setImmediate(resolve));

(async () => {
  const status = document.getElementById("status");
  for (let i = 0; i < 100 && /Loading/.test(status.innerHTML); i++) await tick();
  for (let i = 0; i < 5; i++) await tick();
  if (course) {
    document.getElementById("course").value = course;
    document.getElementById("position").value = position;
    document.getElementById("form").requestSubmit();
    for (let i = 0; i < 5; i++) await tick();
  }
  const out = {
    status: status.innerHTML,
    form_hidden: document.getElementById("form").classList.contains("hidden"),
    result: document.getElementById("result").innerHTML,
    result_hidden: document.getElementById("result").classList.contains("hidden"),
    stamp: document.getElementById("stamp").textContent,
    datalist_options: (document.getElementById("courses").innerHTML.match(/<option /g) || []).length,
  };
  process.stdout.write(JSON.stringify(out));
})().catch((err) => {
  console.error(err && err.stack ? err.stack : String(err));
  process.exit(1);
});
