const $ = id => document.getElementById(id);
const esc = value => String(value ?? '').replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
const statusText = {accepted:'принято',assigned:'назначен исполнитель',done:'выполнено'};
const nextStatus = {accepted:'assigned',assigned:'done'};
let currentTriage = null;
let currentTicket = null;
let startedAt = Date.now();

async function api(path, options={}) {
  const response = await fetch(path, {headers:{'Content-Type':'application/json',...(options.headers||{})},...options});
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || 'Ошибка запроса');
  return data;
}

function message(text, good=false) {
  const node=$('formMessage'); node.textContent=text; node.style.color=good?'#267d5e':'#ba694b';
}

function answers() {
  const a={};
  if ($('location').value) a.location=$('location').value;
  if ($('danger').value) a.danger=$('danger').value;
  if ($('territory').value) a.territory_owner=$('territory').value;
  if ($('manualCategory').value) a.selected_category=$('manualCategory').value;
  return a;
}

function payload() {return {house_id:$('house').value,text:$('description').value.trim(),answers:answers()};}

function routeHtml(result) {
  const card=result.route_card;
  if (!card) {
    const hints=(result.follow_up_questions||[]).map(x=>`<li>${esc(x)}</li>`).join('');
    return `<div class="empty-route"><span class="route-art">?</span><strong>Нужно уточнение</strong><p>Ответьте на вопрос слева и нажмите «Определить маршрут» ещё раз.</p><ul style="text-align:left;font-size:10px;color:#6d8490">${hints}</ul></div>`;
  }
  return `<div class="route-content">
    <span class="category-badge">${esc(result.category_name)}</span>
    ${result.immediate_action?`<div class="route-warning">⚠ ${esc(result.immediate_action)}</div>`:''}
    <div class="route-destination"><small>КУДА ОБРАЩАТЬСЯ</small><strong>${esc(card.recipient)}</strong></div>
    <div class="route-detail"><span>↗</span><div><b>Что делать сейчас</b><br>${esc(card.what_now)}</div></div>
    <div class="route-detail"><span>▣</span><div><b>Что приложить</b><br>${esc(card.attach.join(', '))}</div></div>
    <div class="route-detail"><span>◷</span><div><b>Когда ждать ответ</b><br>${esc(card.response_expectation)}</div></div>
    <div class="route-note">Тип определён моделью. Итоговый адресат зависит от дома, границ территории и фактической ситуации.</div></div>`;
}

async function runTriage() {
  message('');
  if (payload().text.length<2) return message('Опишите проблему хотя бы двумя символами.');
  try {
    currentTriage=await api('/api/triage',{method:'POST',body:JSON.stringify(payload())});
    $('routeContent').className=''; $('routeContent').innerHTML=routeHtml(currentTriage);
    const yard=currentTriage.category==='yard'||$('location').value==='двор';
    $('territoryGroup').classList.toggle('hidden',!yard);
    $('manualGroup').classList.toggle('hidden',!!currentTriage.route_card);
    $('createBtn').disabled=!currentTriage.route_card;
    if (!currentTriage.route_card) message('Уточните данные и повторите проверку.');
    else message('Маршрут готов. Можно создать демо-заявку.',true);
  } catch(error) {message(error.message);}
}

function fileDataURL(file) {
  return new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(reader.result);reader.onerror=()=>reject(new Error('Не удалось прочитать фото'));reader.readAsDataURL(file);});
}

async function createTicket() {
  if (!currentTriage?.route_card) return;
  try {
    const request={...payload(),seconds_to_create:Math.round((Date.now()-startedAt)/1000)};
    const photo=$('photo').files[0];
    if (photo) {
      if (photo.size>3*1024*1024) throw new Error('Фото должно быть не больше 3 МБ.');
      request.photo_data_url=await fileDataURL(photo);
    }
    currentTicket=await api('/api/tickets',{method:'POST',body:JSON.stringify(request)});
    $('createBtn').disabled=true;
    renderTicket(currentTicket);
    message(`Заявка ${currentTicket.id} создана.`,true);
    loadDashboard();
  } catch(error) {message(error.message);}
}

function renderTicket(ticket) {
  const order=['accepted','assigned','done']; const current=order.indexOf(ticket.status);
  const steps=order.map((status,index)=>`<div class="status-step ${index<current?'done':''} ${index===current?'current':''}"><i></i>${esc(statusText[status])}</div>`).join('');
  $('ticketContent').innerHTML=`<div class="ticket-id">${esc(ticket.id)}</div><div class="status-list">${steps}</div><div class="ticket-meta">Обновлено: ${esc(new Date(ticket.updated_at).toLocaleString('ru-RU'))}${ticket.photo_path?' · Фото приложено':''}</div>`;
}

