"""
Scraper Aruba Fatturazione per GitHub Actions.
Scarica XLS inviate+ricevute → parse → push Supabase.
Credenziali via env vars: ARUBA_USER, ARUBA_PASS, SB_COORD_EMAIL, SB_COORD_PASS
"""
import asyncio, os, sys, zipfile, shutil, json
from pathlib import Path
from datetime import datetime

LOGIN_URL = 'https://fatturazioneelettronica.aruba.it'
OUTPUT_DIR = Path('_aruba_download')
TIMEOUT = 30000
SB_URL = 'https://gohtmuxaidwzijzrgzfh.supabase.co'
SB_KEY = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImdvaHRtdXhhaWR3emlqenJnemZoIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzQwODQzNzQsImV4cCI6MjA4OTY2MDM3NH0.TOVZgCuRiCk9B50zTd_BpOKZGpIaHEXFwA2L7TKFJVQ'

async def _login(page, user, pwd):
    await page.goto(LOGIN_URL, wait_until='load', timeout=60000)
    await page.wait_for_timeout(10000)
    # Debug: screenshot per capire cosa vede il browser da GitHub
    await page.screenshot(path='_aruba_download/debug_gh_login.png')
    print(f'  DEBUG URL dopo goto: {page.url}')
    print(f'  DEBUG title: {await page.title()}')
    # Aspetta che il form login appaia (redirect OAuth può essere lento su server remoti)
    try:
        await page.wait_for_selector('input[type="password"]', timeout=60000)
    except:
        # Se non appare, screenshot + dump HTML
        await page.screenshot(path='_aruba_download/debug_gh_timeout.png')
        html = await page.content()
        with open('_aruba_download/debug_gh_page.html', 'w') as f: f.write(html[:5000])
        raise
    await page.fill('input[type="password"]', pwd)
    await page.fill('input[name="username"], input[placeholder*="ARUBA"]', user)
    await page.click('button:has-text("Accedi")')
    await page.wait_for_function("() => window.location.hash.includes('dashboard')", timeout=TIMEOUT)
    await page.wait_for_timeout(5000)
    try: await page.locator('button:has-text("Accetta tutti")').click(timeout=3000); await page.wait_for_timeout(1000)
    except: pass
    await page.evaluate("""() => {
        const titles = document.querySelectorAll('*');
        for(const t of titles) {
            if(t.textContent.trim() === "Seleziona l'anno" && t.offsetHeight > 0 && t.tagName !== 'BODY') {
                let c = t.parentElement;
                for(let i = 0; i < 5; i++) {
                    if(!c) break;
                    const tools = c.querySelectorAll('.x-tool, [class*="tool-close"]');
                    for(const tool of tools) { if(tool.offsetHeight > 0) { tool.click(); return; } }
                    const btns = c.querySelectorAll('[class*="arubabutton"], .x-button');
                    for(const b of btns) { if(b.textContent.trim()==='CHIUDI' && b.offsetHeight > 0) { b.click(); return; } }
                    c = c.parentElement;
                }
            }
        }
    }""")
    await page.wait_for_timeout(2000)

