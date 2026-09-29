const el = id => document.getElementById(id);
const escapeHtml = value => String(value ?? '').replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
const categoryNames = {leak:'Протечка',lift:'Лифт',heating:'Отопление и горячая вода',entrance_electricity:'Свет в общих зонах',trash:'Мусор',yard:'Двор'};
const statusNames = {accepted:'Принято',assigned:'Назначен исполнитель',done:'Выполнено'};
const initData = window.WebApp?.initData || '';
const localPreview = !initData && ['localhost','127.0.0.1'].includes(window.location.hostname);
const state = {session:'checking',tab:'new',screen:'wizard',step:0,revision:0,routeRevision:-1,route:null,
  categoryTouched:false,urgentFromModel:'',urgentTimer:null,urgentSeq:0,startedAt:Date.now(),ticketsSeq:0,lastStatuses:new Map()};

function setConnection(message, kind='') {
  el('connection').textContent = message;
  el('connection').className = `connection ${kind}`.trim();
}

async function request(path, options={}) {
  const headers = {...(options.headers || {})};
  if (options.body) headers['Content-Type'] = 'application/json';
  if (path.startsWith('/api/max/mini/')) {
    if (localPreview) headers['X-Mini-Preview'] = '1';
    else if (initData) headers['X-Max-Init-Data'] = initData;
  }
  let response;
  try { response = await fetch(path, {...options, headers}); }
  catch { throw new Error('Нет связи с сервером. Проверьте интернет и попробуйте ещё раз.'); }
  const raw = await response.text();
  let data;
  try { data = JSON.parse(raw); }
  catch { throw new Error('Сервис временно недоступен. Попробуйте ещё раз позже.'); }
  if (response.status === 401 && path.startsWith('/api/max/mini/')) {
    state.session = 'invalid';
    setConnection(data.error || 'Сессия MAX истекла. Откройте приложение снова.', 'warning');
  }
  if (!response.ok) throw new Error(data.error || 'Не удалось выполнить действие. Попробуйте ещё раз.');
  return data;
}

function showError(id, message) {
  const node = el(id);
  node.textContent = message;
  node.hidden = !message;
}

function selected(name) { return document.querySelector(`input[name="${name}"]:checked`)?.value || ''; }
function answers() {
  const result = {location:selected('location'),danger:selected('danger'),selected_category:el('category').value};
  if (result.selected_category === 'yard' && el('territory').value) result.territory_owner = el('territory').value;
  if (result.selected_category === 'trash' && el('trashContext').value) result.trash_context = el('trashContext').value;
  return result;
}
function formData() { return {house_id:el('house').value,text:el('description').value.trim(),answers:answers()}; }

function updateEmergency() {
  const message = state.urgentFromModel || (selected('danger') === 'да' ?
    'При непосредственной опасности отойдите от места происшествия и позвоните 112. Демо-заявка не вызывает помощь.' : '');
  el('emergencyText').textContent = message;
  el('emergency').hidden = !message;
}

function scheduleUrgency() {
  clearTimeout(state.urgentTimer);
  const seq = ++state.urgentSeq;
  state.urgentFromModel = '';
  updateEmergency();
  const text = el('description').value.trim();
  const house = el('house').value;
  if (text.length < 5) return;
  state.urgentTimer = setTimeout(async () => {
    try {
      const result = await request('/api/triage',{method:'POST',body:JSON.stringify({text,house_id:house || 'demo_1',answers:{danger:selected('danger')}})});
      if (seq !== state.urgentSeq || text !== el('description').value.trim() || house !== el('house').value) return;
      state.urgentFromModel = result.immediate_action || '';
      updateEmergency();
    } catch { /* Main route action reports network errors. */ }
  }, 450);
}

function invalidate({resetCategory=false}={}) {
  state.revision++;
  state.route = null;
  state.routeRevision = -1;
  showError('stepError','');
  showError('routeMessage','');
  if (resetCategory) {
    el('category').value = '';
    el('territory').value = '';
    el('trashContext').value = '';
    state.categoryTouched = false;
    el('categoryHint').textContent = 'Предложим категорию по вашему описанию.';
    updateCategoryFields();
  }
}

