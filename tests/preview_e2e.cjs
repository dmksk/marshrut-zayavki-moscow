const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const net = require('node:net');
const {spawn} = require('node:child_process');
const {chromium} = require('playwright');

const root = path.resolve(__dirname, '..');
const screenshots = process.env.SCREENSHOT_DIR || path.join(os.tmpdir(), 'marshrut-pages-screenshots');
fs.mkdirSync(screenshots, {recursive:true});

async function freePort() {
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
  const port = await freePort();
  const base = `http://127.0.0.1:${port}`;
  const server = spawn('python3',['-m','http.server',String(port),'--bind','127.0.0.1'],{cwd:root,stdio:'ignore'});
  let browser;
  try {
    for (let i=0;i<50;i++) {
      try { if ((await fetch(base)).ok) break; } catch {}
      if (i === 49) throw new Error('Статический предпросмотр не запустился');
      await new Promise(resolve => setTimeout(resolve,150));
    }
    browser = await chromium.launch({headless:true,...(process.env.CHROME_PATH ? {executablePath:process.env.CHROME_PATH} : {})});
    const context = await browser.newContext({viewport:{width:390,height:844}});
    const page = await context.newPage();
    const apiCalls = [];
    const errors = [];
    page.on('request',request => { if (request.url().includes('/api/')) apiCalls.push(request.url()); });
    page.on('pageerror',error => errors.push(error.message));
    await page.goto(base,{waitUntil:'domcontentloaded'});
    await page.locator('#connection.verified').waitFor();
    assert.match(await page.locator('#connection').innerText(),/в этом браузере/);
    await page.screenshot({path:path.join(screenshots,'pages-main-390-viewport.png')});
    await page.screenshot({path:path.join(screenshots,'pages-main-390.png'),fullPage:true});
    await page.locator('#house').selectOption('demo_1');
    await page.locator('#description').fill('В подъезде не горит свет на третьем этаже');
    await page.locator('#wizardNext').click();
    await page.locator('input[name="location"][value="подъезд"]').check();
    await page.locator('#wizardNext').click();
    await page.locator('input[name="danger"][value="нет"]').check();
    await page.locator('#wizardNext').click();
    await page.waitForFunction(() => document.querySelector('#category').value === 'entrance_electricity');
    await page.locator('#wizardNext').click();
    await page.locator('#routeScreen:visible').waitFor();
    await page.screenshot({path:path.join(screenshots,'pages-route-390.png'),fullPage:true});
    await page.locator('#createButton').click();
    await page.locator('#successScreen:visible').waitFor();
    await page.locator('#goToTickets').click();
    await page.locator('.ticket-open').first().click();
    await page.locator('[data-preview-advance]').click();
    await page.waitForFunction(() => document.querySelector('#ticketDetail').textContent.includes('Назначен исполнитель'));
    await page.reload();
    await page.locator('#connection.verified').waitFor();
    await page.locator('[data-tab="mine"]').click();
    assert.match(await page.locator('#myTickets').innerText(),/Назначен исполнитель/);
    assert.deepEqual(apiCalls,[],'GitHub Pages не должен вызывать серверное API');
    assert.deepEqual(errors,[],'JavaScript ошибки в Pages');
    await context.close();
    console.log(`GitHub Pages preview E2E: OK; скриншоты: ${screenshots}`);
  } finally {
    await browser?.close();
    server.kill('SIGINT');
  }
}

main().catch(error => { console.error(error); process.exitCode = 1; });
