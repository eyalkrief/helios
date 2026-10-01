/* ═══════════════════════════════════════════════════════════════
   HELIOS — Dashboard
   ═══════════════════════════════════════════════════════════════ */

const $ = s => document.querySelector(s);
const $$ = s => document.querySelectorAll(s);

let me = null;
let currentPage = 0;
const PAGE_SIZE = 50;
let currentSearch = '';
let currentFilters = { status: '', city: '', sector: '', number_type: '' };
let allCompaniesCache = [];

/* ─── Utils ─────────────────────────────────────────────────── */

function escapeHTML(s) {
  if (s == null) return '';
  return String(s).replace(/[&<>'"]/g, t => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;'
  }[t]));
}

function toast(msg, type = 'info') {
  const icons = {
    success: '<path d="M20 6L9 17l-5-5"/>',
    error: '<circle cx="12" cy="12" r="10"/><path d="M15 9l-6 6M9 9l6 6"/>',
    info: '<circle cx="12" cy="12" r="10"/><path d="M12 16v-4M12 8h.01"/>'
  };
  const el = document.createElement('div');
  el.className = 'toast ' + type;
  el.innerHTML = '<svg class="toast-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">' + (icons[type] || icons.info) + '</svg><span>' + escapeHTML(msg) + '</span>';
  $('#toast-container').appendChild(el);
  setTimeout(() => {
    el.style.transition = 'opacity 200ms, transform 200ms';
    el.style.opacity = '0';
    el.style.transform = 'translateX(20px)';
    setTimeout(() => el.remove(), 200);
  }, 3000);
}

/* ─── Navigation ────────────────────────────────────────────── */

$$('.nav-item').forEach(btn => {
  btn.addEventListener('click', () => {
    $$('.nav-item').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    const v = btn.dataset.view;
    $$('.view').forEach(x => x.classList.remove('active'));
    $('#view-' + v).classList.add('active');

    if (v === 'clusters') loadClusters();
    if (v === 'stats') loadStats();
    if (v === 'api') loadApi();
  });
});

/* ─── Init ──────────────────────────────────────────────────── */

async function init() {
  try {
    const r = await fetch('/api/me');
    const d = await r.json();
    if (d.success) me = d.data;
  } catch (e) {}

  try {
    const r = await fetch('/api/filters');
    const d = await r.json();
    if (d.success) {
      fillSelect('#filter-status', d.data.statuses, 'Tous les statuts');
      fillSelect('#filter-city', d.data.cities, 'Toutes les villes');
      fillSelect('#filter-sector', d.data.sectors, 'Tous les secteurs');
    }
  } catch (e) {}

  ['#filter-status', '#filter-city', '#filter-sector', '#filter-number-type'].forEach(s => {
    const el = $(s);
    if (el) el.addEventListener('change', loadCompanies);
  });

  loadCompanies();
}

function fillSelect(selector, items, defaultLabel) {
  const sel = $(selector);
  if (!sel) return;
  sel.innerHTML = '<option value="">' + defaultLabel + '</option>';
  (items || []).forEach(x => {
    const o = document.createElement('option');
    o.value = x.value;
    o.textContent = x.value + ' (' + Number(x.count).toLocaleString('fr-FR') + ')';
    sel.appendChild(o);
  });
}

/* ─── Companies ─────────────────────────────────────────────── */

async function loadCompanies() {
  currentSearch = $('#search').value.trim();
  currentFilters = {
    status: $('#filter-status') ? $('#filter-status').value : '',
    city: $('#filter-city') ? $('#filter-city').value : '',
    sector: $('#filter-sector') ? $('#filter-sector').value : '',
    number_type: $('#filter-number-type') ? $('#filter-number-type').value : '',
  };
  currentPage = 0;
  await fetchCompaniesPage(0);
}

