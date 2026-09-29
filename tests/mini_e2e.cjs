const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const net = require('node:net');
const {spawn} = require('node:child_process');
const {chromium} = require('playwright');

const root = path.resolve(__dirname, '..');
const screenshots = process.env.SCREENSHOT_DIR || path.join(os.tmpdir(), 'marshrut-mini-screenshots');
fs.mkdirSync(screenshots, {recursive:true});

async function waitForServer(base) {
  for (let attempt=0; attempt<60; attempt++) {
    try { if ((await fetch(`${base}/api/health`)).ok) return; } catch {}
    await new Promise(resolve => setTimeout(resolve, 200));
  }
  throw new Error('Локальный сервер не запустился');
}

function freePort() {
  return new Promise((resolve,reject) => {
    const socket = net.createServer();
    socket.on('error',reject);
    socket.listen(0,'127.0.0.1',() => {
      const port = socket.address().port;
      socket.close(() => resolve(port));
    });
  });
}

async function main() {
  const temp = fs.mkdtempSync(path.join(os.tmpdir(), 'marshrut-e2e-'));
  const port = await freePort();
  const base = `http://127.0.0.1:${port}`;
  const server = spawn('python3', ['-c', `from app.server import build_server; build_server('127.0.0.1',${port},'${path.join(temp,'demo.sqlite3')}').serve_forever()`], {
    cwd:root, env:{...process.env,MAX_BOT_TOKEN:'',APP_PUBLIC:'',APP_ADMIN_KEY:'e2e-admin'}, stdio:'ignore'
  });
  let browser;
  try {
    await waitForServer(base);
    browser = await chromium.launch({headless:true,...(process.env.CHROME_PATH ? {executablePath:process.env.CHROME_PATH} : {})});
    for (const width of [320,375,390,768]) {
      const page = await browser.newPage({viewport:{width,height:740},deviceScaleFactor:1});
      const errors = [];
      page.on('pageerror', error => errors.push(error.message));
      await page.goto(`${base}/mini`,{waitUntil:'domcontentloaded'});
      await page.locator('#connection.verified').waitFor();
      const layout = await page.evaluate(() => ({
        overflow:document.documentElement.scrollWidth-innerWidth,
        descriptionTop:document.querySelector('#description').getBoundingClientRect().top,
        exampleHeight:document.querySelector('.examples button').getBoundingClientRect().height,
        navHeight:document.querySelector('.nav-button').getBoundingClientRect().height,
        mainHeight:document.querySelector('#wizardNext').getBoundingClientRect().height,
      }));
      assert.equal(layout.overflow,0,`${width}px: горизонтальная прокрутка`);
      assert.ok(layout.descriptionTop<740,`${width}px: поле описания не видно на первом экране`);
      assert.ok(layout.exampleHeight>=44 && layout.navHeight>=44 && layout.mainHeight>=44,`${width}px: маленькая область нажатия`);
      assert.deepEqual(errors,[],`${width}px: ошибки JavaScript`);
      await page.screenshot({path:path.join(screenshots,`initial-${width}.png`),fullPage:true});
      if (width === 320) {
        await page.evaluate(() => { document.documentElement.style.fontSize = '32px'; });
        assert.equal(await page.evaluate(() => document.documentElement.scrollWidth-innerWidth),0,'200% текста: горизонтальная прокрутка');
        await page.screenshot({path:path.join(screenshots,'text-200-percent-320.png'),fullPage:true});
      }
      await page.close();
    }

    const page = await browser.newPage({viewport:{width:390,height:844},deviceScaleFactor:1});
    await page.goto(`${base}/mini`,{waitUntil:'domcontentloaded'});
    await page.locator('#connection.verified').waitFor();
    await page.locator('#house').selectOption('demo_1');
    await page.locator('[data-example="В подъезде не горит свет на третьем этаже"]').click();
    await page.locator('#wizardNext').click();
    assert.equal(await page.locator('#progressBar').getAttribute('aria-valuenow'),'2');
    await page.locator('input[name="location"][value="подъезд"]').check();
    await page.locator('#wizardNext').click();
    await page.locator('input[name="danger"][value="нет"]').check();
    await page.locator('#wizardNext').click();
    await page.waitForFunction(() => document.querySelector('#category').value !== '');
    assert.equal(await page.locator('#category').inputValue(),'entrance_electricity');
    await page.locator('#category').selectOption('lift');
    await page.locator('#wizardNext').click();
    await page.locator('#routeScreen:visible').waitFor();
    assert.match(await page.locator('#routeSummary').innerText(),/Лифт/);
    await page.locator('#editAnswers').click();
    await page.locator('#category').selectOption('entrance_electricity');
    await page.locator('#wizardNext').click();
    await page.locator('#routeScreen:visible').waitFor();
    assert.match(await page.locator('#routeContent').innerText(),/Единый диспетчерский центр Москвы/);
    await page.screenshot({path:path.join(screenshots,'route-390.png'),fullPage:true});

    await page.locator('#editAnswers').click();
    for (let i=0;i<3;i++) await page.locator('#wizardBack').click();
    await page.locator('[data-example="Во дворе после снегопада не очистили дорожку"]').click();
    assert.equal(await page.locator('#category').inputValue(),'');
    assert.equal(await page.locator('#routeScreen').isVisible(),false);
    await page.locator('#wizardNext').click();
    await page.locator('input[name="location"][value="двор"]').check();
    await page.locator('#wizardNext').click();
    await page.locator('#wizardNext').click();
    await page.waitForFunction(() => document.querySelector('#category').value !== '');
    await page.locator('#category').selectOption('yard');
    await page.locator('#wizardNext').click();
    assert.match(await page.locator('#stepError').innerText(),/территорию/);
    await page.locator('#territory').selectOption('городская');
    await page.locator('#wizardNext').click();
    await page.locator('#routeScreen:visible').waitFor();
    assert.equal(await page.locator('.route-link[href="https://gorod.mos.ru/"]').count(),1);
    await page.locator('#photo').setInputFiles({name:'demo.png',mimeType:'image/png',buffer:Buffer.from([137,80,78,71,13,10,26,10,1,2,3])});
    await page.locator('#createButton').click();
    await page.locator('#successScreen:visible').waitFor();
    const id = await page.locator('#successId').innerText();
    assert.match(id,/^M-[A-F0-9]{10}$/);
    assert.match(await page.locator('#successDescription').innerText(),/сообщения бота не приходят/);
    await page.screenshot({path:path.join(screenshots,'success-390.png'),fullPage:true});
    await page.locator('#goToTickets').click();
    await page.locator('.ticket-card').first().waitFor();
    assert.match(await page.locator('#myTickets').innerText(),/Принято/);
    await page.screenshot({path:path.join(screenshots,'tickets-390.png'),fullPage:true});
    const status = await fetch(`${base}/api/tickets/${id}/status`,{method:'PATCH',headers:{'Content-Type':'application/json','X-Admin-Key':'e2e-admin'},body:JSON.stringify({status:'assigned'})});
    assert.equal(status.status,200);
    await page.locator('#refreshButton').click();
    await page.waitForFunction(() => document.querySelector('#myTickets').textContent.includes('Назначен исполнитель'));
    assert.match(await page.locator('#ticketsAnnounce').textContent(),/Статус заявки/);
    await page.locator('.ticket-open').first().click();
    await page.locator('#detailTitle').waitFor();
    assert.match(await page.locator('#ticketDetail').innerText(),/Фото приложено/);
    assert.match(await page.locator('#ticketDetail').innerText(),/Назначен исполнитель/);

    await page.locator('[data-tab="new"]').click();
    await page.locator('#startAgain').click();
    await page.locator('#house').selectOption('demo_1');
    await page.locator('#description').fill('Мусор возле контейнеров во дворе');
    await page.locator('#wizardNext').click();
    await page.locator('input[name="location"][value="двор"]').check();
    await page.locator('#wizardNext').click();
    await page.locator('input[name="danger"][value="нет"]').check();
    await page.locator('#wizardNext').click();
    await page.locator('#category').selectOption('trash');
    assert.equal(await page.locator('#trashField').isVisible(),true);
    await page.locator('#wizardNext').click();
    assert.match(await page.locator('#stepError').innerText(),/мусором/);
    await page.locator('#trashContext').selectOption('контейнеры');
    await page.locator('#wizardNext').click();
    await page.locator('#routeScreen:visible').waitFor();
    await page.close();

    const urgent = await browser.newPage({viewport:{width:390,height:844}});
    await urgent.goto(`${base}/mini`,{waitUntil:'domcontentloaded'});
    await urgent.locator('#description').fill('В лифте застрял человек');
    await urgent.locator('#emergency:visible').waitFor({timeout:10000});
    assert.equal(await urgent.locator('.emergency-call').getAttribute('href'),'tel:112');
    assert.match(await urgent.locator('#emergencyText').innerText(),/лифт/);
    await urgent.screenshot({path:path.join(screenshots,'emergency-390.png'),fullPage:true});
    await urgent.close();

    const dark = await browser.newPage({viewport:{width:390,height:844},colorScheme:'dark'});
    await dark.goto(`${base}/mini`,{waitUntil:'domcontentloaded'});
    const darkBg = await dark.evaluate(() => getComputedStyle(document.body).backgroundColor);
    assert.notEqual(darkBg,'rgb(243, 247, 246)');
    await dark.screenshot({path:path.join(screenshots,'dark-390.png'),fullPage:true});
    await dark.close();

    const invalid = await browser.newContext();
    await invalid.route('https://st.max.ru/js/max-web-app.js', route => route.fulfill({body:'window.WebApp={initData:"invalid"};',contentType:'text/javascript'}));
    const invalidPage = await invalid.newPage();
    await invalidPage.goto(`${base}/mini`,{waitUntil:'domcontentloaded'});
    await invalidPage.locator('#connection.warning').waitFor();
    assert.match(await invalidPage.locator('#connection').innerText(),/Бот MAX пока не настроен/);
    await invalid.close();
    console.log(`Mini App E2E: OK; скриншоты: ${screenshots}`);
  } finally {
    await browser?.close();
    server.kill('SIGINT');
    fs.rmSync(temp,{recursive:true,force:true});
  }
}

main().catch(error => {console.error(error);process.exitCode=1;});
