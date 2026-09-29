/* GitHub Pages preview only. No MAX account, server, ML model or real service calls. */
(() => {
  const key = 'marshrut-moscow-preview-tickets-v1';
  const houses = {
    demo_1: {name:'Демо-дом в Москве №1 (вымышленный)',manager:'Демо УК №1 (вымышленная)'},
    demo_2: {name:'Демо-дом в Москве №2 (вымышленный)',manager:'Демо ТСЖ №2 (вымышленное)'}
  };
  const names = {
    leak:'Протечка',lift:'Лифт',heating:'Отопление и горячая вода',
    entrance_electricity:'Свет в общих зонах',trash:'Мусор',yard:'Двор'
  };
  let memory = [];
  try { memory = JSON.parse(localStorage.getItem(key) || '[]'); if (!Array.isArray(memory)) memory = []; } catch { memory = []; }
  const save = () => { try { localStorage.setItem(key, JSON.stringify(memory)); } catch { /* Private browsing may block storage. */ } };
  const fail = message => { throw new Error(message); };
  const now = () => new Date().toISOString();
  const match = (text, expression) => expression.test(text);
  const categoryFromText = (text, location) => {
    if (match(text,/лифт|кабин|застрял|застряли/i)) return 'lift';
    if (match(text,/мусор|контейнер|бак|отход/i)) return 'trash';
    if (match(text,/батаре|отоплен|радиатор|холодно|горяч[а-я]* вод/i)) return 'heating';
    if (match(text,/теч|протеч|затоп|залив|стояк|труб|крыша/i)) return 'leak';
    if (match(text,/двор|снег|голол|дорожк|асфальт|площадк|дерев|яма/i)) return 'yard';
    if (match(text,/подъезд|лестниц|свет|ламп|электр|щит|провод/i)) return location === 'двор' ? 'yard' : 'entrance_electricity';
    return null;
  };
  const urgentAction = (text, danger) => {
    if (match(text,/запах\s+газа|утечк[а-я]*\s+газа/i)) return 'Выйдите из опасной зоны и позвоните 112. Не включайте электроприборы.';
    if (match(text,/(люди|реб[её]нок|человек).{0,35}(застрял|застряли).{0,25}лифт|лифт.{0,35}(застрял|застряли).{0,25}(люди|реб[её]нок|человек)/i)) return 'Если в лифте люди, звоните 112 и в диспетчерскую. Не пытайтесь открыть двери самостоятельно.';
    if (match(text,/дым|пожар|горит\s+проводк|искрит\s+щит/i)) return 'Отойдите от опасного места и позвоните 112.';
    if (match(text,/вода.{0,35}(щит|провод|розет)|затоп.{0,35}(щит|провод|розет)/i)) return 'Не приближайтесь к электрооборудованию и позвоните 112.';
    return danger === 'да' ? 'При непосредственной опасности отойдите от места происшествия и позвоните 112.' : '';
  };
  const route = payload => {
    const text = String(payload?.text || '').trim();
    const house = houses[payload?.house_id];
    if (text.length < 2) fail('Опишите проблему хотя бы двумя символами.');
    if (!house) fail('Выберите дом из списка.');
    const answers = payload.answers || {};
    const category = names[answers.selected_category] ? answers.selected_category : categoryFromText(text, answers.location);
    const urgent = urgentAction(text, answers.danger);
    const followUp = [];
    if (!category) followUp.push('Выберите категорию проблемы.');
    if (category === 'yard' && !['территория дома','городская'].includes(answers.territory_owner))
      followUp.push('Уточните, относится ли участок к дому или к городской территории.');
    if (category === 'trash' && !answers.trash_context)
      followUp.push('Уточните, что случилось с мусором.');
    const city = category === 'yard' && answers.territory_owner === 'городская' && !urgent;
    const card = category && !followUp.length ? {
      recipient: city ? 'Портал «Наш город»: https://gorod.mos.ru/' : 'Единый диспетчерский центр Москвы: +7 (495) 539-53-53',
      recipient_kind: city ? 'сообщение о проблеме на городской территории' : 'ЕДЦ принимает заявки по ЖКХ дома; исполнитель определяется по выбранному дому',
      responsible_for_house: city ? null : house.manager,
      what_now: urgent || 'Создайте заявку и приложите данные. При аварии звоните в ЕДЦ Москвы по номеру +7 (495) 539-53-53; при непосредственной угрозе жизни — 112.',
      attach: ['выбранный дом','точное место','краткое описание','время обнаружения',...(category === 'heating' ? ['есть ли тепло и горячая вода в соседних квартирах'] : ['фото, если безопасно и возможно'])],
      response_expectation: 'Здесь показаны только демо-статусы. Фактический срок реакции и устранения сообщает диспетчер или официальный сервис после регистрации.',
      sources: ['https://www.mos.ru/assets/vyzov-mastera/static/documents/rules.pdf','https://gorod.mos.ru/']
    } : null;
    return {
      category, category_name:names[category] || 'Требуется уточнение',
      category_source:answers.selected_category ? 'resident_confirmation' : 'preview_keyword_rule',
      immediate_action:urgent, needs_clarification:!!followUp.length,
      follow_up_questions:followUp, route_card:card
    };
  };
  const parseBody = options => { try { return JSON.parse(options?.body || '{}'); } catch { fail('Не удалось прочитать данные заявки.'); } };
  window.miniPreviewRequest = async (path, options={}) => {
    if (path === '/api/houses') return houses;
    if (path === '/api/max/mini/session') return {mode:'preview'};
    if (path === '/api/triage') return route(parseBody(options));
    if (path === '/api/max/mini/tickets' && options.method === 'POST') {
      const payload = parseBody(options);
      const answers = payload.answers || {};
      if (!['квартира','подъезд','двор','улица'].includes(answers.location)) fail('Укажите, где возникла проблема.');
      if (!['да','нет','не знаю'].includes(answers.danger)) fail('Ответьте на вопрос об опасности.');
      if (!names[answers.selected_category]) fail('Подтвердите тему обращения.');
      const result = route(payload);
      if (!result.route_card || result.needs_clarification) fail(result.follow_up_questions[0] || 'Уточните ответы перед созданием заявки.');
      const stamp = now();
      const id = 'M-' + Array.from(crypto.getRandomValues(new Uint8Array(5)), byte => byte.toString(16).padStart(2,'0')).join('').toUpperCase();
      const ticket = {
        id, created_at:stamp, updated_at:stamp, house_id:payload.house_id, text:payload.text.trim(),
        category:result.category, status:'accepted', answers, route:result.route_card,
        photo_path:payload.photo_data_url ? 'preview-photo' : null,
        events:[{status:'accepted',created_at:stamp,note:'Демо-заявка создана в этом браузере'}]
      };
      memory.unshift(ticket);
      save();
      return ticket;
    }
    if (path === '/api/max/mini/tickets') return memory.map(({events,...ticket}) => ticket);
    const detail = path.match(/^\/api\/max\/mini\/tickets\/([^/]+)(\/advance)?$/);
    if (detail) {
      const ticket = memory.find(item => item.id === decodeURIComponent(detail[1]));
      if (!ticket) fail('Заявка не найдена в этом браузере.');
      if (detail[2]) {
        const next = {accepted:'assigned',assigned:'done'}[ticket.status];
        if (!next) fail('Демо-заявка уже выполнена.');
        ticket.status = next;
        ticket.updated_at = now();
        ticket.events.push({status:next,created_at:ticket.updated_at,note:'Статус изменён в интерактивном макете'});
        save();
      }
      return ticket;
    }
    fail('Действие недоступно в интерактивном макете.');
  };
})();