async function fetchCompaniesPage(page) {
  const list = $('#companies-list');
  list.innerHTML = '<div class="loader"><div class="spinner"></div><span>Chargement…</span></div>';

  const offset = page * PAGE_SIZE;
  const params = new URLSearchParams({
    search: currentSearch,
    sector: currentFilters.sector,
    status: currentFilters.status,
    city: currentFilters.city,
    number_type: currentFilters.number_type,
    limit: PAGE_SIZE,
    offset: offset,
  });

  try {
    const r = await fetch('/api/companies?' + params.toString());
    const d = await r.json();
    if (!d.success) {
      list.innerHTML = emptyState('Erreur de chargement', 'Réessayez dans un instant.');
      return;
    }
    allCompaniesCache = d.data;
    renderCompanies(d.data);
    renderPagination(d.total);
    $('#result-count').textContent = d.total.toLocaleString('fr-FR') +
      ' société' + (d.total > 1 ? 's' : '');
  } catch (e) {
    list.innerHTML = emptyState('Erreur réseau', 'Vérifiez votre connexion.');
  }
}

function renderCompanies(companies) {
  const list = $('#companies-list');

  if (!companies.length) {
    list.innerHTML = emptyState(
      'Aucun résultat',
      'Essayez d\'élargir vos filtres ou de modifier votre recherche.'
    );
    return;
  }

  list.innerHTML = companies.map(c => {
    const city = (c.address_en || c.address_he || '').split(',').pop().trim();

    // Status badge
    const isActive = (c.status_en || '').toLowerCase() === 'active' ||
                     (c.status_en || '').toLowerCase() === 'active company';
    const statusClass = isActive ? 'badge-status' : 'badge-status inactive';

    // Sector
    const sectorText = c.sector || '—';
    const sectorClass = c.sector ? 'company-sector' : 'company-sector empty';

    // Badges supplémentaires
    const badges = [];
    if (c.cluster_ids && c.cluster_ids.length) {
      badges.push('<span class="badge badge-cluster">' +
        '<svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M9 12h6M12 9v6"/><circle cx="12" cy="12" r="9"/></svg>' +
        c.cluster_ids.length + '</span>');
    }
    if (c.risk_flags && c.risk_flags.length) {
      badges.push('<span class="badge badge-risk">' + c.risk_flags.length + ' alerte' +
        (c.risk_flags.length > 1 ? 's' : '') + '</span>');
    }

    return '<div class="company-row" onclick="showCompany(\'' + c.company_number + '\')">' +
      '<div class="company-main">' +
        '<div class="company-name">' + escapeHTML(c.name_en || c.name_he || 'Sans nom') + '</div>' +
        (c.name_en && c.name_he ? '<div class="company-name-he">' + escapeHTML(c.name_he) + '</div>' : '') +
        '<div class="company-number">' + escapeHTML(c.company_number) + '</div>' +
      '</div>' +
      '<div class="' + sectorClass + '">' + escapeHTML(sectorText) + '</div>' +
      '<div class="company-city">' + escapeHTML(city || '—') + '</div>' +
      '<div class="company-badges">' +
        (c.status_en ? '<span class="badge ' + statusClass + '">' + escapeHTML(c.status_en) + '</span>' : '') +
        badges.join('') +
      '</div>' +
    '</div>';
  }).join('');
}

function emptyState(title, desc) {
  return '<div class="empty-state">' +
    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><circle cx="11" cy="11" r="7"/><path d="M21 21l-4.35-4.35"/></svg>' +
    '<div class="empty-state-title">' + escapeHTML(title) + '</div>' +
    '<div class="empty-state-desc">' + escapeHTML(desc) + '</div>' +
  '</div>';
}

/* ─── Pagination ────────────────────────────────────────────── */