function updateCategoryFields() {
  const category = el('category').value;
  el('territoryField').hidden = category !== 'yard';
  el('trashField').hidden = category !== 'trash';
}

function focusHeading(id) {
  if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) el(id).scrollIntoView({block:'start'});
  else el(id).scrollIntoView({behavior:'smooth',block:'start'});
  el(id).focus({preventScroll:true});
}

function updateBackButton() {
  const button = window.WebApp?.BackButton;
  if (!button) return;
  const visible = (state.tab === 'new' && (state.screen !== 'wizard' || state.step > 0)) ||
    (state.tab === 'mine' && !el('ticketDetailScreen').hidden);
  if (visible) button.show?.(); else button.hide?.();
}

function setStep(index, focus=true) {
  state.step = index;
  document.querySelectorAll('.step').forEach((node,i) => { node.hidden = i !== index; });
  el('stepCount').textContent = `Шаг ${index+1} из 4`;
  el('stepTime').textContent = index === 3 ? 'Последний шаг' : 'Около минуты';
  el('progressBar').setAttribute('aria-valuenow', String(index+1));
  el('progressBar').firstElementChild.style.width = `${(index+1)*25}%`;
  el('wizardBack').hidden = index === 0;
  el('wizardNext').innerHTML = index === 3 ? 'Показать маршрут <span aria-hidden="true">→</span>' : 'Продолжить <span aria-hidden="true">→</span>';
  showError('stepError','');
  updateBackButton();
  if (focus) focusHeading(`stepTitle${index}`);
}

function fieldError(message, field) {
  showError('stepError', message);
  field?.focus();
  return false;
}

function validateStep(index) {
  if (index === 0) {
    if (!el('house').value) return fieldError('Выберите дом из списка.',el('house'));
    if (el('description').value.trim().length < 2) return fieldError('Опишите проблему хотя бы двумя символами.',el('description'));
    const photo = el('photo').files[0];
    if (photo && (!['image/png','image/jpeg'].includes(photo.type) || photo.size > 3*1024*1024))
      return fieldError('Нужно фото JPG или PNG размером до 3 МБ.',el('photo'));
  }
  if (index === 1 && !selected('location')) return fieldError('Выберите место проблемы.',document.querySelector('input[name="location"]'));
  if (index === 2 && !selected('danger')) return fieldError('Ответьте на вопрос об опасности.',document.querySelector('input[name="danger"]'));
  if (index === 3) {
    if (!el('category').value) return fieldError('Подтвердите категорию проблемы.',el('category'));
    if (el('category').value === 'yard' && !['территория дома','городская'].includes(el('territory').value))
      return fieldError('Уточните территорию двора. Если не знаете, спросите диспетчера дома.',el('territory'));
    if (el('category').value === 'trash' && !el('trashContext').value)
      return fieldError('Уточните, что случилось с мусором.',el('trashContext'));
  }
  showError('stepError','');
  return true;
}

async function suggestCategory() {
  const revision = state.revision;
  if (state.categoryTouched && el('category').value) return;
  el('categoryHint').textContent = 'Определяем тему по описанию…';
  try {
    const payload = formData();
    payload.answers.selected_category = '';
    const result = await request('/api/triage',{method:'POST',body:JSON.stringify(payload)});
    if (revision !== state.revision || state.categoryTouched) return;
    if (result.category && categoryNames[result.category]) {
      el('category').value = result.category;
      el('categoryHint').textContent = `Предлагаем: ${categoryNames[result.category]}. Проверьте и при необходимости измените.`;
    } else {
      el('categoryHint').textContent = 'Не смогли уверенно определить тему. Выберите подходящую категорию.';
    }
    updateCategoryFields();
  } catch (error) { if (revision === state.revision) el('categoryHint').textContent = error.message; }
}

