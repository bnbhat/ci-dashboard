/* Shared helpers for the CI dashboard pages. Loaded before Alpine.js
 * initializes each page's x-data component. */

function toggleTheme() {
  const html = document.documentElement;
  const goingDark = !html.classList.contains('is-dark');
  html.classList.remove('is-dark', 'is-paper');
  html.classList.add(goingDark ? 'is-dark' : 'is-paper');
  localStorage.setItem('ci-dashboard-theme', goingDark ? 'dark' : 'paper');
}

/* Base path to the generated data directory. Overridable via a
 * <meta name="ci-dashboard-data-base"> tag if the site is ever served
 * from a sub-path. */
function dataBase() {
  const meta = document.querySelector('meta[name="ci-dashboard-data-base"]');
  return meta ? meta.content : 'data';
}

async function fetchJSON(path) {
  const res = await fetch(`${dataBase()}/${path}`, { cache: 'no-store' });
  if (!res.ok) {
    throw new Error(`Failed to load ${path}: HTTP ${res.status}`);
  }
  return res.json();
}

function statusChipClass(status) {
  return { pass: 'is-pass', fail: 'is-fail', skip: 'is-skip', 'failed-ignored': 'is-ignored' }[status] || 'is-skip';
}

function statusLabel(status) {
  return { 'failed-ignored': 'ignored' }[status] || status;
}

/* Strips the "com.canonical.certification::" style namespace prefix
 * from a Checkbox full test id, keeping only the part after '::'. */
function testIdShort(fullId) {
  if (!fullId) return fullId;
  const idx = fullId.indexOf('::');
  return idx === -1 ? fullId : fullId.slice(idx + 2);
}

function formatDuration(seconds) {
  if (seconds === null || seconds === undefined) return '—';
  if (seconds < 1) return `${Math.round(seconds * 1000)}ms`;
  if (seconds < 60) return `${seconds.toFixed(1)}s`;
  const m = Math.floor(seconds / 60);
  const s = Math.round(seconds % 60);
  return `${m}m ${s}s`;
}

function formatTimestamp(iso) {
  if (!iso) return '—';
  try {
    const d = new Date(iso);
    return d.toLocaleString(undefined, {
      year: 'numeric', month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit',
    });
  } catch (e) {
    return iso;
  }
}

function passRate(summary) {
  const total = (summary.pass || 0) + (summary.fail || 0) + (summary.skip || 0);
  const scored = (summary.pass || 0) + (summary.fail || 0);
  if (scored === 0) return null;
  return Math.round(((summary.pass || 0) / scored) * 100);
}

/* Draws a tiny inline pass-rate sparkline (0-100 values, oldest first)
 * onto a <canvas>. No chart library dependency needed for this. */
function drawSparkline(canvas, values) {
  if (!canvas || !values || values.length === 0) return;
  const ctx = canvas.getContext('2d');
  const w = canvas.width;
  const h = canvas.height;
  ctx.clearRect(0, 0, w, h);
  const max = 100;
  const min = 0;
  const stepX = values.length > 1 ? w / (values.length - 1) : 0;
  ctx.beginPath();
  values.forEach((v, i) => {
    const x = i * stepX;
    const y = h - ((v - min) / (max - min)) * h;
    if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
  });
  ctx.strokeStyle = '#E95420';
  ctx.lineWidth = 2;
  ctx.stroke();
}
