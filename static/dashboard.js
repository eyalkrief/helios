const $=s=>document.querySelector(s),$$=s=>document.querySelectorAll(s);
let me=null,currentPage=0;const PAGE_SIZE=50;let currentSearch='',currentSector='';
function escapeHTML(s){if(s==null)return'';return String(s).replace(/[&<>'"]/g,t=>({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[t]))}
$$('.nav-item').forEach(b=>b.addEventListener('click',()=>{
$$('.nav-item').forEach(x=>x.classList.remove('active'));b.classList.add('active');
const v=b.dataset.view;$$('.view').forEach(x=>x.classList.remove('active'));
$('#view-'+v).classList.add('active');
if(v==='clusters')loadClusters();if(v==='stats')loadStats();if(v==='api')loadApi()}));
async function init(){try{const r=await fetch('/api/me');const d=await r.json();if(d.success)me=d.data;
const s=await fetch('/api/stats');const sd=await s.json();
if(sd.success){const sel=$('#sector-filter');sd.data.sectors.forEach(x=>{const o=document.createElement('option');o.value=x.sector;o.textContent=x.sector+' ('+x.count+')';sel.appendChild(o)})}}catch(e){}
loadCompanies()}
async function loadCompanies(){currentSearch=$('#search').value;currentSector=$('#sector-filter').value;currentPage=0;
const url='/api/companies?search='+encodeURIComponent(currentSearch)+'&sector='+encodeURIComponent(currentSector)+'&limit='+PAGE_SIZE+'&offset=0';
const r=await fetch(url);const d=await r.json();
if(d.success){renderCompanies(d.data);renderPagination(d.total);$('#result-count').textContent=d.total+' societes'}}
function renderCompanies(cs){const c=$('#companies-list');
if(!cs.length){c.innerHTML='<div style="text-align:center;padding:3rem;color:var(--text-dim)">Aucune societe</div>';return}
c.innerHTML=cs.map(x=>'<div class="company-row" onclick="showCompany(\'' + x.company_number + '\')"><div><div class="company-name">'+escapeHTML(x.name_en)+'</div><div class="company-name-he">'+escapeHTML(x.name_he)+'</div></div><div class="company-sector">'+escapeHTML(x.sector||'-')+'</div><div style="color:var(--text-dim);font-size:0.85rem">'+escapeHTML((x.address_en||'').split(',').pop().trim()||'-')+'</div><div></div></div>').join('')}
function renderPagination(t){const tp=Math.ceil(t/PAGE_SIZE);const c=$('#pagination');if(tp<=1){c.innerHTML='';return}
let h='';for(let i=0;i<Math.min(tp,10);i++)h+='<button onclick="goToPage('+i+')" class="'+(i===currentPage?'active':'')+'">'+(i+1)+'</button>';c.innerHTML=h}
async function goToPage(p){currentPage=p;
const url='/api/companies?search='+encodeURIComponent(currentSearch)+'&sector='+encodeURIComponent(currentSector)+'&limit='+PAGE_SIZE+'&offset='+(p*PAGE_SIZE);
const r=await fetch(url);const d=await r.json();if(d.success){renderCompanies(d.data);renderPagination(d.total)}}
async function showCompany(n){const r=await fetch('/api/company/'+n);const d=await r.json();if(!d.success)return;const c=d.data;
$('#modal-content').innerHTML='<div><button onclick="closeModal()" style="float:right;background:none;border:none;color:var(--text-dim);font-size:1.5rem;cursor:pointer">x</button><h2 style="font-family:Cinzel;color:var(--gold);margin-bottom:1rem">'+escapeHTML(c.name_en)+'</h2><p style="color:var(--text-dim);margin-bottom:1rem">'+escapeHTML(c.name_he)+'</p><p><strong>Secteur:</strong> '+escapeHTML(c.sector)+'</p><p><strong>Statut:</strong> '+escapeHTML(c.status_en)+'</p><p><strong>Adresse:</strong> '+escapeHTML(c.address_en)+'</p></div>';
$('#modal').classList.remove('hidden')}
function closeModal(){$('#modal').classList.add('hidden')}
$('#modal').addEventListener('click',e=>{if(e.target.id==='modal')closeModal()});
async function loadClusters(){const r=await fetch('/api/clusters');const d=await r.json();const c=$('#clusters-list');
if(!d.success||!d.data.length){c.innerHTML='<div style="text-align:center;padding:3rem;color:var(--text-dim)">Aucun cluster</div>';return}
c.innerHTML=d.data.map(cl=>'<div class="cluster-card"><span class="cluster-type">'+cl.cluster_type+'</span><div style="font-family:Cinzel;color:var(--gold);font-size:1.5rem;margin:0.5rem 0">'+escapeHTML(cl.cluster_key)+'</div><div style="font-size:0.8rem;color:var(--text-dim);margin-bottom:1rem">Confiance: '+Math.round(cl.confidence*100)+'% | '+cl.size+' societes</div><div>'+cl.members.map(m=>'<div class="cluster-member" onclick="showCompany(\'' + m.company_number + '\')">'+escapeHTML(m.name_en)+'</div>').join('')+'</div></div>').join('')}
async function loadStats(){const r=await fetch('/api/stats');const d=await r.json();if(!d.success)return;const s=d.data;
$('#stats-content').innerHTML='<div style="display:grid;grid-template-columns:1fr 1fr;gap:1.5rem;margin-bottom:2rem"><div style="background:var(--night-2);border:1px solid var(--border);border-radius:12px;padding:2rem"><div style="color:var(--text-dim)">Societes</div><div style="font-family:Cinzel;font-size:3rem;color:var(--text)">'+s.total_companies+'</div></div><div style="background:var(--night-2);border:1px solid var(--border);border-radius:12px;padding:2rem"><div style="color:var(--text-dim)">Clusters</div><div style="font-family:Cinzel;font-size:3rem;color:var(--gold)">'+s.total_clusters+'</div></div></div>'}
async function loadApi(){if(!me)return;
$('#api-content').innerHTML='<div><h2 style="font-family:Cinzel;color:var(--gold)">Votre cle API</h2><code style="display:block;background:var(--night-3);padding:1rem;border-radius:8px;margin:1rem 0;color:var(--gold);word-break:break-all">'+me.api_key+'</code><p style="color:var(--text-dim);font-size:0.9rem">Utilisez cette cle dans le header X-API-Key</p></div>'}
let debounce;$('#search').addEventListener('input',()=>{clearTimeout(debounce);debounce=setTimeout(loadCompanies,400)});
$('#sector-filter').addEventListener('change',loadCompanies);
init();