async def _scarica(page, tipo, timestamp, mese='tutti'):
    try:
        menu_label = 'Fatture inviate' if tipo == 'inviate' else 'Fatture ricevute'
        await page.locator(f'role=menuitem[name="{menu_label}"]').click(force=True)
        await page.wait_for_timeout(5000)
        await page.evaluate("""() => { const al = document.querySelector('[aria-label="RICERCA AVANZATA"]'); if(al) { (al.closest('.x-button') || al).click(); } }""")
        await page.wait_for_timeout(3000)
        if mese != 'tutti':
            mese_label = 'Mese corrente' if mese == 'corrente' else 'Mese precedente' if mese == 'precedente' else mese
            await page.evaluate(f"""() => {{ const c = document.querySelectorAll('.x-combobox .x-expandtrigger'); if(c.length>=2) c[1].click(); }}""")
            await page.wait_for_timeout(1500)
            await page.evaluate(f"""() => {{ const items = document.querySelectorAll('.x-list-item,.x-dataview-item,.x-boundlistitem,[class*="listitem"]'); for(const it of items) {{ if(it.textContent.trim()==='{mese_label}' && it.offsetHeight>0) {{ it.click(); return; }} }} }}""")
            await page.wait_for_timeout(1000)
        await page.evaluate("""() => { const b = document.querySelectorAll('.x-button,[role="button"]'); for(const x of b) { if(x.textContent.trim()==='RICERCA' && x.offsetHeight>0) { x.click(); return; } } }""")
        await page.wait_for_timeout(4000)
        cb = await page.evaluate("() => { const c=document.querySelector('.x-checkcolumn'); if(!c) return null; const x=c.querySelector('.x-checkbox-el'); if(!x) return null; const r=x.getBoundingClientRect(); return {x:r.x+r.width/2,y:r.y+r.height/2}; }")
        if cb: await page.mouse.click(cb['x'], cb['y']); await page.wait_for_timeout(2000)
        await page.evaluate("() => { const b=document.querySelectorAll('.x-button'); for(const x of b) { if(x.textContent.includes('Seleziona tutti') && x.offsetHeight>0) { x.click(); return; } } }")
        await page.wait_for_timeout(1500)
        dd = await page.evaluate("() => { const c=document.querySelector('[id*=\"arubacomboboxcheck\"]'); if(!c) return null; const t=c.querySelector('.x-expandtrigger'); if(!t) return null; const r=t.getBoundingClientRect(); return {x:r.x+r.width/2,y:r.y+r.height/2}; }")
        if dd:
            await page.mouse.click(dd['x'], dd['y']); await page.wait_for_timeout(2000)
            rpt = await page.evaluate("() => { const i=document.querySelectorAll('.x-list-item,.x-dataview-item,.x-boundlistitem,[class*=\"listitem\"]'); for(const x of i) { if(x.textContent.trim().includes('Scarica Report Excel') && x.offsetHeight>0) { const r=x.getBoundingClientRect(); return {x:r.x+r.width/2,y:r.y+r.height/2}; } } return null; }")
            if rpt: await page.mouse.click(rpt['x'], rpt['y']); await page.wait_for_timeout(1500)
        app = await page.evaluate("() => { const b=document.querySelectorAll('.x-button,[role=\"button\"]'); for(const x of b) { if(x.textContent.trim()==='APPLICA' && x.offsetHeight>0) { const r=x.getBoundingClientRect(); return {x:r.x+r.width/2,y:r.y+r.height/2}; } } return null; }")
        async with page.expect_download(timeout=TIMEOUT) as dl_info:
            if app: await page.mouse.click(app['x'], app['y'])
        download = await dl_info.value
        zip_path = OUTPUT_DIR / download.suggested_filename
        await download.save_as(str(zip_path))
        xls_path = None
        if zip_path.suffix.lower() == '.zip':
            with zipfile.ZipFile(str(zip_path), 'r') as zf:
                for f in zf.filelist:
                    if f.filename.lower().endswith(('.xls', '.xlsx')):
                        zf.extract(f, str(OUTPUT_DIR))
                        final = OUTPUT_DIR / f'{timestamp}_Report{"FattureInviate" if tipo=="inviate" else "FattureRicevute"}.xls'
                        shutil.move(str(OUTPUT_DIR / f.filename), str(final))
                        xls_path = final; break
            zip_path.unlink()
        else: xls_path = zip_path
        return xls_path
    except Exception as e:
        print(f'  ERRORE {tipo}: {str(e)[:120]}')
        try: await page.screenshot(path=str(OUTPUT_DIR / f'error_{tipo}.png'))
        except: pass
        return None

