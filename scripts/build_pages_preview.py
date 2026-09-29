"""Generate the GitHub Pages entry from the actual MAX Mini App markup."""

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
source = (ROOT / "web" / "mini.html").read_text(encoding="utf-8")
preview = source.replace('href="/mini.css"', 'href="web/mini.css"')
preview = preview.replace('<script src="https://st.max.ru/js/max-web-app.js"></script>',
                          '<script src="preview/mock-api.js"></script>')
preview = preview.replace('src="/mini.js"', 'src="web/mini.js"')
preview = preview.replace('<title>Маршрут заявки · Москва</title>',
                          '<title>Предпросмотр · Маршрут заявки · Москва</title>')
assert preview != source
target = ROOT / "index.html"
if "--check" in sys.argv:
    if not target.exists() or target.read_text(encoding="utf-8") != preview:
        raise SystemExit("GitHub Pages index.html устарел. Запустите python3 scripts/build_pages_preview.py")
else:
    target.write_text(preview, encoding="utf-8")