function renderPagination(total) {
  const tp = Math.ceil(total / PAGE_SIZE);
  const c = $('#pagination');
  if (tp <= 1) { c.innerHTML = ''; return; }

  const maxShow = 9;
  let start = Math.max(0, currentPage - Math.floor(maxShow / 2));
  let end = Math.min(tp, start + maxShow);
  if (end - start < maxShow) start = Math.max(0, end - maxShow);

  let h = '';
  if (start > 0) {
    h += '<button class="page-btn" onclick="goToPage(0)">1</button>';
    if (start > 1) h += '<span class="page-btn" style="cursor:default">…</span>';
  }

  for (let i = start; i < end; i++) {
    h += '<button class="page-btn' + (i === currentPage ? ' active' : '') +
         '" onclick="goToPage(' + i + ')">' + (i + 1) + '</button>';
  }

  if (end < tp) {
    if (end < tp - 1) h += '<span class="page-btn" style="cursor:default">…</span>';
    h += '<button class="page-btn" onclick="goToPage(' + (tp - 1) + ')">' + tp + '</button>';
  }

  c.innerHTML = h;
}

async function goToPage(page) {
  currentPage = page;
  await fetchCompaniesPage(page);
  document.querySelector('.content').scrollTop = 0;
}

function resetFilters() {
  ['#filter-status', '#filter-city', '#filter-sector', '#filter-number-type'].forEach(s => {
    const el = $(s);
    if (el) el.value = '';
  });
  $('#search').value = '';
  loadCompanies();
}

/* ─── Modal ─────────────────────────────────────────────────── */

async function showCompany(num) {
  const modal = $('#modal');
  $('#modal-content').innerHTML = '<div class="loader"><div class="spinner"></div><span>Chargement…</span></div>';
  modal.classList.remove('hidden');

  try {
    const r = await fetch('/api/company/' + num);
    const d = await r.json();
    if (!d.success) {
      $('#modal-content').innerHTML = emptyState('Société introuvable', '');
      return;
    }
    const c = d.data;

    let html = '<div class="modal-header">' +
      '<div>' +
        '<div class="modal-title">' + escapeHTML(c.name_en || c.name_he || 'Sans nom') + '</div>' +
        (c.name_he ? '<div class="modal-subtitle">' + escapeHTML(c.name_he) + '</div>' : '') +
      '</div>' +
      '<button class="modal-close" onclick="closeModal()" aria-label="Fermer">' +
        '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M18 6L6 18M6 6l12 12"/></svg>' +
      '</button>' +
    '</div>';

    html += '<div class="modal-grid">' +
      field('Numéro de société', c.company_number, 'mono') +
      field('Statut', c.status_en || '—') +
      field('Secteur', c.sector || '—', 'accent') +
      field('Type', c.type_en || '—') +
      field('Adresse', c.address_en || c.address_he || '—', '', true) +
    '</div>';

    if (c.context) {
      html += '<div class="modal-section">' +
        '<p style="color: var(--text-2); font-size: 13.5px; line-height: 1.6; font-style: italic">' +
          escapeHTML(c.context) +
        '</p>' +
      '</div>';
    }

    if (c.risk_flags && c.risk_flags.length) {
      html += '<div class="modal-section">' +
        '<div class="modal-section-title">Alertes</div>' +
        c.risk_flags.map(f => '<div class="risk-item">' + escapeHTML(f) + '</div>').join('') +
      '</div>';
    }

    if (c.clusters && c.clusters.length) {
      html += '<div class="modal-section">' +
        '<div class="modal-section-title">Groupes détectés (' + c.clusters.length + ')</div>' +
        c.clusters.map(cl => '<div class="risk-item" style="background: var(--accent-soft); border-color: var(--accent-border); color: var(--accent)">' +
          escapeHTML(cl.cluster_type) + ' · ' + escapeHTML(cl.cluster_key) +
        '</div>').join('') +
      '</div>';
    }

    if (c.related_companies && c.related_companies.length) {
      html += '<div class="modal-section">' +
        '<div class="modal-section-title">Sociétés liées (' + c.related_companies.length + ')</div>' +
        c.related_companies.map(r =>
          '<div class="related-item" onclick="closeModal(); showCompany(\'' + r.company_number + '\')">' +
            '<span class="related-item-name">' + escapeHTML(r.name_en || r.name_he) + '</span>' +
            '<span class="related-item-sector">' + escapeHTML(r.sector || '') + '</span>' +
          '</div>'
        ).join('') +
      '</div>';
    }

    $('#modal-content').innerHTML = html;
  } catch (e) {
    $('#modal-content').innerHTML = emptyState('Erreur de chargement', '');
  }
}