function showScreen(screen) {
  state.screen = screen;
  document.querySelector('.intro').hidden = screen !== 'wizard';
  el('wizard').hidden = screen !== 'wizard';
  el('routeScreen').hidden = screen !== 'route';
  el('successScreen').hidden = screen !== 'success';
  updateBackButton();
  if (screen === 'route') focusHeading('routeTitle');
  if (screen === 'success') focusHeading('successTitle');
}

function routeRecipient(card) {
  if (card.recipient.includes('gorod.mos.ru')) return {name:'Портал «Наш город»', action:'Открыть портал ↗', href:'https://gorod.mos.ru/'};
  if (card.recipient.includes('539-53-53')) return {name:'Единый диспетчерский центр Москвы', action:'Позвонить +7 (495) 539-53-53 ↗', href:'tel:+74955395353'};
  return {name:card.recipient, action:'', href:''};
}

function renderRoute(result) {
  const card = result.route_card;
  const recipient = routeRecipient(card);
  el('routeSummary').textContent = `${result.category_name} · ${el('house').selectedOptions[0]?.textContent || 'Москва'}`;
  el('routeContent').innerHTML = `
    ${result.immediate_action ? `<div class="route-warning"><strong>Срочно:</strong> ${escapeHtml(result.immediate_action)}<br><a href="tel:112">Позвонить 112 ↗</a></div>` : ''}
    <div class="route-block"><span class="route-label">01 / Куда обратиться</span><strong>${escapeHtml(recipient.name)}</strong><p>${escapeHtml(card.recipient_kind || '')}</p>${recipient.href ? `<a class="route-link" href="${recipient.href}" ${recipient.href.startsWith('https:') ? 'data-open-external="true" target="_blank" rel="noopener noreferrer"' : ''}>${escapeHtml(recipient.action)}</a>` : ''}</div>
    <div class="route-block"><span class="route-label">02 / Что делать сейчас</span><p>${escapeHtml(card.what_now)}</p></div>
    <div class="route-block"><span class="route-label">03 / Что приложить</span><p>${escapeHtml(card.attach.join(' · '))}</p></div>
    <div class="route-block"><span class="route-label">04 / Когда ждать ответ</span><p>${escapeHtml(card.response_expectation)}</p></div>`;
}

async function buildRoute() {
  if (!validateStep(3)) return;
  const revision = state.revision;
  const button = el('wizardNext');
  button.disabled = true;
  el('categoryHint').textContent = 'Проверяем маршрут…';
  try {
    const result = await request('/api/triage',{method:'POST',body:JSON.stringify(formData())});
    if (revision !== state.revision) return;
    if (!result.route_card || result.needs_clarification) {
      const question = result.follow_up_questions?.[0] || 'Уточните ответы и попробуйте ещё раз.';
      el('categoryHint').textContent = 'Проверьте ответы и повторите.';
      showError('stepError',question);
      return;
    }
    state.route = result;
    state.routeRevision = revision;
    el('categoryHint').textContent = 'Категория подтверждена.';
    renderRoute(result);
    showScreen('route');
  } catch (error) { el('categoryHint').textContent = 'Не удалось построить маршрут.'; showError('stepError',error.message); }
  finally { button.disabled = false; }
}

function readPhoto(file) {
  return new Promise((resolve,reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result);
    reader.onerror = () => reject(new Error('Не удалось прочитать фото. Выберите его ещё раз.'));
    reader.readAsDataURL(file);
  });
}

