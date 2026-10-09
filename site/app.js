// Renders shows and regular classes from the backend (/api/*.json), which builds them from the
// Institute's Google Calendar. The backend has already removed past performances.
const API = '/api';
const DAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
const MONTHS_LONG = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'];
const MARK = '<svg viewBox="0 0 120 96" fill="none" aria-hidden="true"><path d="M8 34 L60 7 L112 34M14 40 H106M24 92 V66 A14 14 0 0 1 52 66 V92M68 92 V66 A14 14 0 0 1 96 66 V92M6 92 H114" stroke="#B27A2B" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/></svg>';

const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const parse = d => { const [y, m, day] = d.split('-').map(Number); return new Date(y, m - 1, day); };
const iso = d => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
const addDays = (d, n) => new Date(d.getFullYear(), d.getMonth(), d.getDate() + n);

function shortRange(s, e) {
  const a = parse(s), b = parse(e || s);
  if (+a === +b) return `${a.getDate()} ${MONTHS[a.getMonth()]}`;
  if (a.getMonth() === b.getMonth()) return `${a.getDate()}–${b.getDate()} ${MONTHS[a.getMonth()]}`;
  return `${a.getDate()} ${MONTHS[a.getMonth()]} – ${b.getDate()} ${MONTHS[b.getMonth()]}`;
}
function longRange(s, e) {
  const a = parse(s), b = parse(e || s);
  if (+a === +b) return `${a.getDate()} ${MONTHS_LONG[a.getMonth()]} ${a.getFullYear()}`;
  if (a.getMonth() === b.getMonth()) return `${a.getDate()} – ${b.getDate()} ${MONTHS_LONG[a.getMonth()]} ${b.getFullYear()}`;
  return `${a.getDate()} ${MONTHS_LONG[a.getMonth()]} – ${b.getDate()} ${MONTHS_LONG[b.getMonth()]} ${b.getFullYear()}`;
}
// "Fri 30 Oct – Sat 7 Nov · 7.30pm (doors 7pm)"
const scheduleLine = l => [l.dates, l.time && (l.doors ? `${l.time} (doors ${l.doors})` : l.time), l.status].filter(Boolean).join(' · ');
const statusBadge = s => (s.draft ? '<span class="status">DRAFT · test only</span>' : '') + (s.status ? `<span class="status">${esc(s.status)}</span>` : '');

const poster = s => {
  const images = (s.images?.length ? s.images : s.image ? [s.image] : []);
  if (!images.length) return `<div class="poster">${MARK}</div>`;
  if (images.length === 1) return `<div class="poster"><img src="${esc(images[0])}" alt="Poster for ${esc(s.title)}" loading="lazy"></div>`;
  return `<div class="poster poster-carousel" data-images="${esc(JSON.stringify(images))}">
    <img src="${esc(images[0])}" alt="Image 1 of ${images.length} for ${esc(s.title)}" loading="lazy">
    <div class="poster-controls">
      <button type="button" data-step="-1" aria-label="Previous image">‹</button>
      <span class="poster-count" aria-live="polite">1 / ${images.length}</span>
      <button type="button" data-step="1" aria-label="Next image">›</button>
    </div>
  </div>`;
};

function startCarousels() {
  document.querySelectorAll('.poster-carousel').forEach(el => {
    const images = JSON.parse(el.dataset.images);
    const img = el.querySelector('img');
    const count = el.querySelector('.poster-count');
    const title = img.alt.replace(/^Image \d+ of \d+ for /, '');
    let index = 0;
    const move = n => {
      index = (index + n + images.length) % images.length;
      img.src = images[index];
      img.alt = `Image ${index + 1} of ${images.length} for ${title}`;
      count.textContent = `${index + 1} / ${images.length}`;
    };
    el.querySelectorAll('button[data-step]').forEach(b => b.addEventListener('click', () => move(Number(b.dataset.step))));
    if (!matchMedia('(prefers-reduced-motion: reduce)').matches) {
      setInterval(() => {
        if (!document.hidden && !el.matches(':hover') && !el.matches(':focus-within')) move(1);
      }, 7500);
    }
  });
}
const buttons = (s, big) => {
  const t = s.ticketsUrl && s.status !== 'Cancelled' ? `<a class="btn btn-solid" href="${esc(s.ticketsUrl)}">${big ? 'Book tickets' : 'Tickets'}<span class="visually-hidden"> for ${esc(s.title)}</span></a>` : '';
  const w = s.websiteUrl ? `<a class="btn btn-line" href="${esc(s.websiteUrl)}">Website<span class="visually-hidden"> for ${esc(s.title)}</span></a>` : '';
  return t || w ? `<div class="buttons">${t}${w}</div>` : '';
};