function field(label, value, className = '', full = false) {
  return '<div class="modal-field' + (full ? ' full' : '') + '">' +
    '<div class="modal-field-label">' + escapeHTML(label) + '</div>' +
    '<div class="modal-field-value ' + className + '">' + escapeHTML(value) + '</div>' +
  '</div>';
}

function closeModal() { $('#modal').classList.add('hidden'); }

document.addEventListener('keydown', e => {
  if (e.key === 'Escape') closeModal();
});

/* ─── Clusters ──────────────────────────────────────────────── */

async function loadClusters() {
  const c = $('#clusters-list');
  c.innerHTML = '<div class="loader"><div class="spinner"></div><span>Chargement des groupes…</span></div>';

  try {
    const r = await fetch('/api/clusters');
    const d = await r.json();

    if (!d.success || !d.data.length) {
      c.innerHTML = emptyState('Aucun groupe détecté', 'Les clusters sont détectés automatiquement lors de l\'import.');
      return;
    }

    c.innerHTML = d.data.map(cl => {
      const conf = Math.round((cl.confidence || 0) * 100);
      const membersHtml = (cl.members || []).map(m =>
        '<div class="cluster-member" onclick="showCompany(\'' + m.company_number + '\')">' +
          '<span class="cluster-member-name">' + escapeHTML(m.name_en || m.name_he) + '</span>' +
          '<span class="cluster-member-sector">' + escapeHTML(m.sector || '') + '</span>' +
        '</div>'
      ).join('');

      return '<div class="cluster-card">' +
        '<div class="cluster-header">' +
          '<span class="cluster-type">' + escapeHTML(cl.cluster_type) + '</span>' +
          '<span class="cluster-size">' + cl.size + '</span>' +
        '</div>' +
        '<div class="cluster-key">' + escapeHTML(cl.cluster_key) + '</div>' +
        '<div class="confidence-row">' +
          '<div class="confidence-track"><div class="confidence-fill" style="width:' + conf + '%"></div></div>' +
          '<span class="confidence-label">' + conf + '%</span>' +
        '</div>' +
        '<div class="cluster-members">' + membersHtml + '</div>' +
      '</div>';
    }).join('');
  } catch (e) {
    c.innerHTML = emptyState('Erreur réseau', '');
  }
}

/* ─── Stats ─────────────────────────────────────────────────── */

async function loadStats() {
  const c = $('#stats-content');
  c.innerHTML = '<div class="loader"><div class="spinner"></div><span>Chargement…</span></div>';

  try {
    const r = await fetch('/api/stats');
    const d = await r.json();
    if (!d.success) { c.innerHTML = emptyState('Erreur', ''); return; }
    const s = d.data;
    const maxCount = Math.max.apply(null, (s.sectors || []).map(x => x.count).concat([1]));

    let html = '<div class="stats-grid">' +
      '<div class="stat-card"><div class="stat-card-label">Sociétés</div><div class="stat-card-value">' + Number(s.total_companies).toLocaleString('fr-FR') + '</div></div>' +
      '<div class="stat-card"><div class="stat-card-label">Groupes détectés</div><div class="stat-card-value accent">' + Number(s.total_clusters).toLocaleString('fr-FR') + '</div></div>' +
    '</div>';

    if (s.sectors && s.sectors.length) {
      html += '<div class="sectors-panel"><h3>Répartition par secteur</h3>';
      s.sectors.forEach(sec => {
        const pct = Math.round((sec.count / maxCount) * 100);
        html += '<div class="sector-row">' +
          '<span class="sector-name">' + escapeHTML(sec.sector) + '</span>' +
          '<div class="sector-bar"><div class="sector-bar-fill" style="width:' + pct + '%"></div></div>' +
          '<span class="sector-count">' + Number(sec.count).toLocaleString('fr-FR') + '</span>' +
        '</div>';
      });
      html += '</div>';
    } else {
      html += '<div class="sectors-panel"><h3>Répartition par secteur</h3>' +
        '<p style="color: var(--text-3); font-size: 13px">Aucune société enrichie pour l\'instant. Cliquez sur une société pour lancer son enrichissement.</p></div>';
    }

    c.innerHTML = html;
  } catch (e) {
    c.innerHTML = emptyState('Erreur réseau', '');
  }
}