async function createTicket() {
  if (!state.route || state.routeRevision !== state.revision) {
    showError('routeMessage','Ответы изменились. Проверьте маршрут ещё раз.');
    return;
  }
  if (!['max','preview'].includes(state.session)) {
    showError('routeMessage','Чтобы сохранить заявку, откройте мини-приложение через бота MAX или локальный предпросмотр.');
    return;
  }
  const button = el('createButton');
  button.disabled = true;
  showError('routeMessage','');
  try {
    const elapsed = Math.round((Date.now()-state.startedAt)/1000);
    const payload = {...formData()};
    if (elapsed <= 86400) payload.seconds_to_create = elapsed;
    const photo = el('photo').files[0];
    if (photo) {
      if (!['image/png','image/jpeg'].includes(photo.type) || photo.size > 3*1024*1024) throw new Error('Нужно фото JPG или PNG размером до 3 МБ.');
      payload.photo_data_url = await readPhoto(photo);
    }
    const ticket = await request('/api/max/mini/tickets',{method:'POST',body:JSON.stringify(payload)});
    el('successId').textContent = ticket.id;
    el('successDescription').textContent = state.session === 'preview' ?
      'Следите за статусом во вкладке «Мои заявки». В локальном предпросмотре сообщения бота не приходят.' :
      'Следите за статусом во вкладке «Мои заявки». При смене статуса бот MAX попробует прислать сообщение.';
    showScreen('success');
  } catch (error) { showError('routeMessage',error.message); }
  finally { button.disabled = false; }
}

function formatDate(value) {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? 'Дата неизвестна' : date.toLocaleString('ru-RU',{dateStyle:'medium',timeStyle:'short'});
}
function statusRank(status) { return {accepted:1,assigned:2,done:3}[status] || 0; }

function renderTicket(ticket) {
  const progress = [1,2,3].map(n => `<span class="${n <= statusRank(ticket.status) ? 'done' : ''}"></span>`).join('');
  return `<article class="ticket-card"><div class="ticket-top"><span class="ticket-id">${escapeHtml(ticket.id)}</span><span class="status-badge">${escapeHtml(statusNames[ticket.status] || ticket.status)}</span></div>
    <h2>${escapeHtml(categoryNames[ticket.category] || ticket.category)}</h2><p>${escapeHtml(ticket.text)}</p>
    <div class="ticket-progress" aria-label="Прогресс: ${escapeHtml(statusNames[ticket.status] || ticket.status)}">${progress}</div>
    <div class="ticket-meta"><span>Этап ${statusRank(ticket.status)} из 3</span><time>${escapeHtml(formatDate(ticket.updated_at))}</time></div>
    <button class="ticket-open" type="button" data-ticket-id="${escapeHtml(ticket.id)}">Детали и история →</button></article>`;
}

async function loadTickets() {
  if (!['max','preview'].includes(state.session)) {
    el('myTickets').innerHTML = '<div class="error-state"><strong>История пока недоступна</strong><p>Откройте приложение из бота MAX, чтобы увидеть свои заявки.</p></div>';
    return;
  }
  const seq = ++state.ticketsSeq;
  el('refreshButton').disabled = true;
  if (!el('myTickets').querySelector('.ticket-card')) el('myTickets').innerHTML = '<div class="loading-state"><strong>Загружаем заявки…</strong><p>Обычно это занимает несколько секунд.</p></div>';
  try {
    const tickets = await request('/api/max/mini/tickets');
    if (seq !== state.ticketsSeq) return;
    const changes = tickets.filter(ticket => state.lastStatuses.has(ticket.id) && state.lastStatuses.get(ticket.id) !== ticket.status)
      .map(ticket => `Статус заявки ${ticket.id}: ${statusNames[ticket.status] || ticket.status}.`);
    state.lastStatuses = new Map(tickets.map(ticket => [ticket.id,ticket.status]));
    el('ticketsAnnounce').textContent = changes.join(' ');
    el('myTickets').innerHTML = tickets.length ? tickets.map(renderTicket).join('') :
      '<div class="empty-state"><strong>Заявок пока нет</strong><p>Опишите проблему — мы подскажем, куда обратиться.</p><button type="button" id="emptyStart">Создать заявку</button></div>';
  } catch (error) {
    if (seq === state.ticketsSeq) el('myTickets').innerHTML = `<div class="error-state"><strong>Не удалось загрузить заявки</strong><p>${escapeHtml(error.message)}</p><button type="button" id="retryTickets">Повторить</button></div>`;
  } finally { if (seq === state.ticketsSeq) el('refreshButton').disabled = false; }
}

