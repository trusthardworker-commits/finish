import asyncio, base64, io, json, re, sys
from playwright.async_api import async_playwright
from PIL import Image
B='http://localhost:8801'; PW='E2e-Passw0rd-xyz'; R=[]
def ok(name,cond,info=''):
    R.append((name,bool(cond),info)); print(('PASS' if cond else 'FAIL'),name,info,flush=True)
async def until(pg,expr,t=8):
    for _ in range(int(t*10)):
        try:
            if await pg.evaluate('()=>!!('+expr+')'): return True
        except Exception: pass
        await pg.wait_for_timeout(100)
    raise Exception('timeout: '+expr[:80])
def png(path):
    Image.new('RGB',(300,300),(30,120,200)).save(path)
async def main():
    async with async_playwright() as p:
        b=await p.chromium.launch()
        ctx=await b.new_context(viewport={'width':1440,'height':900}); pg=await ctx.new_page()
        errs=[]; pg.on('pageerror',lambda e:errs.append('pageerror '+str(e))); pg.on('console',lambda m:errs.append(m.text) if m.type=='error' else None)
        pg.on('dialog',lambda d:asyncio.ensure_future(d.accept()))
        # --- главная
        await pg.goto(B+'/'); await pg.wait_for_selector('.show .slide')
        ok('баннер: новый заголовок',(await pg.inner_text('.hero h1')).strip()=='Всё для речи и развития дошкольника')
        ok('старые панели категорий удалены',await pg.locator('.cats,.cat').count()==0)
        n=await pg.locator('.slide').count(); ok('витрина: карточки из БД',n>=10,f'{n} карточек')
        cats=await pg.eval_on_selector_all('.slide .dir','e=>e.map(x=>x.textContent)'); ok('витрина: категории не повторяются',len(cats)==len(set(cats)))
        ok('«Готовые комплекты»/«Оборудование» нигде на главной',not re.search('Готовые комплекты|Оборудование для кабинета',await pg.inner_text('body')))
        ok('кнопка влево отключена в начале',await pg.locator('[data-act=car][data-dir="-1"]').is_disabled())
        await pg.click('[data-act=car][data-dir="1"]'); await pg.wait_for_timeout(700)
        sl=await pg.evaluate('document.getElementById("track").scrollLeft'); ok('кнопка вправо листает ленту',sl>100,f'scrollLeft={sl}')
        ok('кнопка влево включилась',not await pg.locator('[data-act=car][data-dir="-1"]').is_disabled())
        await pg.click('[data-act=car][data-dir="-1"]'); await pg.wait_for_timeout(900)
        # конец ленты
        await pg.evaluate('(()=>{const t=document.getElementById("track");t.scrollLeft=t.scrollWidth})()'); await pg.wait_for_timeout(400)
        ok('кнопка вправо отключена в конце',await pg.locator('[data-act=car][data-dir="1"]').is_disabled())
        await pg.evaluate('document.getElementById("track").scrollLeft=0')
        ok('страница без горизонтального переполнения',await pg.evaluate('document.documentElement.scrollWidth<=innerWidth'))
        # --- количество до добавления
        first=pg.locator('.slide .pc').first; fid=await first.get_attribute('data-id')
        await first.locator('[data-act=inc]').click(); await first.locator('[data-act=inc]').click()
        ok('контрол количества на витрине: 3',(await first.locator('[data-qv]').inner_text())=='3')
        await first.locator('[data-act=add]').click(); ok('в корзину добавлено 3 шт.',(await pg.inner_text('#cc'))=='3')
        await first.locator('[data-act=dec]').click(); await first.locator('[data-act=dec]').click(); await first.locator('[data-act=dec]').click()
        ok('минимум количества = 1',(await first.locator('[data-qv]').inner_text())=='1')
        await first.locator('[data-act=add]').click(); ok('повторное добавление суммируется (4)',(await pg.inner_text('#cc'))=='4')
        # --- каталог по направлениям
        await pg.click('#nav a[data-n=stationery]'); await until(pg,'document.querySelector(".crumb") && document.querySelector(".crumb").textContent.includes("Канцелярия") && document.querySelector(".grid .pc")')
        dirs=set(await pg.eval_on_selector_all('.grid .pc .dir','e=>e.map(x=>x.title)')); ok('направление «Канцелярия» содержит только канцелярию',dirs=={'Канцелярия'},str(dirs))
        await pg.click('#nav a[data-n=logoped]'); await until(pg,'document.querySelector(".crumb") && document.querySelector(".crumb").textContent.includes("Логопедические") && document.querySelector(".grid .pc")')
        dirs=set(await pg.eval_on_selector_all('.grid .pc .dir','e=>e.map(x=>x.title)')); ok('направление «Логопедические товары» только логопедия',dirs=={'Логопедические товары'},str(dirs))
        await pg.goto(B+'/#/catalog'); await pg.wait_for_selector('.grid .pc'); await pg.wait_for_timeout(300)
        ok('пагинация есть (товаров > 12)',await pg.locator('.pg a').count()>=2)
        await pg.fill('#q','карандаш'); await pg.press('#q','Enter'); await until(pg,'document.querySelector(".grid .pc h3") && document.querySelector(".grid .pc h3").textContent.toLowerCase().includes("карандаш")')
        ok('поиск работает (регистр кириллицы)',True)
        await pg.fill('#q','zzzzqqq'); await pg.press('#q','Enter'); await until(pg,'document.querySelector(".ok2")'); ok('пустой результат поиска — аккуратное сообщение','Ничего не найдено' in await pg.inner_text('.ok2'))
        await pg.goto(B+'/#/catalog?dir=stationery'); await until(pg,'document.querySelectorAll(".grid .pc").length>0')
        await pg.fill('#flt [name=min]','150'); await pg.fill('#flt [name=max]','250'); await pg.press('#flt [name=max]','Tab'); await pg.wait_for_timeout(600)
        prices=await pg.eval_on_selector_all('.grid .pc .p','e=>e.map(x=>parseInt(x.textContent.replace(/\\s/g,"")))'); ok('фильтр по цене',prices and all(150<=x<=250 for x in prices),str(prices))
        await pg.select_option('#so','price_desc'); await pg.wait_for_timeout(600)
        prices=await pg.eval_on_selector_all('.grid .pc .p','e=>e.map(x=>parseInt(x.textContent.replace(/\\s/g,"")))'); ok('сортировка по убыванию цены',prices==sorted(prices,reverse=True),str(prices))
        # --- товар: максимум остатка, отсутствие
        await pg.goto(B+'/#/catalog?q=10721'); await until(pg,'document.querySelectorAll(".grid .pc").length===1 && document.querySelector(".pc .sk").textContent.includes("10721")'); c=pg.locator('.grid .pc').first
        for _ in range(9): await c.locator('[data-act=inc]').click()
        ok('количество не превышает остаток (5)',(await c.locator('[data-qv]').inner_text())=='5')
        await c.locator('[data-act=add]').click(); await c.locator('[data-act=add]').click(); await pg.wait_for_timeout(200)
        ok('повторное добавление сверх остатка отклонено',(await c.locator('[data-inc]').inner_text())=='В корзине: 5')
        await pg.goto(B+'/#/catalog?q=10903'); await until(pg,'document.querySelectorAll(".grid .pc").length===1 && document.querySelector(".pc .sk").textContent.includes("10903")'); ok('нет в наличии: кнопка отключена',await pg.locator('.grid .pc button:has-text("Нет в наличии")').is_disabled())
        await pg.goto(B+'/#/catalog?q=10721'); await until(pg,'document.querySelectorAll(".grid .pc").length===1 && document.querySelector(".pc .sk").textContent.includes("10721")'); await pg.click('.grid .pc a.im'); await pg.wait_for_selector('.pd h1')
        ok('страница товара открывается',True); await pg.click('[data-t=c]'); ok('вкладка «Характеристики» переключается','Артикул' in await pg.inner_text('#tp'))
        # --- корзина
        await pg.goto(B+'/#/cart'); await pg.wait_for_selector('.ci')
        rows=await pg.locator('.ci').count(); ok('корзина: позиции не дублируются',rows==2,f'{rows} строки')
        before=await pg.inner_text('.tot b'); await pg.locator('.ci [data-act=cinc]:not([disabled])').first.click(); await until(pg,'document.querySelector(".tot b").textContent!=%s'%json.dumps(before)); ok('итог пересчитывается при изменении количества',True)
        await pg.reload(); await pg.wait_for_selector('.ci'); ok('корзина восстанавливается после обновления',await pg.locator('.ci').count()==2)
        await pg.evaluate("localStorage.setItem('lp_cart2',JSON.stringify({'%s':9999,'999999':3,'abc':2}))"%fid); await pg.reload(); await pg.wait_for_selector('.ok2,.ci')
        st_=await pg.evaluate('()=>fetch("/api/catalog?q="+"%s").then(r=>r.json()).then(j=>j.items[0]&&j.items[0].max_qty)'%'')
        ok('подделанная корзина в localStorage приводится к реальным остаткам',await pg.locator('.ci:not(.bad)').count()==1 and int(await pg.inner_text('#cc'))<=99 and await pg.locator('.ci.bad').count()==1,'qty в бейдже='+await pg.inner_text('#cc'))
        await pg.evaluate("localStorage.setItem('lp_cart2',JSON.stringify({'%s':2}))"%fid); await pg.goto(B+'/#/cart'); await pg.reload(); await pg.wait_for_selector('.ci')
        await pg.click('[data-act=crm]'); await pg.wait_for_selector('.ok2'); ok('удаление позиции → пустая корзина',True)
        # --- заказ физлица
        await pg.goto(B+'/#/catalog?q=S-002'); await until(pg,'document.querySelectorAll(".grid .pc").length===1 && document.querySelector(".pc .sk").textContent.includes("S-002")'); await pg.locator('.grid .pc [data-act=add]').first.click()
        await pg.goto(B+'/#/checkout'); await pg.wait_for_selector('#fo'); await pg.click('#fo-btn'); ok('валидация формы: ошибки показаны',(await pg.inner_text('#e-name'))!='' and (await pg.inner_text('#e-consent'))!='')
        await pg.fill('#f-name','Тест Тестов'); await pg.fill('#f-phone','+7 900 111-22-33'); await pg.fill('#f-address','г. Москва, ул. Тестовая, 1'); await pg.check('#f-consent'); await pg.click('#fo-btn')
        await pg.wait_for_selector('.ok2 b'); num=await pg.inner_text('.ok2 b'); ok('заказ оформлен, номер с сервера',num.startswith('LP-'),num); ok('корзина очищена после заказа',(await pg.inner_text('#cc'))=='0')
        # --- заявка организации
        await pg.goto(B+'/#/org'); await pg.wait_for_selector('#fo'); ok('для организации видны поля ИНН/организации',await pg.locator('#f-inn').is_visible())
        await pg.fill('#f-org','МБДОУ Детский сад № 5'); await pg.fill('#f-inn','123'); await pg.fill('#f-name','Иванова М.С.'); await pg.fill('#f-phone','89001112233'); await pg.fill('#f-email','a@b.ru'); await pg.fill('#f-address','г. Москва, ул. Садовая, 5'); await pg.check('#f-consent'); await pg.click('#fo-btn')
        ok('неверный ИНН отклонён',(await pg.inner_text('#e-inn'))!=''); await pg.fill('#f-inn','7707083893'); await pg.click('#fo-btn')
        try:
            await pg.wait_for_selector('.ok2 b',timeout=8000); ok('заявка организации принята без товаров','Заявка принята' in await pg.inner_text('.ok2'))
        except Exception:
            print('DIAG fo-err:',await pg.evaluate('()=>{const e=document.getElementById("fo-err");return e&&e.textContent}'),'| errs:',await pg.evaluate('()=>[...document.querySelectorAll(".er")].map(x=>x.textContent).join("|")'),'| main:',(await pg.inner_text('main'))[:150]); ok('заявка организации принята без товаров',False)
        # --- сервер недоступен
        await pg.route('**/api/**',lambda r:r.abort()); await pg.goto(B+'/#/'); await pg.reload(); await pg.wait_for_selector('.warn'); ok('ошибка сети: понятное сообщение и «Повторить»','Нет связи' in await pg.inner_text('.warn') and await pg.locator('[data-act=retry]').count()==1); await pg.unroute('**/api/**')
        await pg.goto(B+'/#/nonexistent'); await pg.wait_for_selector('h1'); ok('несуществующая страница → 404-экран','не найдена' in (await pg.inner_text('h1')))
        # --- админка
        ap=await ctx.new_page(); ap.on('pageerror',lambda e:errs.append('admin pageerror '+str(e))); ap.on('console',lambda m:errs.append('admin '+m.text) if m.type=='error' else None); ap.on('dialog',lambda d:asyncio.ensure_future(d.accept()))
        await ap.goto(B+'/admin/'); await ap.wait_for_selector('.login'); ok('админка без входа показывает только форму входа',await ap.locator('.top').count()==0)
        await ap.fill('.login input[type=password]','wrong'); await ap.click('.login button'); await ap.wait_for_selector('.login .msg:not([hidden])'); ok('неверный пароль → ошибка',True)
        await ap.fill('.login input[type=password]',PW); await ap.click('.login button'); await ap.wait_for_selector('.top'); ok('вход в админку',True)
        await ap.click('.top button:has-text("Категории")'); await ap.wait_for_selector('table'); await ap.click('button:has-text("Новая категория")')
        await ap.fill('input[maxlength="150"]','Тестовая категория'); await ap.locator('.fg input').nth(1).fill('e2e-cat'); await ap.click('button[type=submit]'); await ap.wait_for_selector('td:has-text("e2e-cat")'); ok('категория создана',True)
        await ap.click('.top button:has-text("Товары")'); await ap.wait_for_selector('table'); await ap.click('button:has-text("Новый товар")')
        png('/tmp/e2e.png'); fg=ap.locator('.fg')
        await fg.locator('input').nth(0).fill('<img src=x onerror="window.__xss=1">Товар E2E'); await fg.locator('input').nth(1).fill('E2E-1'); await fg.locator('input').nth(2).fill('321.50'); await fg.locator('input').nth(3).fill('7')
        await fg.locator('select').nth(0).select_option(label=re.compile('e2e')) if False else None
        opt=await fg.locator('select').nth(0).locator('option:has-text("Тестовая категория")').get_attribute('value'); await fg.locator('select').nth(0).select_option(opt); await fg.locator('select').nth(1).select_option('published')
        await ap.set_input_files('input[type=file]','/tmp/e2e.png'); await ap.wait_for_selector('.imgs img'); ok('изображение загружено и показано',True)
        await ap.click('button[type=submit]'); await ap.wait_for_selector('.msg:has-text("сохранён")'); ok('товар сохранён',True)
        await pg.goto(B+'/#/catalog?cat=e2e-cat'); await until(pg,'document.querySelectorAll(".grid .pc").length===1'); ok('новый товар виден в публичном каталоге (цена 321,5 ₽)','321,5' in await pg.inner_text('.grid .pc .p'))
        ok('XSS в названии не исполняется (каталог)',await pg.evaluate('window.__xss===undefined') and await pg.locator('.grid .pc h3 img').count()==0)
        await pg.click('.grid .pc a.im'); await pg.wait_for_selector('.pd h1'); ok('XSS не исполняется (страница товара)',await pg.evaluate('window.__xss===undefined')); 
        im=await pg.locator('.pd .big img').get_attribute('src'); ok('загруженное изображение отдаётся с сервера (webp)',im.startswith('/uploads/') and im.endswith('.webp'),im)
        await ap.reload(); await ap.wait_for_selector('.top'); ok('сессия админки сохраняется после обновления',True)
        ok('XSS не исполняется в админке',await ap.evaluate('window.__xss===undefined'))
        await ap.click('.top button:has-text("Главная")'); await ap.wait_for_selector('form.card'); t=ap.locator('.fg input').first; await t.fill('Новый заголовок из CMS'); await ap.click('button[type=submit]'); await ap.wait_for_selector('.msg:has-text("сохранены")')
        await pg.goto(B+'/'); await pg.reload(); await pg.wait_for_selector('.hero h1'); ok('заголовок баннера меняется из CMS без правки HTML',(await pg.inner_text('.hero h1')).strip()=='Новый заголовок из CMS')
        await ap.click('.top button:has-text("Главная")'); await ap.wait_for_selector('form.card'); await ap.locator('.fg input').first.fill('Всё для речи и развития дошкольника'); await ap.click('button[type=submit]'); await ap.wait_for_selector('.msg:has-text("сохранены")')
        await ap.click('.top button:has-text("Заказы")'); await ap.wait_for_selector('tbody tr'); ok('список заказов в админке виден',await ap.locator('tbody tr').count()>=2)
        await ap.click('.top button:has-text("Выйти")'); await ap.wait_for_selector('.login'); await ap.goto(B+'/admin/'); await ap.wait_for_selector('.login'); ok('после выхода админка снова требует вход',await ap.locator('.top').count()==0)
        st=(await ctx.request.get(B+'/api/admin/products')).status; ok('после выхода админ-API → 401',st==401,str(st))
        csp=[e for e in errs if 'Content Security Policy' in e or 'Refused' in e]; ok('нет нарушений CSP',not csp,str(csp[:2]))
        other=[e for e in errs if e not in csp and 'Failed to load resource' not in e and 'ERR_FAILED' not in e and 'fonts.g' not in e]; ok('нет ошибок JS в консоли',not other,str(other[:3]))
        await ctx.close()
        # --- адаптивность
        await b.close()
    bad=[r for r in R if not r[1]]; print('\nИТОГО: %d проверок, %d провалено'%(len(R),len(bad)))
    json.dump(R,open('/home/claude/e2e_result.json','w'),ensure_ascii=False)
asyncio.run(main())