/* ─── API ───────────────────────────────────────────────────── */

async function loadApi() {
  const c = $('#api-content');
  if (!me) { c.innerHTML = emptyState('Non connecté', ''); return; }

  const baseUrl = window.location.origin;
  const endpoints = [
    { m: 'GET', p: '/api/companies?search=&status=&city=&limit=50', d: 'Rechercher des sociétés' },
    { m: 'GET', p: '/api/company/{number}', d: 'Détail d\'une société' },
    { m: 'GET', p: '/api/clusters', d: 'Groupes détectés' },
    { m: 'GET', p: '/api/stats', d: 'Statistiques globales' },
  ];

  let html = '<div class="api-panel">';

  html += '<div class="api-section">' +
    '<h3>Votre clé API</h3>' +
    '<p>Utilisez cette clé dans le header <code style="font-family: monospace; background: var(--surface-3); padding: 2px 6px; border-radius: 4px">X-API-Key</code> pour authentifier vos requêtes.</p>' +
    '<div class="api-key-box">' +
      '<code class="api-key-value">' + escapeHTML(me.api_key || '—') + '</code>' +
      '<button class="btn btn-ghost" onclick="copyKey()">' +
        '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15V5a2 2 0 012-2h10"/></svg>' +
        'Copier' +
      '</button>' +
    '</div>' +
  '</div>';

  html += '<div class="api-section">' +
    '<h3>Endpoints</h3>' +
    endpoints.map(e =>
      '<div class="endpoint">' +
        '<span class="endpoint-method">' + e.m + '</span>' +
        '<span class="endpoint-path">' + escapeHTML(e.p) + '</span>' +
        '<span class="endpoint-desc">' + escapeHTML(e.d) + '</span>' +
      '</div>'
    ).join('') +
  '</div>';

  html += '<div class="api-section">' +
    '<h3>Exemple cURL</h3>' +
    '<pre class="code-block">curl -H "X-API-Key: ' + escapeHTML(me.api_key || '') + '" \\\n     "' + baseUrl + '/api/companies?search=tech&limit=10"</pre>' +
  '</div>';

  html += '<div class="api-section">' +
    '<h3>Votre consommation</h3>' +
    '<div class="stat-card" style="margin-top: 8px">' +
      '<div class="stat-card-label">Requêtes aujourd\'hui</div>' +
      '<div class="stat-card-value">' + Number(me.usage_today || 0).toLocaleString('fr-FR') + '</div>' +
    '</div>' +
  '</div>';

  html += '</div>';
  c.innerHTML = html;
}

function copyKey() {
  if (!me || !me.api_key) return;
  navigator.clipboard.writeText(me.api_key).then(() => toast('Clé copiée', 'success'));
}

/* ─── Exports ───────────────────────────────────────────────── */

$$('[data-export]').forEach(btn => {
  btn.addEventListener('click', () => {
    const format = btn.dataset.export;
    const ids = allCompaniesCache.map(c => c.company_number).join(',');
    const params = ids ? '?ids=' + encodeURIComponent(ids) : '';
    window.location.href = '/api/export/' + format + params;
    toast('Génération du fichier ' + format.toUpperCase() + '…', 'info');
  });
});

/* ─── Search debounce ───────────────────────────────────────── */

let debounceTimer;
$('#search').addEventListener('input', () => {
  clearTimeout(debounceTimer);
  debounceTimer = setTimeout(loadCompanies, 350);
});

/* ─── Start ─────────────────────────────────────────────────── */

init();