async function openTicket(id) {
  el('ticketListScreen').hidden = true;
  el('ticketDetailScreen').hidden = false;
  el('ticketDetail').innerHTML = '<div class="loading-state"><strong>Открываем заявку…</strong></div>';
  updateBackButton();
  try {
    const ticket = await request(`/api/max/mini/tickets/${encodeURIComponent(id)}`);
    const recipient = routeRecipient(ticket.route);
    const events = (ticket.events || []).map(event => `<li><strong>${escapeHtml(statusNames[event.status] || event.status)}</strong><small>${escapeHtml(formatDate(event.created_at))} · ${escapeHtml(event.note)}</small></li>`).join('');
    el('ticketDetail').innerHTML = `<article class="detail-card"><span class="eyebrow">${escapeHtml(ticket.id)}</span><h1 id="detailTitle" tabindex="-1">${escapeHtml(categoryNames[ticket.category] || ticket.category)}</h1><span class="status-badge">${escapeHtml(statusNames[ticket.status] || ticket.status)}</span>
      <div class="detail-section"><h2>Описание</h2><p>${escapeHtml(ticket.text)}</p><p>${ticket.photo_path ? 'Фото приложено' : 'Фото не приложено'}</p></div>
      <div class="detail-section"><h2>Куда обратиться</h2><p>${escapeHtml(recipient.name)}</p>${recipient.href ? `<a class="route-link" href="${recipient.href}" ${recipient.href.startsWith('https:') ? 'data-open-external="true" target="_blank" rel="noopener noreferrer"' : ''}>${escapeHtml(recipient.action)}</a>` : ''}</div>
      <div class="detail-section"><h2>История статусов</h2><ol class="event-list">${events}</ol></div></article>`;
    focusHeading('detailTitle');
  } catch (error) { el('ticketDetail').innerHTML = `<div class="error-state"><strong>Не удалось открыть заявку</strong><p>${escapeHtml(error.message)}</p></div>`; }
}

function closeTicket() {
  el('ticketDetailScreen').hidden = true;
  el('ticketListScreen').hidden = false;
  updateBackButton();
  focusHeading('ticketsTitle');
}

function setTab(tab, focus=true) {
  const previous = state.tab;
  state.tab = tab;
  el('newTab').hidden = tab !== 'new';
  el('mineTab').hidden = tab !== 'mine';
  document.querySelectorAll('.nav-button').forEach(button => {
    const active = button.dataset.tab === tab;
    button.classList.toggle('active',active);
    if (active) button.setAttribute('aria-current','page'); else button.removeAttribute('aria-current');
  });
  if (tab === 'mine') {
    if (previous !== 'mine') { el('ticketDetailScreen').hidden = true; el('ticketListScreen').hidden = false; }
    loadTickets();
    if (focus) focusHeading('ticketsTitle');
  }
  else if (focus) focusHeading(state.screen === 'wizard' ? `stepTitle${state.step}` : state.screen === 'route' ? 'routeTitle' : 'successTitle');
  updateBackButton();
}

function startAgain() {
  el('house').selectedIndex = 0;
  el('description').value = '';
  el('photo').value = '';
  el('photoName').textContent = 'По желанию · JPG или PNG, до 3 МБ';
  document.querySelectorAll('input[type="radio"]').forEach(input => { input.checked = false; });
  el('category').value = '';
  el('territory').value = '';
  el('trashContext').value = '';
  state.categoryTouched = false;
  state.urgentFromModel = '';
  state.urgentSeq++;
  clearTimeout(state.urgentTimer);
  updateEmergency();
  invalidate();
  state.startedAt = Date.now();
  updateCategoryFields();
  setTab('new',false);
  showScreen('wizard');
  setStep(0);
}

function handleBack() {
  if (state.tab === 'mine' && !el('ticketDetailScreen').hidden) return closeTicket();
  if (state.tab === 'new' && state.screen === 'route') { showScreen('wizard'); return setStep(3); }
  if (state.tab === 'new' && state.screen === 'success') return setTab('mine');
  if (state.tab === 'new' && state.step > 0) return setStep(state.step-1);
  setTab('new');
}

