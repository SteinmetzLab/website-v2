/* Execute a built page's <script> against a minimal DOM stub, to catch setup-time errors
   without a browser. It cannot verify layout -- only that the code runs.

   Usage: node tools/runpage.js out/a2-signal.html            */
const fs = require('fs');
const path = require('path');

const file = process.argv[2] || 'out/a2-signal.html';
const html = fs.readFileSync(file, 'utf8');

// ---- which element ids and classes actually exist in the markup ----------------
const ids = new Set([...html.matchAll(/\bid="([\w-]+)"/g)].map((m) => m[1]));
const classes = new Set(
  [...html.matchAll(/class="([^"]+)"/g)].flatMap((m) => m[1].split(/\s+/)));

const noop = () => {};
const ctx2d = new Proxy({}, {
  get: (_, k) => {
    if (k === 'canvas') return el('canvas');
    if (k === 'createImageData') return (w, h) => ({ data: new Uint8ClampedArray(w * h * 4) });
    if (k === 'getImageData') return (x, y, w, h) => ({ data: new Uint8ClampedArray(w * h * 4) });
    if (k === 'measureText') return () => ({ width: 10 });
    if (k === 'createLinearGradient' || k === 'createRadialGradient')
      return () => ({ addColorStop: noop });
    return noop;
  },
  set: () => true,
});

function el(tag = 'div', id = '') {
  const node = {
    tagName: (tag || 'div').toUpperCase(),
    id, dataset: {}, style: {}, children: [], hidden: false,
    width: 300, height: 150, textContent: '', value: '',
    classList: { add: noop, remove: noop, toggle: noop, contains: () => false },
    getContext: () => ctx2d,
    getBoundingClientRect: () => ({ width: 600, height: 340, left: 0, top: 0 }),
    addEventListener: noop, removeEventListener: noop, setPointerCapture: noop,
    setAttribute: noop, getAttribute: () => null, hasAttribute: () => false,
    removeAttribute: noop, appendChild: (c) => c, insertAdjacentHTML: noop,
    querySelector: () => el(), querySelectorAll: () => [],
    closest: () => null, focus: noop, play: () => Promise.resolve(), pause: noop,
    getElementsByTagName: () => [],
  };
  return node;
}

const documentEl = el('html');
global.document = {
  documentElement: documentEl,
  head: el('head'),
  body: el('body'),
  createElement: (t) => el(t),
  createElementNS: (ns, t) => Object.assign(el(t), { setAttribute: noop }),
  getElementById: (i) => (ids.has(i) ? el('div', i) : null),
  querySelector: (s) => el(),
  // return one stub per selector so forEach/map paths execute
  querySelectorAll: (s) => {
    const cls = s.replace(/^[.#]/, '').split(/[ .[:]/)[0];
    return classes.has(cls) || s.includes('[') ? [el(), el()] : [];
  },
  addEventListener: noop,
  fonts: { ready: Promise.resolve() },
};
global.window = global;
global.matchMedia = () => ({ matches: false, addEventListener: noop, addListener: noop });
global.getComputedStyle = () => ({
  getPropertyValue: (p) => (p.startsWith('--d') && p.length === 4 ? '#112233'
    : p === '--mono' ? 'monospace' : '#889999'),
  fontFamily: 'monospace',
});
global.devicePixelRatio = 2;
global.requestAnimationFrame = () => 0;
global.cancelAnimationFrame = noop;
global.IntersectionObserver = class { constructor() {} observe() {} unobserve() {} disconnect() {} };
global.ResizeObserver = class { constructor() {} observe() {} disconnect() {} };
global.addEventListener = noop;
global.scrollY = 0;
global.atob = (s) => Buffer.from(s, 'base64').toString('binary');
global.performance = { now: () => 0 };

/* Collect every script the page runs, in document order: the linked ones (engine, the
   recordings) as well as the inline block. They are concatenated and run as one body
   rather than one call per script, because that is the part of the browser's behavior
   this test exists to check -- a `const` at the top of a classic script is visible to
   every script after it, which is the whole reason the page can keep using SL and RASTER
   as if they were still pasted in above it. Running each separately would scope them
   away and pass a page that breaks in a browser. */
const parts = [];
for (const m of html.matchAll(/<script\b([^>]*)>([\s\S]*?)<\/script>/g)) {
  const src = /\bsrc="([^"]+)"/.exec(m[1]);
  if (src) {
    const p = path.resolve(path.dirname(file), src[1]);
    if (!fs.existsSync(p)) {
      console.log(`${file}: missing linked script ${src[1]}`);
      process.exit(1);
    }
    parts.push({ name: src[1], code: fs.readFileSync(p, 'utf8') });
  } else {
    parts.push({ name: '(inline)', code: m[2] });
  }
}

console.log(`${file}: ${parts.length} script(s): ${parts.map((p) => p.name).join(', ')}`);

// Line at which each part starts in the concatenated body, for blaming an error.
const starts = [];
let n = 1;
for (const p of parts) { starts.push(n); n += p.code.split('\n').length; }
const body = parts.map((p) => p.code).join('\n');

try {
  new Function(body)();
  console.log('  ran to completion');
  process.exit(0);
} catch (e) {
  console.log(`  ${e.constructor.name}: ${e.message}`);
  const at = /<anonymous>:(\d+):/.exec(
    (e.stack || '').split('\n').find((l) => l.includes('<anonymous>')) || '');
  if (at) {
    const line = +at[1] - 2;               // new Function wraps the body in one extra line
    let i = starts.findIndex((s) => s > line) - 1;
    if (i < 0) i = parts.length - 1;
    console.log(`  in ${parts[i].name}:`);
    const src = body.split('\n');
    for (let j = Math.max(0, line - 3); j < Math.min(src.length, line + 2); j++) {
      console.log(`    ${j + 1 === line ? '>>' : '  '} ${src[j]}`);
    }
  }
  process.exit(1);
}