function renderFeature(s) {
  const el = document.getElementById('feature');
  if (!s) { el.innerHTML = `<div class="feature-text"><div class="eyebrow">What's on</div><h2>New shows coming soon</h2></div>`; return; }
  const today = new Date(); today.setHours(0, 0, 0, 0);
  const label = parse(s.startDate) <= today ? 'Now playing' : 'Next on stage';
  const times = (s.schedule || []).map(l => esc(scheduleLine(l))).join('<br>');
  const facts = [['Dates', esc(longRange(s.startDate, s.endDate))], ['Times', times], ['Venue', esc(s.venue)], ['Tickets', esc(s.price)],
    ['Suitable for', esc(s.suitableFor)], ['Duration', esc(s.duration)]].filter(f => f[1]);
  el.innerHTML = `${poster(s)}
    <div class="feature-text">
      <div class="eyebrow">${label}${statusBadge(s)}</div>
      <h2>${esc(s.title)}</h2>
      ${s.company ? `<div class="company"><span>${esc(s.company)}</span></div>` : ''}
      ${s.summary ? `<p class="summary">${esc(s.summary)}</p>` : ''}
      <dl class="facts">${facts.map(([k, v]) => `<dt>${k}</dt><dd>${v}</dd>`).join('')}</dl>
      ${buttons(s, true)}
    </div>`;
}

function renderUpcoming(list) {
  const el = document.getElementById('upcoming');
  if (!list.length) { el.innerHTML = '<div class="empty">More shows will be announced soon.</div>'; return; }
  el.innerHTML = list.map(s => {
    const first = (s.schedule || [])[0];
    const when = first ? [first.time, s.schedule.length > 1 ? 'more times' : ''].filter(Boolean).join(', ') : '';
    return `
    <article class="show-row">
      ${poster(s)}
      <div class="show-date">${shortRange(s.startDate, s.endDate)}</div>
      <div><h3>${esc(s.title)}${statusBadge(s)}</h3><div class="by">${[s.company, s.venue, when].filter(Boolean).map(esc).join(' · ')}</div></div>
      ${buttons(s, false) || '<div></div>'}
    </article>`;
  }).join('');
}

function renderWeeks(data) {
  const grid = document.getElementById('week-grid');
  const tabs = document.getElementById('week-tabs');
  const start = parse(data.from);
  const today = iso(new Date());
  const weeks = Math.round(((parse(data.to) - start) / 864e5 + 1) / 7) || 4;
  const byDate = {};
  (data.sessions || []).forEach(s => (byDate[s.date] ||= []).push(s));
  const label = w => w === 0 ? 'This week' : w === 1 ? 'Next week' : `Week of ${shortRange(iso(addDays(start, 7 * w)))}`;

  const show = w => {
    tabs.querySelectorAll('button').forEach((b, i) => b.setAttribute('aria-pressed', String(i === w)));
    grid.innerHTML = DAYS.map((d, i) => {
      const date = addDays(start, 7 * w + i), key = iso(date);
      const items = (byDate[key] || []).map(s => {
        const cancelled = s.status === 'Cancelled';
        const inner = `<span class="t">${esc(s.time)}${cancelled ? ' · Cancelled' : ''}</span><span class="n">${esc(s.name)}</span><span class="a">${esc(s.activity)}</span>${s.venue ? `<span class="a">${esc(s.venue)}</span>` : ''}`;
        const cls = `session${cancelled ? ' cancelled' : ''}`;
        return s.websiteUrl ? `<a class="${cls}" href="${esc(s.websiteUrl)}">${inner}</a>` : `<div class="${cls}">${inner}</div>`;
      }).join('');
      return `<div class="day${key < today ? ' past' : ''}"><h3 class="day-name">${d} ${date.getDate()} ${MONTHS[date.getMonth()]}</h3><div class="day-items">${items}</div></div>`;
    }).join('');
  };
  tabs.innerHTML = Array.from({ length: weeks }, (_, w) => `<button type="button" aria-pressed="false">${label(w)}</button>`).join('');
  tabs.querySelectorAll('button').forEach((b, w) => b.addEventListener('click', () => show(w)));
  show(0);
}

function openCurtain() {
  const stage = document.querySelector('.stage');
  const reduce = matchMedia('(prefers-reduced-motion: reduce)').matches;
  setTimeout(() => stage.classList.add('open'), reduce ? 0 : 600);
}

(async () => {
  const get = (u, fallback) => fetch(`${API}/${u}`).then(r => r.ok ? r.json() : fallback).catch(() => fallback);
  const [shows, regulars] = await Promise.all([get('shows.json', { shows: [] }), get('regulars.json', null)]);
  const live = shows.shows || [];
  const featured = live.find(s => s.featured) || live[0];
  renderFeature(featured);
  renderUpcoming(live.filter(s => s !== featured));
  startCarousels();
  if (regulars) renderWeeks(regulars);
  else document.getElementById('week-grid').innerHTML = '<div class="empty">The timetable is unavailable right now.</div>';
  openCurtain();
})();

// Caddy returns 204 only when this browser reaches the site from Staff Wi-Fi.
// Never use the visibility of this link as an access-control mechanism.
fetch('/api/staff-status', { cache: 'no-store', credentials: 'same-origin' })
  .then(response => {
    if (response.status === 204) document.getElementById('staff-admin-link').hidden = false;
  })
  .catch(() => {});


// Theme is public configuration; the admin colour picker controls only a CSS variable.
fetch('/api/appearance.json', { cache: 'no-store' })
  .then(r => r.ok ? r.json() : null)
  .then(theme => {
    if (theme && /^#[0-9a-fA-F]{6}$/.test(theme.curtain))
      document.documentElement.style.setProperty('--curtain-base', theme.curtain);
  }).catch(() => {});
