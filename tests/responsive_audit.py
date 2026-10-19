import asyncio, json, os
os.makedirs('shots', exist_ok=True)  # скриншоты (в .gitignore)
from playwright.async_api import async_playwright
B='http://localhost:8801'; W=[320,360,390,430,768,834,1024,1280,1440,1920]
PAGES={'home':'/','catalog':'/#/catalog','catalog-dir':'/#/catalog?dir=stationery','product':'/#/product/1','cart':'/#/cart','checkout':'/#/checkout','org':'/#/org','delivery':'/#/delivery','admin-login':'/admin/'}
async def main():
    res=[];small=[]
    async with async_playwright() as p:
        b=await p.chromium.launch()
        for w in W:
            ctx=await b.new_context(viewport={'width':w,'height':900},device_scale_factor=1,has_touch=w<1024,is_mobile=w<768)
            pg=await ctx.new_page()
            await pg.goto(B+'/'); await pg.evaluate("localStorage.setItem('lp_cart2',JSON.stringify({'1':2,'2':1,'12':3}))")
            for name,url in PAGES.items():
                await pg.goto(B+url); await pg.reload(); await pg.wait_for_timeout(700)
                sw=await pg.evaluate('document.documentElement.scrollWidth'); res.append((w,name,sw,sw<=w))
                if w in (320,390,768,1440) and name in ('home','catalog','cart','checkout','product'): await pg.screenshot(path=f'shots/{name}_{w}.png',full_page=(w<1440 or name!='home'))
                if w in (360,390) and name in ('home','catalog','product','cart'):
                    s=await pg.evaluate('''()=>[...document.querySelectorAll('button,a.btn,.ic,.q button,.fav,.chip,nav a,select,input[type=checkbox]')].filter(e=>e.offsetParent&&!e.disabled).map(e=>{const r=e.getBoundingClientRect();return [e.className||e.tagName,Math.round(r.width),Math.round(r.height),(e.textContent||e.getAttribute('aria-label')||'').trim().slice(0,20)]}).filter(x=>x[2]<36||x[1]<36)''')
                    small+= [(w,name)+tuple(x) for x in s]
            await ctx.close()
        await b.close()
    bad=[r for r in res if not r[3]]
    print('проверено сочетаний ширина×страница:',len(res),'| с горизонтальным переполнением:',len(bad),bad[:10])
    seen=set(); print('мелкие цели нажатия (<36px) на 360/390:')
    for s in small:
        k=s[2:]
        if k not in seen: seen.add(k); print('  ',s)
asyncio.run(main())
