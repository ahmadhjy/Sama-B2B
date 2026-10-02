"""Guided planner browser checks. AI responses are mocked; no provider calls."""
import json
import os
import sys
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import urlparse
from playwright.sync_api import sync_playwright, expect

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
os.environ.setdefault('DJANGO_SETTINGS_MODULE','hellosama.settings')
import django
django.setup()
from portal.models import Draft, User
from django.conf import settings
BASE=os.environ.get('HELLOSAMA_TEST_URL','http://127.0.0.1:8766')
if urlparse(BASE).hostname not in ('127.0.0.1','localhost') or not settings.DEBUG or settings.DATABASES['default']['ENGINE']!='django.db.backends.sqlite3':
    raise SystemExit('Run only against the local SQLite demo preview.')
OUT=ROOT/'test-results';OUT.mkdir(exist_ok=True)
password=os.environ.get('HELLOSAMA_DEMO_PASSWORD') or (ROOT/'.demo-access.txt').read_text(encoding='utf-8-sig').split('Local demo password: ',1)[1].strip()
errors=[]
summary=dict(title='Family trip to Bangkok',origin='Beirut',destination='Bangkok',
    departure=str(date.today()+timedelta(days=30)),return_date='',travellers='4',budget='',
    requirements='2 adults, 1 child, 1 infant. 6 nights. Hotel and transfers.')

draft_ids=[str(Draft.objects.create(user=User.objects.get(username='demo.requester')).pk) for _ in range(2)]
with sync_playwright() as p:
    browser=p.chromium.launch(channel='msedge',headless=True)
    for width,draft_id in zip((1440,390),draft_ids):
        planner_url=BASE+'/requests/new/?draft='+draft_id
        context=browser.new_context(viewport={'width':width,'height':950 if width==1440 else 844})
        context.route('**/*',lambda route:route.continue_() if route.request.url.startswith(BASE) else route.abort())
        def mock_ai(route):
            data=route.request.post_data_json
            body={'summary':summary} if data.get('action')=='summary' else {'message':{
                'role':'assistant','content':'Your trip details are ready. Click Review my request below.','sources':[]}}
            route.fulfill(status=200,content_type='application/json',body=json.dumps(body))
        context.route('**/api/assistant/**',mock_ai)
        page=context.new_page();page.on('pageerror',lambda exc:errors.append(str(exc)))
        page.goto(BASE+'/login/')
        page.get_by_label('Account number or user ID').fill('demo.requester')
        page.locator('#id_password').fill(password);page.get_by_role('button',name='Sign in',exact=False).click()
        page.wait_for_url(BASE+'/');page.goto(planner_url)
        expect(page.locator('#request-review')).to_be_hidden()
        expect(page.locator('#generate-summary')).to_be_disabled()
        page.screenshot(path=str(OUT/f'planner-{width}-chat.png'),full_page=True)
        page.locator('#chat-input').fill('Beirut to Bangkok next month, 2 adults, 1 child, 1 infant, six nights.')
        page.locator('#assistant-form button').click()
        expect(page.locator('#generate-summary')).to_be_enabled()
        page.locator('#generate-summary').click()
        expect(page.locator('#request-review')).to_be_visible()
        expect(page.locator('#id_travellers')).to_have_value('4')
        expect(page.locator('#id_requirements')).to_have_value(summary['requirements'])
        expect(page.locator('#review-status')).to_contain_text('Submit request to Sama')
        expect(page.locator('#id_budget')).to_be_hidden()
        # Regeneration must not silently discard edits or private traveller details.
        page.locator('#id_destination').fill('Phuket')
        page.locator('#extra-details > summary').click()
        page.locator('#id_traveller_details').fill('Private details stay out of the assistant')
        page.once('dialog',lambda dialog:dialog.dismiss());page.locator('#generate-summary').click()
        expect(page.locator('#id_destination')).to_have_value('Phuket')
        page.once('dialog',lambda dialog:dialog.accept());page.locator('#generate-summary').click()
        expect(page.locator('#id_destination')).to_have_value('Bangkok')
        expect(page.locator('#id_traveller_details')).to_have_value('Private details stay out of the assistant')
        page.locator('#extra-details > summary').click()
        page.screenshot(path=str(OUT/f'planner-{width}-review.png'),full_page=True)
        assert not page.evaluate('document.documentElement.scrollWidth > innerWidth + 1')
        # Browser validation keeps an incomplete form in place; AI never auto-submits it.
        page.locator('#id_departure').fill('');page.locator('#submit-request').click()
        expect(page).to_have_url(planner_url)
        expect(page.locator('#submit-request')).to_be_enabled()
        context.close()
    browser.close()
if errors:raise SystemExit('\n'.join(errors))
print('Guided planner passed on desktop and mobile: chat, review, edit protection, private fields and validation.')
