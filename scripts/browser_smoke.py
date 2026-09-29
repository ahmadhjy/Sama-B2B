"""Local-only browser acceptance journey and responsive screenshots (fictional accounts)."""
import json
import os
import re
from datetime import date,timedelta
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT=Path(__file__).resolve().parents[1]
BASE='http://127.0.0.1:8765'
OUTPUT=ROOT/'test-results';OUTPUT.mkdir(exist_ok=True)
password=os.environ.get('HELLOSAMA_DEMO_PASSWORD','')
if not password:
    text=(ROOT/'.demo-access.txt').read_text(encoding='utf-8-sig')
    password=text.split('Local demo password: ',1)[1].strip()
errors=[]

with sync_playwright() as p:
    browser=p.chromium.launch(channel='msedge',headless=True)
    context=browser.new_context(viewport={'width':1440,'height':1050},device_scale_factor=1)
    page=context.new_page()
    page.on('pageerror',lambda error:errors.append(str(error)))
    context.route('**/*',lambda route:route.continue_() if route.request.url.startswith(BASE) else route.abort())
    def capture(name):
        page.screenshot(path=str(OUTPUT/f'{name}.png'),full_page=True,animations='disabled')
        overflow=page.evaluate('document.documentElement.scrollWidth > innerWidth + 1')
        if overflow: errors.append(f'Horizontal overflow: {name}')
    def sign_in(username):
        page.goto(BASE+'/login/')
        if page.locator('button.logout').count():
            page.locator('button.logout').click();page.wait_for_url('**/login/')
        page.get_by_label('Account number or user ID').fill(username)
        page.locator('#id_password').fill(password)
        page.get_by_role('button',name='Sign in',exact=False).click()
        page.wait_for_url(BASE+'/')
    page.goto(BASE+'/login/');capture('01-login-desktop')
    sign_in('demo.owner');capture('02-dashboard-desktop')
    page.set_viewport_size({'width':390,'height':844});capture('03-dashboard-mobile')
    page.locator('#menu-toggle').click();page.get_by_role('link',name='My requests',exact=False).click()
    page.wait_for_url('**/requests/');capture('04-requests-mobile')
    page.set_viewport_size({'width':1440,'height':1050})
    page.goto(BASE+'/requests/new/');capture('05-trip-planner')
    page.locator('#id_title').fill('Browser acceptance journey')
    page.locator('#id_origin').fill('Beirut');page.locator('#id_destination').fill('Bangkok')
    page.locator('#id_departure').fill((date.today()+timedelta(days=40)).isoformat())
    page.locator('#id_return_date').fill((date.today()+timedelta(days=46)).isoformat())
    page.locator('#id_travellers').fill('2');page.locator('#id_budget').fill('3000 USD total')
    page.locator('#id_requirements').fill('Central hotel and airport transfers. Fictional browser acceptance test.')
    page.get_by_role('button',name='Submit request',exact=False).click()
    page.wait_for_url(re.compile(r'.*/requests/[0-9a-f-]+/$'))
    request_url=page.url
    reference=page.locator('.request-page-heading p').inner_text().split(' · ')[0].strip()
    capture('06-submitted-conversation')
    sign_in('demo.sales');page.goto(BASE+'/queue/')
    row=page.get_by_role('row').filter(has_text=reference)
    row.get_by_role('button',name='Take over',exact=False).click();page.wait_for_url(request_url)
    page.get_by_role('link',name='Prepare quotation',exact=True).click()
    page.locator('#id_amount').fill('2840.00')
    page.locator('#id_details').fill('Two return flights and six nights in Bangkok. Demonstration offer only.')
    page.locator('#id_inclusions').fill('Breakfast and airport transfers')
    page.locator('#id_exclusions').fill('Optional excursions')
    page.get_by_role('button',name='Send quotation',exact=True).click();page.wait_for_url(request_url)
    sign_in('demo.owner');page.goto(request_url)
    page.get_by_role('button',name='Submit for approval',exact=False).click();page.wait_for_load_state()
    capture('07-awaiting-approval')
    page.get_by_role('button',name='Approve',exact=False).filter(has_text='Approve').first.click()
    page.wait_for_load_state()
    for approver in ('demo.approver','demo.manager'):
        sign_in(approver);page.goto(request_url)
        page.get_by_role('button',name='Approve',exact=False).first.click();page.wait_for_load_state()
    page.get_by_text('All required approvers accepted this quotation.',exact=False).wait_for()
    sign_in('demo.sales');page.goto(request_url)
    page.locator('#next-status').select_option('booking');page.get_by_role('button',name='Update status',exact=True).click();page.wait_for_load_state()
    page.locator('#next-status').select_option('confirmed');page.locator('#booking-reference').fill('BROWSER-TEST-ONLY')
    page.get_by_role('button',name='Update status',exact=True).click();page.wait_for_load_state()
    page.get_by_text('BROWSER-TEST-ONLY',exact=True).wait_for();capture('08-confirmed-desktop')
    page.set_viewport_size({'width':390,'height':844});capture('09-confirmed-mobile')
    page.set_viewport_size({'width':1440,'height':1050})
    sign_in('demo.ceo')
    for name,url in [('10-team','/team/'),('11-operations','/operations/'),('12-accounting-unavailable','/accounting/')]:
        page.goto(BASE+url);capture(name)
    browser.close()

(OUTPUT/'browser-results.json').write_text(json.dumps({'errors':errors,'journey':'submitted → claimed → quoted → 3 approvals → booking → confirmed','request_url':request_url},indent=2))
if errors: raise SystemExit('\n'.join(errors))
print('Browser acceptance journey passed. Desktop/mobile screenshots saved in test-results/.')