def push_to_supabase(results):
    import xlrd, requests
    email = os.environ.get('SB_COORD_EMAIL', 'coordinatore1@eeseguo.it')
    pwd = os.environ.get('SB_COORD_PASS', 'Coordinatore2025!')
    login_r = requests.post(f'{SB_URL}/auth/v1/token?grant_type=password', json={'email': email, 'password': pwd}, headers={'apikey': SB_KEY, 'Content-Type': 'application/json'})
    login_r.raise_for_status()
    token = login_r.json()['access_token']
    user_id = login_r.json()['user']['id']
    headers = {'apikey': SB_KEY, 'Authorization': f'Bearer {token}', 'Content-Type': 'application/json', 'Prefer': 'return=minimal'}
    def excel_to_date(v):
        if not v: return None
        try: tup = xlrd.xldate_as_tuple(v, 0); return f'{tup[0]:04d}-{tup[1]:02d}-{tup[2]:02d}'
        except: return None
    def num(v):
        try: return float(v) if v else 0.0
        except: return 0.0
    summary = []
    if 'inviate' in results:
        wb = xlrd.open_workbook(str(results['inviate']))
        sh = wb.sheet_by_name('FattureInviate') if 'FattureInviate' in wb.sheet_names() else wb.sheet_by_index(0)
        h = {sh.cell_value(0, c): c for c in range(sh.ncols)}
        ex_r = requests.get(f'{SB_URL}/rest/v1/fatture_attive?select=numero,cliente,data_emissione', headers=headers)
        exist = set(f"{r['cliente']}|{r['numero']}|{r['data_emissione']}" for r in (ex_r.json() if ex_r.ok else []))
        rows = []
        for r in range(1, sh.nrows):
            cells = [sh.cell_value(r, c) for c in range(sh.ncols)]
            cl = str(cells[h.get('Cliente', 7)]).strip()
            if not cl: continue
            de = excel_to_date(cells[h.get('Data documento', 4)]); n = str(cells[h.get('Numero', 0)]).strip()
            imp = num(cells[h.get('Totale imponibile', 12)]); iva = num(cells[h.get('Totale IVA', 20)]); tot = num(cells[h.get('Totale documento', 21)])
            if tot == 0 and imp == 0: continue
            if f"{cl}|{n}|{de}" in exist: continue
            di = excel_to_date(cells[h.get('Data incasso', 24)]) if 'Data incasso' in h else None
            rows.append({'numero': n, 'data_emissione': de, 'data_pagamento': di, 'cliente': cl, 'descrizione': str(cells[h.get('Tipo documento', 5)]).strip(), 'imponibile': round(imp, 2), 'iva': round(iva, 2), 'totale': round(tot, 2), 'stato': 'pagata' if di else 'emessa', 'note': 'Importato da Aruba (GitHub Actions)', 'fonte': 'aruba', 'inserito_da': user_id})
        if rows:
            r = requests.post(f'{SB_URL}/rest/v1/fatture_attive', headers=headers, json=rows)
            summary.append(f'{len(rows)} attive' + ('' if r.ok else f' ERR:{r.status_code}'))
    if 'ricevute' in results:
        wb = xlrd.open_workbook(str(results['ricevute']))
        sh = wb.sheet_by_name('FattureRicevute') if 'FattureRicevute' in wb.sheet_names() else wb.sheet_by_index(0)
        h = {sh.cell_value(0, c): c for c in range(sh.ncols)}
        ex_r = requests.get(f'{SB_URL}/rest/v1/costi_mensili?select=num_fattura,fornitore,data_fattura&num_fattura=not.is.null', headers=headers)
        exist = set(f"{r['fornitore']}|{r['num_fattura']}|{r['data_fattura']}" for r in (ex_r.json() if ex_r.ok else []))
        rows = []
        for r in range(1, sh.nrows):
            cells = [sh.cell_value(r, c) for c in range(sh.ncols)]
            f = str(cells[h.get('Fornitore', 6)]).strip()
            if not f: continue
            dd = excel_to_date(cells[h.get('Data documento', 4)])
            if not dd: continue
            imp = num(cells[h.get('Totale imponibile', 10)])
            if imp == 0: continue
            n = str(cells[h.get('Numero', 0)]).strip()
            if f"{f}|{n}|{dd}" in exist: continue
            rows.append({'mese': dd[:7]+'-01', 'voce': f'{f} — {n or "(senza)"}', 'importo': round(imp, 2), 'note': f'Importato da Aruba (GitHub Actions)', 'categoria': 'Fattura passiva', 'fornitore': f, 'num_fattura': n or None, 'data_fattura': dd, 'fonte': 'aruba', 'inserito_da': user_id, 'match_banca': False})
        if rows:
            r = requests.post(f'{SB_URL}/rest/v1/costi_mensili', headers=headers, json=rows)
            summary.append(f'{len(rows)} passive' + ('' if r.ok else f' ERR:{r.status_code}'))
    return ' + '.join(summary) if summary else 'nessuna nuova fattura (dedup)'

async def run(mese='tutti'):
    from playwright.async_api import async_playwright
    user = os.environ.get('ARUBA_USER', '')
    pwd = os.environ.get('ARUBA_PASS', '')
    if not user or not pwd:
        print('ERRORE: settare ARUBA_USER e ARUBA_PASS come env vars o GitHub Secrets')
        sys.exit(1)
    OUTPUT_DIR.mkdir(exist_ok=True)
    ts = datetime.now().strftime('%Y%m%d_%H%M')
    results = {}
    async with async_playwright() as p:
        for tipo in ['ricevute', 'inviate']:
            print(f'[{tipo.upper()}]')
            browser = await p.chromium.launch(headless=True)
            ctx = await browser.new_context(accept_downloads=True)
            page = await ctx.new_page()
            page.set_default_timeout(TIMEOUT)
            print(f'  Login...'); await _login(page, user, pwd); print(f'  Login OK')
            xls = await _scarica(page, tipo, ts, mese=mese)
            if xls: results[tipo] = xls; print(f'  OK — {xls.name}')
            await browser.close()
    if results:
        print(f'\n[PUSH SUPABASE]')
        r = push_to_supabase(results)
        print(f'  {r}')
    print(f'\nDone.')

if __name__ == '__main__':
    mese = os.environ.get('MESE', 'tutti')
    for i, a in enumerate(sys.argv[1:]):
        if a == '--mese' and i + 2 <= len(sys.argv): mese = sys.argv[i + 2]
    asyncio.run(run(mese=mese))