async function verifySession() {
  try {
    const session = await request('/api/max/mini/session');
    state.session = session.mode;
    setConnection(session.mode === 'preview' ?
      'Локальный предпросмотр · заявки и статусы только в демо-системе.' :
      'Аккаунт MAX подтверждён · заявки будут привязаны к вам.', 'verified');
  } catch (error) {
    state.session = 'invalid';
    setConnection(error.message, 'warning');
  }
}

async function loadHouses() {
  try {
    const houses = await request('/api/houses');
    el('house').innerHTML = '<option value="">Выберите дом</option>' + Object.entries(houses).map(([id,house]) => `<option value="${escapeHtml(id)}">${escapeHtml(house.name)}</option>`).join('');
    if (Object.keys(houses).length === 1) el('house').selectedIndex = 1;
  } catch (error) { el('house').innerHTML = '<option value="">Дома не загрузились</option>'; showError('stepError',`Не удалось загрузить дома: ${error.message}`); }
}

function bindEvents() {
  document.addEventListener('click',event => {
    const link = event.target.closest('a[data-open-external]');
    if (link && state.session === 'max' && window.WebApp?.openLink) {
      event.preventDefault();
      window.WebApp.openLink(link.href);
    }
  });
  el('description').addEventListener('input',() => { invalidate({resetCategory:true}); scheduleUrgency(); });
  el('house').addEventListener('change',() => { invalidate({resetCategory:true}); scheduleUrgency(); });
  document.querySelectorAll('[data-example]').forEach(button => button.addEventListener('click',() => {
    el('description').value = button.dataset.example;
    el('description').dispatchEvent(new Event('input',{bubbles:true}));
    el('description').focus();
  }));
  document.querySelectorAll('input[name="location"]').forEach(input => input.addEventListener('change',() => invalidate({resetCategory:true})));
  document.querySelectorAll('input[name="danger"]').forEach(input => input.addEventListener('change',() => { invalidate({resetCategory:true}); updateEmergency(); scheduleUrgency(); }));
  el('category').addEventListener('change',() => {
    state.categoryTouched = true;
    el('categoryHint').textContent = 'Категорию можно изменить до создания заявки.';
    el('territory').value = '';
    el('trashContext').value = '';
    updateCategoryFields();
    invalidate();
  });
  el('territory').addEventListener('change',() => invalidate());
  el('trashContext').addEventListener('change',() => invalidate());
  el('photo').addEventListener('change',() => { el('photoName').textContent = el('photo').files[0]?.name || 'По желанию · JPG или PNG, до 3 МБ'; showError('routeMessage',''); });
  el('wizardBack').addEventListener('click',() => setStep(state.step-1));
  el('wizardNext').addEventListener('click',async () => {
    if (!validateStep(state.step)) return;
    if (state.step === 3) return buildRoute();
    setStep(state.step+1);
    if (state.step === 3) suggestCategory();
  });
  el('editAnswers').addEventListener('click',() => { showScreen('wizard'); setStep(3); });
  el('createButton').addEventListener('click',createTicket);
  el('goToTickets').addEventListener('click',() => setTab('mine'));
  el('startAgain').addEventListener('click',startAgain);
  document.querySelectorAll('.nav-button').forEach(button => button.addEventListener('click',() => setTab(button.dataset.tab)));
  el('refreshButton').addEventListener('click',loadTickets);
  el('myTickets').addEventListener('click',event => {
    const id = event.target.closest('[data-ticket-id]')?.dataset.ticketId;
    if (id) openTicket(id);
    if (event.target.closest('#emptyStart')) setTab('new');
    if (event.target.closest('#retryTickets')) loadTickets();
  });
  el('ticketBack').addEventListener('click',closeTicket);
  document.addEventListener('visibilitychange',() => { if (!document.hidden && state.tab === 'mine') loadTickets(); });
  setInterval(() => { if (!document.hidden && state.tab === 'mine' && el('ticketDetailScreen').hidden) loadTickets(); },15000);
  window.WebApp?.BackButton?.onClick?.(handleBack);
}

bindEvents();
Promise.all([loadHouses(),verifySession()]).then(() => { if (state.session !== 'invalid') loadTickets(); });