async function loadDashboard() {
  try {
    const [summary,tickets]=await Promise.all([api('/api/summary'),api('/api/tickets')]);
    $('statTotal').textContent=summary.total; $('statAccepted').textContent=summary.accepted;
    $('statAssigned').textContent=summary.assigned; $('statDone').textContent=summary.done;
    $('ticketList').innerHTML=tickets.length?tickets.map(ticket=>`<div class="ticket-row"><div><div class="ticket-row-title">${esc(ticket.id)} · ${esc(ticket.route.recipient_kind)}</div><div class="ticket-row-text">${esc(ticket.text)}</div><div class="ticket-row-meta">${esc(ticket.house_id)} · ${esc(new Date(ticket.created_at).toLocaleString('ru-RU'))}</div></div><div class="ticket-row-right"><span class="status-badge ${esc(ticket.status)}">${esc(statusText[ticket.status])}</span>${nextStatus[ticket.status]?`<button class="advance-btn" data-id="${esc(ticket.id)}" data-next="${nextStatus[ticket.status]}">Следующий статус →</button>`:''}</div></div>`).join(''):'<div class="list-empty">Пока заявок нет. Создайте первую во вкладке «Жителю».</div>';
  } catch(error) {$('ticketList').textContent=error.message;}
}

async function advance(id,status) {
  const key=$('adminKey').value;
  if (!key) return alert('Введите APP_ADMIN_KEY из терминала запуска.');
  try {
    const result=await api(`/api/tickets/${id}/status`,{method:'PATCH',headers:{'X-Admin-Key':key},body:JSON.stringify({status})});
    if (currentTicket?.id===id) {currentTicket=result.ticket;renderTicket(currentTicket);}
    await loadDashboard();
  } catch(error) {alert(error.message);}
}

function bubble(text,kind) {
  const node=document.createElement('div');node.className=`bubble ${kind}`;node.textContent=text;
  $('chatMessages').append(node);$('chatMessages').scrollTop=$('chatMessages').scrollHeight;
}

async function sendChat() {
  const input=$('chatInput');const text=input.value.trim();if (!text) return;
  bubble(text,'user');input.value='';
  try {const out=await api('/api/demo/max',{method:'POST',body:JSON.stringify({user_id:1001,text})});bubble(out.reply||'Сообщение принято.','bot');loadDashboard();}
  catch(error){bubble('Ошибка: '+error.message,'bot');}
}

async function init() {
  try {
    const houses=await api('/api/houses');
    $('house').innerHTML=Object.entries(houses).map(([id,h])=>`<option value="${esc(id)}">${esc(h.name)}</option>`).join('');
  } catch(error) {message('Не удалось загрузить дома: '+error.message);}
  document.querySelectorAll('.nav-item').forEach(button=>button.addEventListener('click',()=>{
    document.querySelectorAll('.nav-item').forEach(x=>x.classList.toggle('active',x===button));
    document.querySelectorAll('.view').forEach(x=>x.classList.toggle('active',x.id===`${button.dataset.view}View`));
    $('pageTitle').textContent={resident:'Проблема дома? Разберёмся.',dispatcher:'Кабинет диспетчера.',max:'Диалог в MAX.'}[button.dataset.view];
    if(button.dataset.view==='dispatcher')loadDashboard();
  }));
  document.querySelectorAll('.example').forEach(button=>button.addEventListener('click',()=>{$('description').value=button.dataset.example;$('description').focus();}));
  $('triageBtn').addEventListener('click',runTriage);
  $('createBtn').addEventListener('click',createTicket);
  $('refreshBtn').addEventListener('click',loadDashboard);
  $('ticketList').addEventListener('click',event=>{const btn=event.target.closest('.advance-btn');if(btn)advance(btn.dataset.id,btn.dataset.next);});
  $('photo').addEventListener('change',()=>{$('fileName').textContent=$('photo').files[0]?.name||'Не выбрано';});
  $('chatSend').addEventListener('click',sendChat);
  $('chatInput').addEventListener('keydown',event=>{if(event.key==='Enter')sendChat();});
  for(const id of ['description','house','location','danger','territory','manualCategory'])$(id).addEventListener('change',()=>{currentTriage=null;$('createBtn').disabled=true;});
  loadDashboard();
  setInterval(async()=>{if(currentTicket){try{const updated=await api(`/api/tickets/${currentTicket.id}`);if(updated.status!==currentTicket.status){currentTicket=updated;renderTicket(updated);}}catch{}}},4000);
}
init();
