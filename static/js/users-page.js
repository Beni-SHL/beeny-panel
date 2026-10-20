(function(){
const panelPath = JSON.parse(document.getElementById("users-page-data").textContent).panelPath;
let PAGE_SIZE = 15;
let serverTotal = 0;
let serverOverview = null;
let loadController;
const searchInput = document.getElementById('userSearch');
const protocolSelect = document.getElementById('protocolFilter');
const statusSelect = document.getElementById('statusFilter');
const sortSelect = document.getElementById('sortFilter');
const container = document.getElementById('usersListContainer');
const paginationContainer = document.getElementById('paginationContainer');
const statOnline = document.getElementById('statOnline');
const statTotal = document.getElementById('statTotal');
const statTraffic = document.getElementById('statTraffic');
const statWarn = document.getElementById('statWarn');
const configsPortalRoot = document.getElementById('configsPortalRoot');

let allUsersCache = [];
let currentPage = 1;

function showToast(message, type) {
  const stack = document.getElementById('toastStack');
  const el = document.createElement('div');
  el.className = `toast toast-${type === 'error' ? 'err' : 'ok'}`;
  el.innerHTML = `<i class="fa ${type === 'error' ? 'fa-circle-exclamation' : 'fa-circle-check'}"></i><span>${escapeText(message)}</span>`;
  stack.appendChild(el);
  setTimeout(() => {
    el.classList.add('leaving');
    setTimeout(() => el.remove(), 320);
  }, 3600);
}

(function checkNoticeParam(){
  const params = new URLSearchParams(window.location.search);
  const notice = params.get('notice');
  const noticeType = params.get('notice_type') || 'success';
  if (notice) {
    showToast(notice, noticeType);
    params.delete('notice'); params.delete('notice_type');
    const newUrl = window.location.pathname + (params.toString() ? `?${params}` : '');
    window.history.replaceState({}, '', newUrl);
  }
})();

function getFilterParams() {
  const p = new URLSearchParams();
  if(searchInput.value) p.append('q', searchInput.value);
  if(protocolSelect.value) p.append('protocol', protocolSelect.value);
  if(statusSelect.value) p.append('status', statusSelect.value);
  if(sortSelect.value) p.append('sort', sortSelect.value);
  p.append('page', currentPage); p.append('per_page', PAGE_SIZE);
  return p.toString();
}

async function loadUsers() {
  if(loadController)loadController.abort();
  const controller=new AbortController();loadController=controller;
  try {
    const res = await fetch(`${panelPath}/api/users/search?${getFilterParams()}`, {signal:controller.signal});
    if(!res.ok)throw new Error("Request failed");
    const data = await res.json();
    if(controller !== loadController)return;
    serverTotal=data.pagination?.total || 0;
    serverOverview=data.overview;
    let users = data.users || [];
    allUsersCache = users;
    renderPage();
  } catch(e) {
    if(e.name === "AbortError")return;
    container.innerHTML = `<div style="text-align:center; padding:40px; color:rgba(255,255,255,0.4);"><i class="fa fa-triangle-exclamation" style="font-size:32px;"></i><p>${window.adminT('Error loading users')}</p></div>`;
    paginationContainer.innerHTML = '';
  }
}

function renderPage() {
  const total = serverTotal;
  updateStats(allUsersCache, total);

  const totalPages = Math.ceil(total / PAGE_SIZE) || 1;
  if (currentPage > totalPages) currentPage = totalPages;

  const start = (currentPage - 1) * PAGE_SIZE;
  const end = Math.min(start + PAGE_SIZE, total);
  const pageUsers = allUsersCache;

  if (!total) {
    container.innerHTML = `<div style="text-align:center; padding:40px; color:rgba(255,255,255,0.3);"><i class="fa fa-users" style="font-size:48px; opacity:0.2; margin-bottom:12px;"></i><p>${window.adminT('No users found.')}</p></div>`;
    paginationContainer.innerHTML = '';
    return;
  }

  renderUsers(pageUsers);
  renderPagination(totalPages, total);
}

function getFlag(countryCode) {
    const code=String(countryCode||'').toLowerCase();
    if(!/^[a-z]{2}$/.test(code))return '<i class="fa fa-server"></i>';
    return `<span data-country="${code}" class="country-flag"></span>`;
}
function escapeText(value){const el=document.createElement('span');el.textContent=String(value??'');return el.innerHTML.replace(/'/g,'&#39;').replace(/"/g,'&quot;');}

function compactDays(text) {
    if (text == null) return '—';
    const match = String(text).match(/-?\d+/);
    if (!match) return window.adminT(text);
    return `${match[0]} ${window.adminT('Days')}`;
}

function updateStats(users, total) {
  const online = users.filter(u => u.online_status === 'online').length;
  const warn = users.filter(u => u.traffic_limit > 0 && u.traffic_percent > 80).length;
  const totalUsage = users.reduce((sum, u) => sum + (parseFloat(u.traffic_usage) || 0), 0);
  statOnline.textContent = serverOverview?.online ?? online;
  statTotal.textContent = total;
  statTraffic.textContent = `${(serverOverview?.usage ?? totalUsage).toFixed(1)} GB`;
  statWarn.textContent = serverOverview?.near_limit ?? warn;
}

function renderUsers(users) {
  closeConfigsMenu();
  container.innerHTML = users.map((user) => {
    user={...user, username:escapeText(user.username), status:escapeText(user.status), protocol:escapeText(user.protocol)};
    const isUnlimited = user.traffic_limit === 0;
    let trafficStr = isUnlimited ? `${user.traffic_usage} GB / ∞` : `${user.traffic_usage} / ${user.traffic_limit} GB`;
    let pctClass = isUnlimited ? 'pill-unlimited' : (user.traffic_percent > 80 ? 'pill-bad' : (user.traffic_percent > 60 ? 'pill-warn' : ''));

    let nodeFlagChips = '';
    const configLinks = [{ label: window.adminT('Smart Multi-Location'), flag: '<i class="fa fa-bolt" style="color:var(--orange)"></i>', href: `${panelPath}/users/download/${encodeURIComponent(user.username)}` }];

    if(user.nodes_list && user.nodes_list.length > 0) {
        user.nodes_list.forEach(n => {
            configLinks.push({ label: escapeText(n.name), flag: getFlag(n.country), href: `${panelPath}/users/download/${encodeURIComponent(user.username)}?node_id=${n.id}` });
            if(n.tunnel)configLinks.push({label:escapeText(n.name)+' · '+window.adminT('Via entry tunnel'),flag:getFlag('IR'),href:`${panelPath}/users/download/${encodeURIComponent(user.username)}?node_id=${n.id}&route=tunnel`});
            nodeFlagChips += `<span class="node-flag-chip">${getFlag(n.country)} ${escapeText(n.name)}</span>`;
        });
    } else {
        nodeFlagChips = `<span class="node-flag-chip node-flag-chip-empty"><i class="fa fa-ban"></i> ${window.adminT('No servers')}</span>`;
    }

    return `
      <div class="user-row" data-config-links='${JSON.stringify(configLinks).replace(/'/g, "&#39;").replace(/"/g, "&quot;")}'>
        <div class="user-header" onclick="toggleRow(this)">

          <span class="compact-state ${user.status === 'active' ? 'enabled' : ''}" title="Account status">${window.adminT(user.status)}</span>
          <span class="compact-online ${user.online_status === 'online' ? 'connected' : ''}">${window.adminT(user.online_status === 'online' ? 'Online' : 'Offline')}</span>
          <div class="avatar ${user.online_status === 'online' ? 'avatar-online' : ''}">${user.username.charAt(0).toUpperCase()}</div>
          <div class="user-name-block">
            <h3>${user.username}</h3>
            <div class="user-pills">
              <span class="pill ${pctClass}"><i class="fa fa-database"></i> ${trafficStr}</span>
              <span class="pill"><i class="fa fa-clock"></i> ${compactDays(user.days_left_text)}</span>
            </div>
          </div>
          <button class="expand-btn"><i class="fa fa-chevron-down"></i></button>
        </div>
        <div class="user-details">
          <div class="details-inner">
            <div class="details-grid">
              <div class="detail-card"><span>${window.adminT('Status')}</span><strong>${window.adminT(user.status)}</strong></div>
              <div class="detail-card"><span>${window.adminT('Protocol')}</span><strong>${user.protocol.toUpperCase()}</strong></div>
              <div class="detail-card"><span>${window.adminT('Devices')}</span><strong>${user.current_devices}/${user.max_devices}</strong></div>
              <div class="detail-card"><span>${window.adminT('Days Left')}</span><strong>${compactDays(user.days_left_text)}</strong></div>
            </div>
            <div class="nodes-section">
              <span class="nodes-section-label">${window.adminT('Allowed Servers')}</span>
              <div class="node-flags-row">${nodeFlagChips}</div>
            </div>
            <div class="traffic-section">
              <div class="traffic-label-row"><span>${window.adminT('Traffic Used')}</span><strong>${trafficStr} ${!isUnlimited ? `· ${user.traffic_percent}%` : ''}</strong></div>
              <div class="progress-track"><div class="progress-fill ${isUnlimited ? 'unlimited' : (user.traffic_percent > 80 ? 'warn' : '')}" style="width: ${isUnlimited ? 100 : Math.min(user.traffic_percent, 100)}%"></div></div>
            </div>
            <div class="action-row">
              <a href="${panelPath}/users/view/${user.id}" class="glass-btn" title="Profile" aria-label="Profile"><i class="fa fa-id-card"></i></a>
              <a href="${panelPath}/users/edit/${user.id}" class="glass-btn" title="Edit" aria-label="Edit"><i class="fa fa-pen"></i></a>

              <button type="button" class="glass-btn configs-trigger" title="Download config" aria-label="Download config" onclick="toggleConfigsMenu(this)" style="background: linear-gradient(135deg, rgba(96,165,250,0.2), rgba(96,165,250,0.05)); border-color:rgba(96,165,250,0.4); color:var(--blue);">
                <i class="fa fa-cloud-arrow-down"></i> <i class="fa fa-chevron-down" style="font-size:9px; margin-left:4px;"></i>
              </button>

              <a href="${panelPath}/users/reset_traffic/${user.id}" class="glass-btn warning" onclick="return confirm('Reset traffic for this user?')" title="Reset traffic"><i class="fa fa-rotate-left"></i></a>
              <a href="${panelPath}/users/delete/${user.id}" class="glass-btn danger" onclick="return confirm('Delete user?')" title="Delete user"><i class="fa fa-trash"></i></a>
            </div>
          </div>
        </div>
      </div>
    `;
  }).join('');
  if(window.BeenyFlags)window.BeenyFlags.render(container);
}

function renderPagination(totalPages, total) {
  if (totalPages <= 1) {
    paginationContainer.innerHTML = '';
    return;
  }

  let html = '';
  const startPage = Math.max(1, currentPage - 2);
  const endPage = Math.min(totalPages, currentPage + 2);

  // Previous
  html += `<button class="pagination-btn" onclick="goToPage(${currentPage - 1})" ${currentPage <= 1 ? 'disabled' : ''}><i class="fa fa-chevron-left"></i></button>`;

  // First page
  if (startPage > 1) {
    html += `<button class="pagination-btn" onclick="goToPage(1)">1</button>`;
    if (startPage > 2) html += `<span class="pagination-ellipsis">…</span>`;
  }

  // Pages
  for (let i = startPage; i <= endPage; i++) {
    html += `<button class="pagination-btn ${i === currentPage ? 'active' : ''}" onclick="goToPage(${i})">${i}</button>`;
  }

  // Last page
  if (endPage < totalPages) {
    if (endPage < totalPages - 1) html += `<span class="pagination-ellipsis">…</span>`;
    html += `<button class="pagination-btn" onclick="goToPage(${totalPages})">${totalPages}</button>`;
  }

  // Next
  html += `<button class="pagination-btn" onclick="goToPage(${currentPage + 1})" ${currentPage >= totalPages ? 'disabled' : ''}><i class="fa fa-chevron-right"></i></button>`;

  // Info
  const start = (currentPage - 1) * PAGE_SIZE + 1;
  const end = Math.min(currentPage * PAGE_SIZE, total);
  html += `<span class="pagination-info">${start}–${end} of ${total}</span>`;

  paginationContainer.innerHTML = html;
}

window.goToPage = function(page) {
  const totalPages = Math.ceil(serverTotal / PAGE_SIZE) || 1;
  if (page < 1 || page > totalPages || page === currentPage) return;
  currentPage = page;
  loadUsers();
  document.querySelector('.users-page').scrollIntoView({ behavior: 'smooth', block: 'start' });
};

window.toggleRow = function(header) {
  header.closest('.user-row').classList.toggle('open');
};

let activeConfigsMenu = null;
let activeConfigsTrigger = null;

function closeConfigsMenu() {
  if (activeConfigsMenu) {
    activeConfigsMenu.classList.remove('show');
    const toRemove = activeConfigsMenu;
    setTimeout(() => toRemove.remove(), 160);
  }
  if (activeConfigsTrigger) activeConfigsTrigger.setAttribute('aria-expanded', 'false');
  activeConfigsMenu = null;
  activeConfigsTrigger = null;
  window.removeEventListener('scroll', positionActiveMenu, true);
  window.removeEventListener('resize', positionActiveMenu);
}

function positionActiveMenu() {
  if (!activeConfigsMenu || !activeConfigsTrigger) return;
  const rect = activeConfigsTrigger.getBoundingClientRect();
  const menu = activeConfigsMenu;
  const menuRect = menu.getBoundingClientRect();
  const vh = window.innerHeight, vw = window.innerWidth;
  let top = rect.bottom + 8;
  let openUp = false;
  if (top + menuRect.height > vh - 12 && rect.top - menuRect.height - 8 > 12) {
    top = rect.top - menuRect.height - 8;
    openUp = true;
  }
  menu.classList.toggle('menu-up', openUp);
  let left = rect.left;
  const menuW = Math.max(menuRect.width, 220);
  if (left + menuW > vw - 12) left = Math.max(12, vw - menuW - 12);
  if (left < 12) left = 12;
  menu.style.top = `${Math.max(8, top)}px`;
  menu.style.left = `${left}px`;
}

window.toggleConfigsMenu = function(triggerBtn) {
  if (activeConfigsTrigger === triggerBtn) { closeConfigsMenu(); return; }
  closeConfigsMenu();
  const row = triggerBtn.closest('.user-row');
  let links = [];
  try { links = JSON.parse(row.dataset.configLinks.replace(/&#39;/g, "'").replace(/&quot;/g, '"')); } catch(e) { links = []; }
  const menu = document.createElement('div');
  menu.className = 'configs-menu';
  let html = `<div class="configs-menu-label">${window.adminT('Download Config')}</div>`;
  links.forEach((l, i) => {
    if (i === 1 && links.length > 1) html += `<div class="configs-menu-divider"></div>`;
    html += `<a class="configs-menu-item" href="${l.href}" download>${l.flag} <span>${l.label}</span><i class="fa fa-arrow-down dl-icon"></i></a>`;
  });
  menu.innerHTML = html;
  configsPortalRoot.appendChild(menu);
  if(window.BeenyFlags)window.BeenyFlags.render(menu);
  activeConfigsMenu = menu;
  activeConfigsTrigger = triggerBtn;
  triggerBtn.setAttribute('aria-expanded', 'true');
  positionActiveMenu();
  requestAnimationFrame(() => menu.classList.add('show'));
  window.addEventListener('scroll', positionActiveMenu, true);
  window.addEventListener('resize', positionActiveMenu);
};

document.addEventListener('click', (e) => {
  if (!activeConfigsMenu) return;
  if (e.target.closest('.configs-menu') || e.target.closest('.configs-trigger')) return;
  closeConfigsMenu();
});
document.addEventListener('keydown', (e) => { if (e.key === 'Escape') closeConfigsMenu(); });

[searchInput, protocolSelect, statusSelect, sortSelect].forEach(el => el.addEventListener('change',()=>{currentPage=1;loadUsers()}));
let searchDebounce;searchInput.addEventListener('input',()=>{clearTimeout(searchDebounce);searchDebounce=setTimeout(()=>{currentPage=1;loadUsers()},220)});
searchInput.addEventListener('keyup', (e) => { if(e.key === 'Enter'){currentPage=1;loadUsers();} });

const scope=document.querySelector('.users-page');
function setView(view){
 view=view==='compact'?'compact':'original';scope.dataset.view=view;
 PAGE_SIZE=view==='compact'?100:15;currentPage=1;
 scope.querySelectorAll('[data-user-view]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.userView===view)));
 try{localStorage.setItem('beeny-users-display',view)}catch(e){}
 loadUsers();
}
scope.querySelectorAll('[data-user-view]').forEach(b=>b.addEventListener('click',()=>setView(b.dataset.userView)));
const initializeUsers=()=>{let view='original';try{view=localStorage.getItem('beeny-users-display')||view}catch(e){}setView(view)};if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',initializeUsers,{once:true});else initializeUsers();
})();
