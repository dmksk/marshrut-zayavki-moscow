const el = id => document.getElementById(id);
const escapeHtml = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const statusNames = {accepted:'Принято',assigned:'Назначен исполнитель',done:'Выполнено'};
const initData = window.WebApp?.initData || '';
const localPreview = !initData && ['localhost','127.0.0.1'].includes(window.location.hostname);
let routeResult = null;
let createdTicket = null;
let startedAt = Date.now();

async function request(path, options={}) {
  const headers = {'Content-Type':'application/json',...(options.headers || {})};
  if (path.startsWith('/api/max/mini/')) {
    if (localPreview) headers['X-Mini-Preview'] = '1';
    else headers['X-Max-Init-Data'] = initData;
  }
  const response = await fetch(path, {...options, headers});
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || 'Ошибка запроса');
  return data;
}

function tell(text, good=false) {
  el('message').textContent = text;
  el('message').classList.toggle('good', good);
}

function answers() {
  const result = {};
  for (const [field,key] of [['location','location'],['danger','danger'],['territory','territory_owner'],['category','selected_category']]) {
    if (el(field).value) result[key] = el(field).value;
  }
  return result;
}

function formData() {
  return {house_id:el('house').value,text:el('description').value.trim(),answers:answers()};
}

function showRoute(result) {
  const card = result.route_card;
  if (!card) {
    const questions = (result.follow_up_questions || []).map(q => `<li>${escapeHtml(q)}</li>`).join('');
    el('route').innerHTML = `<span class="route-kicker">НУЖНО УТОЧНЕНИЕ</span><h2>Ещё один вопрос</h2><ul>${questions}</ul>`;
  } else {
    el('route').innerHTML = `<span class="route-kicker">МАРШРУТ ГОТОВ</span><h2>${escapeHtml(result.category_name)}</h2>
      ${result.immediate_action ? `<div class="route-warning">⚠ ${escapeHtml(result.immediate_action)}</div>` : ''}
      <div class="route-destination"><small>КУДА ОБРАЩАТЬСЯ</small><strong>${escapeHtml(card.recipient)}</strong></div>
      <div class="route-row"><i>↗</i><div><strong>Что делать сейчас</strong><br>${escapeHtml(card.what_now)}</div></div>
      <div class="route-row"><i>▣</i><div><strong>Что приложить</strong><br>${escapeHtml(card.attach.join(', '))}</div></div>
      <div class="route-row"><i>◷</i><div><strong>Когда ждать ответ</strong><br>${escapeHtml(card.response_expectation)}</div></div>`;
  }
  el('route').classList.remove('hidden');
  el('createButton').classList.toggle('hidden', !card);
  el('route').scrollIntoView({behavior:'smooth',block:'start'});
}

async function classify() {
  const payload = formData();
  if (payload.text.length < 2) return tell('Опишите проблему хотя бы двумя символами.');
  el('triageButton').disabled = true;
  tell('');
  try {
    routeResult = await request('/api/triage',{method:'POST',body:JSON.stringify(payload)});
    el('territoryField').classList.toggle('hidden', !(routeResult.category === 'yard' || el('location').value === 'двор'));
    el('categoryField').classList.toggle('hidden', !!routeResult.route_card);
    showRoute(routeResult);
    if (!routeResult.route_card) tell('Уточните данные выше и повторите проверку.');
  } catch (error) {tell(error.message);}
  finally {el('triageButton').disabled = false;}
}

function photoData(file) {
  return new Promise((resolve,reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result);
    reader.onerror = () => reject(new Error('Не удалось прочитать фото'));
    reader.readAsDataURL(file);
  });
}

async function createTicket() {
  if (!routeResult?.route_card) return;
  if (!initData && !localPreview) return tell('Для создания заявки откройте мини-приложение через бота MAX.');
  el('createButton').disabled = true;
  tell('');
  try {
    const payload = {...formData(),seconds_to_create:Math.round((Date.now()-startedAt)/1000)};
    const photo = el('photo').files[0];
    if (photo) {
      if (photo.size > 3 * 1024 * 1024) throw new Error('Фото должно быть не больше 3 МБ.');
      payload.photo_data_url = await photoData(photo);
    }
    createdTicket = await request('/api/max/mini/tickets',{method:'POST',body:JSON.stringify(payload)});
    el('created').innerHTML = `<strong>Заявка ${escapeHtml(createdTicket.id)} создана ✓</strong><small>Статус: принято. Дальше смотрите его во вкладке «Мои заявки» и в сообщениях бота.</small>`;
    el('created').classList.remove('hidden');
    el('createButton').classList.add('hidden');
    tell('Заявка сохранена в демо-системе.',true);
    await loadTickets();
  } catch (error) {tell(error.message);el('createButton').disabled = false;}
}

async function loadTickets() {
  if (!initData && !localPreview) {
    el('myTickets').textContent = 'Откройте мини-приложение из бота MAX, чтобы увидеть свои заявки.';
    return;
  }
  try {
    const tickets = await request('/api/max/mini/tickets');
    el('myTickets').innerHTML = tickets.length ? tickets.map(t => `<article class="ticket-card">
      <div class="ticket-card-head"><strong>${escapeHtml(t.id)}</strong><span class="status ${escapeHtml(t.status)}">${escapeHtml(statusNames[t.status] || t.status)}</span></div>
      <p>${escapeHtml(t.text)}</p><small>${escapeHtml(new Date(t.updated_at).toLocaleString('ru-RU'))}</small>
    </article>`).join('') : 'Пока заявок нет. Начните с описания проблемы.';
  } catch (error) {el('myTickets').textContent = error.message;}
}

async function init() {
  const connected = !!initData;
  el('connection').textContent = connected ? '✓ Открыто в MAX. Заявки будут привязаны к вашему аккаунту.' :
    localPreview ? 'Локальный предпросмотр: заявки доступны только на этом компьютере и не привязаны к MAX.' :
      'Откройте мини-приложение из бота MAX, чтобы создать заявку.';
  el('connection').classList.toggle('warning', !connected);
  try {
    const houses = await request('/api/houses');
    el('house').innerHTML = Object.entries(houses).map(([id,house]) => `<option value="${escapeHtml(id)}">${escapeHtml(house.name)}</option>`).join('');
  } catch (error) {tell('Не удалось загрузить дома: ' + error.message);}
  for (const tab of document.querySelectorAll('.tab')) tab.addEventListener('click', () => {
    document.querySelectorAll('.tab').forEach(node => node.classList.toggle('active',node === tab));
    el('newTab').classList.toggle('active',tab.dataset.tab === 'new');
    el('mineTab').classList.toggle('active',tab.dataset.tab === 'mine');
    if (tab.dataset.tab === 'mine') loadTickets();
  });
  for (const button of document.querySelectorAll('[data-example]')) button.addEventListener('click', () => {
    el('description').value = button.dataset.example;el('description').focus();
  });
  for (const id of ['house','description','location','danger','territory','category']) el(id).addEventListener('input', () => {
    routeResult = null;el('route').classList.add('hidden');el('createButton').classList.add('hidden');
  });
  el('triageButton').addEventListener('click',classify);
  el('createButton').addEventListener('click',createTicket);
  el('refreshButton').addEventListener('click',loadTickets);
  el('photo').addEventListener('change',() => {el('photoName').textContent = el('photo').files[0]?.name || '→';});
  if (connected || localPreview) loadTickets();
  setInterval(() => {if (el('mineTab').classList.contains('active')) loadTickets();},10000);
}
init();
