(() => {
'use strict';
const $ = (s, r = document) => r.querySelector(s), $$ = (s, r = document) => [...r.querySelectorAll(s)];
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const rub = k => (k / 100).toLocaleString('ru-RU', { minimumFractionDigits: k % 100 ? 2 : 0, maximumFractionDigits: 2 }) + ' ₽';
const safeHref = h => /^(#|\/|https?:\/\/)/.test(h || '') ? h : '#/';
const store = { get(k, d) { try { return JSON.parse(localStorage.getItem(k)) ?? d; } catch (e) { return d; } }, set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch (e) { /* хранилище недоступно — корзина живёт до перезагрузки */ } } };
const clampInt = (v, lo, hi) => Math.min(hi, Math.max(lo, parseInt(v, 10) || lo));
// В localStorage — только «id → количество». Цены, остатки и суммы приходят с сервера и не хранятся.
const loadCart = () => { const o = store.get('lp_cart2', {}), r = {}; for (const [k, v] of Object.entries(o)) if (/^\d{1,9}$/.test(k) && Number.isInteger(v) && v > 0) r[k] = Math.min(v, 99); return r; };
let cart = loadCart(), fav = (store.get('lp_fav2', []) || []).filter(Number.isInteger);
const app = $('#app');
const motion = () => matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth';

async function api(path, opt = {}) {
  let r;
  try { r = await fetch('/api' + path, { method: opt.method || 'GET', headers: opt.body ? { 'Content-Type': 'application/json' } : {}, body: opt.body ? JSON.stringify(opt.body) : undefined, credentials: 'same-origin' }); }
  catch (e) { throw { msg: 'Нет связи с сервером. Проверьте интернет и попробуйте ещё раз.' }; }
  let d = {}; try { d = await r.json(); } catch (e) { /* пустой ответ */ }
  if (!r.ok) throw { status: r.status, msg: d.error || 'Ошибка сервера', data: d };
  return d;
}

function saveCart() { store.set('lp_cart2', cart); store.set('lp_fav2', fav); badges(); }
function badges() {
  const n = Object.values(cart).reduce((a, b) => a + b, 0);
  $('#cc').textContent = n; $('#fc').textContent = fav.length;
  $('#ct').setAttribute('aria-label', `Корзина, товаров: ${n}`); $('#fv').setAttribute('aria-label', `Избранное: ${fav.length}`);
  $$('[data-inc]').forEach(e => { const q = cart[e.dataset.inc]; e.textContent = q ? `В корзине: ${q}` : ''; });
}
let toastT;
function toast(msg) {
  let t = $('#toast'); if (!t) { t = document.createElement('div'); t.id = 'toast'; t.setAttribute('role', 'status'); document.body.appendChild(t); }
  t.textContent = msg; t.classList.add('show'); clearTimeout(toastT); toastT = setTimeout(() => t.classList.remove('show'), 2600);
}
function setMeta(title, desc) {
  document.title = title ? `${title} — Лавка логопеда` : 'Лавка логопеда — товары для логопедов и канцелярия';
  const m = $('meta[name=description]'); if (m) m.content = desc || 'Интернет-магазин «Лавка логопеда»: логопедические товары и канцелярия.';
}

// ---------------------------------------------------------------- компоненты
const hue = id => [210, 25, 150, 270, 40, 190][id % 6];
const img = (p, big) => p.images && p.images[0]
  ? `<img src="${esc(p.images[0])}" alt="${esc(p.name)}" loading="${big ? 'eager' : 'lazy'}" decoding="async" width="400" height="400">`
  : `<svg viewBox="0 0 200 200" role="img" aria-label="Фото товара «${esc(p.name)}» пока не добавлено"><rect width="200" height="200" fill="#EEF7FF"/><rect x="40" y="52" width="120" height="96" rx="12" fill="hsl(${hue(p.id)} 55% 42%)"/><circle cx="82" cy="92" r="15" fill="#fff" opacity=".9"/><rect x="106" y="80" width="38" height="12" rx="6" fill="#fff" opacity=".8"/><rect x="106" y="100" width="28" height="12" rx="6" fill="#fff" opacity=".6"/><text x="100" y="176" font-size="11" text-anchor="middle" fill="#5b7391" font-family="Arial">фото не добавлено</text></svg>`;
const qctl = (val = 1) => `<span class="q" data-q><button type="button" data-act="dec" aria-label="Уменьшить количество">−</button><output data-qv>${val}</output><button type="button" data-act="inc" aria-label="Увеличить количество">+</button></span>`;
const stock = p => p.in_stock ? '<span class="ok">● В наличии</span>' : '<span class="no">● Нет в наличии</span>';
function card(p) {
  const f = fav.includes(p.id);
  return `<article class="pc" data-id="${p.id}"><button type="button" class="fav${f ? ' on' : ''}" data-act="fav" data-id="${p.id}" aria-pressed="${f}" aria-label="${f ? 'Убрать из избранного' : 'В избранное'}">${f ? '♥' : '♡'}</button>
<a class="im" href="#/product/${p.id}">${img(p)}</a><span class="dir" title="${esc(p.category.direction_name)}">${esc(p.category.name)}</span>
<h3><a href="#/product/${p.id}">${esc(p.name)}</a></h3><span class="sk">Артикул: ${esc(p.sku)}</span><span class="p">${rub(p.price_kop)}</span>${stock(p)}
<div class="row">${p.in_stock ? `${qctl()}<button type="button" class="btn o s" data-act="add" data-id="${p.id}" data-max="${p.max_qty}" data-name="${esc(p.name)}">В корзину</button>` : '<button type="button" class="btn s" disabled>Нет в наличии</button>'}</div>
<span class="inc" data-inc="${p.id}">${cart[p.id] ? `В корзине: ${cart[p.id]}` : ''}</span></article>`;
}
const paras = t => t ? t.split(/\n{2,}/).map(x => `<p>${esc(x).replace(/\n/g, '<br>')}</p>`).join('') : '';
const errBox = e => `<div class="warn" role="alert">${esc(e.msg || 'Что-то пошло не так')}</div><p><button type="button" class="btn l s" data-act="retry">Повторить</button></p>`;

// ---------------------------------------------------------------- страницы
async function home() {
  const d = await api('/home'), s = d.settings, hero = s.hero_image || 'assets/hero.webp';
  setMeta('', s.hero_sub);
  const showcase = !s.showcase_enabled ? '' : `<section class="show" aria-labelledby="sh-t"><div class="sh-head"><h2 id="sh-t">${esc(s.showcase_title)}</h2>
<div class="car-nav"><button type="button" class="ic-b" data-act="car" data-dir="-1" aria-label="Листать влево" disabled>‹</button><button type="button" class="ic-b" data-act="car" data-dir="1" aria-label="Листать вправо">›</button></div></div>
${d.showcase.length ? `<div class="track" id="track" tabindex="0" role="region" aria-label="Лента товаров, листайте стрелками или свайпом">${d.showcase.map(p => `<div class="slide">${card(p)}</div>`).join('')}</div>` : '<div class="ok2">Товары скоро появятся.</div>'}
<div class="center"><a class="btn o" href="#/catalog">Перейти в каталог</a></div></section>`;
  app.innerHTML = `<section class="hero"><div class="t"><h1>${esc(s.hero_title)}</h1><p>${esc(s.hero_sub)}</p><div class="r"><a class="btn o" href="${esc(safeHref(s.hero_btn_link))}">${esc(s.hero_btn_text)} →</a>${s.hero_btn2_text ? `<a class="btn l" href="${esc(safeHref(s.hero_btn2_link))}">${esc(s.hero_btn2_text)}</a>` : ''}</div></div>
<div class="hi"><img src="${esc(hero)}" alt="Улыбающаяся девочка за столом с книгами, карточками и развивающими играми" width="1000" height="658" fetchpriority="high"></div></section>
${showcase}
<section class="dirs" aria-label="Направления магазина"><a class="dir-card" href="#/catalog?dir=logoped"><b>Логопедические товары</b><span>Пособия, карточки, игры, зонды и книги для развития речи</span></a><a class="dir-card" href="#/catalog?dir=stationery"><b>Канцелярия</b><span>Бумага, альбомы, карандаши, краски и всё для творчества</span></a></section>
<section class="dou"><div><h2>Для детских садов и организаций</h2><p>Закупка по списку или спецификации, счёт для юридического лица, помощь с подбором. Условия оплаты и поставки согласует менеджер.</p><a class="btn o s" href="#/org">Оставить заявку</a> <a class="btn l s" href="#/page/kindergarten">Подробнее об условиях</a></div><div class="adv"><div>📄 Заказ по списку или спецификации</div><div>🧾 Счёт для юридического лица</div><div>📑 Документы для закупки</div><div>🧭 Помощь с подбором комплектации</div></div></section>
<h2 class="h2">Как оформить заказ</h2><section class="steps">${[['Выберите товары', 'Добавьте нужные позиции в корзину.'], ['Укажите данные', 'Заполните форму; для организации — реквизиты.'], ['Согласуйте условия', 'Менеджер уточнит стоимость, доставку и документы.'], ['Получите заказ', 'Доставка или самовывоз по согласованию.']].map((x, i) => `<div class="st"><b>${i + 1}</b><h3>${x[0]}</h3><p>${x[1]}</p></div>`).join('')}</section>`;
  initTrack();
}
function initTrack() {
  const tr = $('#track'); if (!tr) return;
  const upd = () => { const [l, r] = $$('[data-act=car]'); l.disabled = tr.scrollLeft < 4; r.disabled = tr.scrollLeft + tr.clientWidth >= tr.scrollWidth - 4; };
  let raf; tr.addEventListener('scroll', () => { cancelAnimationFrame(raf); raf = requestAnimationFrame(upd); }, { passive: true });
  addEventListener('resize', upd); upd();
}

const P = {};  // параметры каталога
async function catalog(qs) {
  const sp = new URLSearchParams(qs), dir = sp.get('dir') || '', cat = sp.get('cat') || '', q = sp.get('q') || '', fv = sp.get('fav') === '1';
  const min = sp.get('min') || '', max = sp.get('max') || '', inst = sp.get('instock') === '1', sort = sp.get('sort') || 'popular', page = Math.max(1, parseInt(sp.get('page')) || 1);
  const cq = new URLSearchParams({ sort, page, per: 12 }); [['dir', dir], ['cat', cat], ['q', q], ['min', min], ['max', max]].forEach(([k, v]) => v && cq.set(k, v)); if (inst) cq.set('instock', '1');
  if (fv && fav.length) cq.set('ids', fav.join(','));
  const noFav = fv && !fav.length;
  const [cats, list] = await Promise.all([api('/categories'), noFav ? Promise.resolve({ items: [], total: 0, page: 1, pages: 1 }) : api('/catalog?' + cq)]);
  const dn = Object.fromEntries(cats.directions.map(d => [d.id, d.name])), curCat = cats.categories.find(c => c.slug === cat);
  const link = o => '#/catalog?' + new URLSearchParams(Object.fromEntries(Object.entries({ dir, cat, q, min, max, instock: inst ? '1' : '', sort: sort === 'popular' ? '' : sort, fav: fv ? '1' : '', ...o }).filter(([, v]) => v)));
  const title = fv ? 'Избранное' : curCat ? curCat.name : dir ? dn[dir] : 'Все товары';
  setMeta(title, curCat && curCat.description);
  const groups = cats.directions.map(d => { const cs = cats.categories.filter(c => c.direction === d.id); return cs.length ? `<div class="bx"><h3>${esc(d.name)}</h3><a href="${link({ dir: d.id, cat: '', page: '' })}" class="${dir === d.id && !cat ? 'on' : ''}">Все в разделе</a>${cs.map(c => `<a href="${link({ dir: c.direction, cat: c.slug, page: '' })}" class="${cat === c.slug ? 'on' : ''}">${esc(c.name)}<span>${c.count}</span></a>`).join('')}</div>` : ''; }).join('');
  const chips = [['', '', 'Все'], ...cats.directions.map(d => [d.id, '', d.name]), ...cats.categories.filter(c => !dir || c.direction === dir).map(c => [c.direction, c.slug, c.name])].map(([d, c, n]) => `<a class="chip${(d === dir && c === cat) ? ' on' : ''}" href="${link({ dir: d, cat: c, page: '' })}">${esc(n)}</a>`).join('');
  const pages = list.pages > 1 ? `<nav class="pg" aria-label="Страницы">${Array.from({ length: list.pages }, (_, i) => `<a href="${link({ page: i + 1 > 1 ? i + 1 : '' })}" ${i + 1 === list.page ? 'aria-current="page" class="on"' : ''}>${i + 1}</a>`).join('')}</nav>` : '';
  app.innerHTML = `<p class="crumb"><a href="#/">Главная</a> › <a href="#/catalog">Каталог</a>${dir ? ` › <a href="${link({ cat: '', page: '' })}">${esc(dn[dir])}</a>` : ''}${curCat ? ' › ' + esc(curCat.name) : ''}</p>
<div class="cl"><aside class="side" id="side"><div class="bx"><h3>Направления</h3><a href="#/catalog" class="${!dir && !cat && !fv ? 'on' : ''}">Весь каталог</a></div>${groups}
<div class="bx"><h3>Фильтры</h3><form id="flt" data-base="${esc(link({ min: '', max: '', instock: '', page: '' }))}"><b class="lbl">Цена, ₽</b><div class="pr"><input name="min" type="number" min="0" inputmode="numeric" placeholder="от" aria-label="Цена от" value="${esc(min)}"><input name="max" type="number" min="0" inputmode="numeric" placeholder="до" aria-label="Цена до" value="${esc(max)}"></div>
<label class="chk"><input type="checkbox" name="instock" ${inst ? 'checked' : ''}> Только в наличии</label><button type="button" class="btn l s full" data-act="reset" data-href="${esc(link({ min: '', max: '', instock: '', q: '', page: '' }))}">Сбросить фильтры</button></form></div></aside>
<section><div class="mchips">${chips}</div><button type="button" class="btn l s mft" data-act="filters" aria-expanded="false" aria-controls="side">Фильтры</button><h1 class="h1">${esc(title)}</h1>${q ? `<p class="note">Поиск: «${esc(q)}»</p>` : ''}
<div class="bar"><span>Найдено: ${list.total}</span><label class="sr"><span class="sr-t">Сортировка</span> <select id="so" data-base="${esc(link({ sort: '', page: '' }))}"><option value="popular">По популярности</option><option value="price_asc"${sort === 'price_asc' ? ' selected' : ''}>Сначала дешевле</option><option value="price_desc"${sort === 'price_desc' ? ' selected' : ''}>Сначала дороже</option><option value="new"${sort === 'new' ? ' selected' : ''}>Новинки</option><option value="name"${sort === 'name' ? ' selected' : ''}>По названию</option></select></label></div>
${list.items.length ? `<div class="grid">${list.items.map(card).join('')}</div>${pages}` : `<div class="ok2">${fv ? 'В избранном пока ничего нет.' : 'Ничего не найдено. Измените запрос или фильтры.'}<p><a class="btn o s" href="#/catalog">Весь каталог</a></p></div>`}</section></div>`;
}

async function product(id) {
  const p = await api('/product/' + id), sel = 0;
  setMeta(p.name, p.description.slice(0, 160));
  const f = fav.includes(p.id);
  app.innerHTML = `<p class="crumb"><a href="#/">Главная</a> › <a href="#/catalog">Каталог</a> › <a href="#/catalog?dir=${esc(p.category.direction)}">${esc(p.category.direction_name)}</a> › <a href="#/catalog?cat=${esc(p.category.slug)}">${esc(p.category.name)}</a> › ${esc(p.name)}</p>
<div class="pd" data-id="${p.id}"><div><div class="big" id="big">${img(p, true)}</div>${p.images.length > 1 ? `<div class="thumbs">${p.images.map((s, i) => `<button type="button" data-act="thumb" data-src="${esc(s)}" aria-label="Фото ${i + 1}"><img src="${esc(s)}" alt="" loading="lazy" width="64" height="64"></button>`).join('')}</div>` : ''}</div>
<div><h1>${esc(p.name)}</h1><span class="sk">Артикул: ${esc(p.sku)}</span><div class="p">${rub(p.price_kop)}</div>${stock(p)}${p.demo ? ' <small>(демонстрационные данные)</small>' : ''}
<div class="row" style="margin-top:18px">${p.in_stock ? `${qctl()}<button type="button" class="btn o" data-act="add" data-id="${p.id}" data-max="${p.max_qty}" data-name="${esc(p.name)}">В корзину</button>` : '<button type="button" class="btn" disabled>Нет в наличии</button>'}<button type="button" class="btn l" data-act="fav" data-id="${p.id}" aria-pressed="${f}">${f ? '♥ В избранном' : '♡ В избранное'}</button></div><span class="inc" data-inc="${p.id}">${cart[p.id] ? `В корзине: ${cart[p.id]}` : ''}</span></div></div>
<div class="tabs" role="tablist"><button type="button" role="tab" class="on" data-act="tab" data-t="d" aria-selected="true">Описание</button><button type="button" role="tab" data-act="tab" data-t="c" aria-selected="false">Характеристики</button><button type="button" role="tab" data-act="tab" data-t="r" aria-selected="false">Отзывы</button></div>
<div class="tp" id="tp" role="tabpanel"></div>
${p.similar.length ? `<h2 class="h2">Похожие товары</h2><div class="grid sim">${p.similar.map(card).join('')}</div>` : ''}`;
  const T = { d: p.description ? paras(p.description) : '<p>Описание пока не добавлено.</p>', c: `<dl><dt>Артикул</dt><dd>${esc(p.sku)}</dd><dt>Направление</dt><dd>${esc(p.category.direction_name)}</dd><dt>Категория</dt><dd>${esc(p.category.name)}</dd></dl>`, r: '<p>Отзывов пока нет.</p>' };
  const show = k => { $('#tp').innerHTML = T[k]; $$('.tabs button').forEach(b => { const on = b.dataset.t === k; b.classList.toggle('on', on); b.setAttribute('aria-selected', on); }); };
  $$('.tabs button').forEach(b => b.addEventListener('click', () => show(b.dataset.t))); show('d');
}

async function quote() {
  const items = Object.entries(cart).map(([id, qty]) => ({ id: +id, qty }));
  if (!items.length) return { lines: [], total_kop: 0 };
  const q = await api('/cart/quote', { method: 'POST', body: { items } });
  const next = {}; q.lines.forEach(l => { if (l.available) next[l.id] = l.qty; });  // корзина подгоняется под реальные остатки
  cart = next; saveCart(); return q;
}
const lineRow = l => !l.available ? `<div class="ci bad"><div class="nm"><b>Товар №${l.id}</b><br><span class="no">${esc(l.note)}</span></div></div>` :
  `<div class="ci" data-id="${l.id}"><a class="im" href="#/product/${l.id}">${img({ id: l.id, name: l.name, images: l.image ? [l.image] : [] })}</a><div class="nm"><a href="#/product/${l.id}"><b>${esc(l.name)}</b></a><br><small class="sk">Артикул: ${esc(l.sku)}</small>${l.note ? `<br><span class="no">${esc(l.note)}</span>` : ''}</div>
<span class="unit">${rub(l.price_kop)}</span><span class="q" data-q data-max="${l.max_qty}"><button type="button" data-act="cdec" data-id="${l.id}" aria-label="Уменьшить количество">−</button><output>${l.qty}</output><button type="button" data-act="cinc" data-id="${l.id}" aria-label="Увеличить количество"${l.qty >= l.max_qty ? ' disabled' : ''}>+</button></span><b class="sum">${rub(l.line_kop)}</b><button type="button" class="x" data-act="crm" data-id="${l.id}" aria-label="Удалить ${esc(l.name)}">✕</button></div>`;
async function cartPage() {
  setMeta('Корзина');
  const q = await quote(), shown = q.lines;
  app.innerHTML = `<h1 class="h1">Корзина</h1>` + (!shown.length ? '<div class="ok2">Корзина пуста.<p><a class="btn o s" href="#/catalog">Перейти в каталог</a></p></div>' :
    `<div class="bx nopad">${shown.map(lineRow).join('')}</div><div class="tot"><a href="#/catalog" class="back">← Продолжить покупки</a><button type="button" class="btn l s" data-act="cclear">Очистить корзину</button><span>Итого: <b>${rub(q.total_kop)}</b></span><a class="btn o" href="#/checkout">Оформить заказ</a></div><p class="note">Цены и наличие проверяются на сервере при оформлении заказа.</p>`);
}

let idem = '', btype = 'p';
async function checkout(type) {
  btype = type; idem = crypto.randomUUID ? crypto.randomUUID() : String(Date.now()) + Math.random().toString(16).slice(2);
  const q = await quote(), org = type !== 'p';
  setMeta(org ? 'Заявка для организации' : 'Оформление заказа');
  app.innerHTML = `<h1 class="h1">${org ? 'Заявка для организации' : 'Оформление заказа'}</h1>
<div class="seg" role="group" aria-label="Покупатель"><button type="button" data-act="btype" data-k="p" aria-pressed="${type === 'p'}" class="${type === 'p' ? 'on' : ''}">Физическое лицо</button><button type="button" data-act="btype" data-k="u" aria-pressed="${type === 'u'}" class="${type === 'u' ? 'on' : ''}">Юридическое лицо / ИП</button><button type="button" data-act="btype" data-k="d" aria-pressed="${type === 'd'}" class="${type === 'd' ? 'on' : ''}">Детский сад / бюджетное учреждение</button></div>
<form id="fo" class="fm" data-type="${type}" novalidate>
${[['org', 'Полное наименование организации *', 1, 'f'], ['inn', 'ИНН *', 1, ''], ['kpp', 'КПП', 1, ''], ['name', '<span class="n-p">Имя *</span><span class="n-o">Контактное лицо (ФИО) *</span>', 0, ''], ['position', 'Должность', 1, ''], ['phone', 'Телефон *', 0, ''], ['email', '<span class="e-p">E-mail</span><span class="e-o">E-mail *</span>', 0, ''], ['address', 'Адрес доставки *', 0, 'f']].map(([n, l, o, f]) => `<div class="fl ${f} ${o ? 'org-only' : ''}"><label for="f-${n}">${l}</label><input id="f-${n}" name="${n}" ${n === 'phone' ? 'type="tel" autocomplete="tel"' : n === 'email' ? 'type="email" autocomplete="email"' : 'type="text"'} maxlength="300" aria-describedby="e-${n}"><span class="er" id="e-${n}" role="alert"></span></div>`).join('')}
<div class="fl"><label for="f-delivery">Доставка</label><select id="f-delivery" name="delivery"><option>Способ уточнит менеджер</option><option>Самовывоз</option><option>Курьер / транспортная компания</option></select></div>
<div class="fl f"><label for="f-comment">Комментарий</label><textarea id="f-comment" name="comment" rows="3" maxlength="2000"></textarea></div>
<div class="f"><b>Состав заказа:</b> ${q.lines.length ? `<ul class="olist">${q.lines.filter(l => l.available).map(l => `<li>${esc(l.name)} × ${l.qty} — ${rub(l.line_kop)}</li>`).join('')}</ul>` : '<span>корзина пуста</span>'}<p><b>Итого: ${rub(q.total_kop)}</b> <span class="org-only">— окончательную стоимость, поставку и документы согласует менеджер</span></p></div>
<div class="f"><label class="chk"><input type="checkbox" name="consent" id="f-consent"> Согласен на обработку персональных данных (<a href="#/page/privacy" target="_blank" rel="noopener">политика</a>) *</label><span class="er" id="e-consent" role="alert"></span></div>
<div class="f"><div class="warn" id="fo-err" role="alert" hidden></div><button class="btn o" type="submit" id="fo-btn">${org ? 'Отправить заявку' : 'Подтвердить заказ'}</button></div></form>`;
  $('#fo').addEventListener('submit', submitOrder);
}
async function submitOrder(e) {
  e.preventDefault();
  const f = e.target, org = f.dataset.type !== 'p', v = n => (f.elements[n]?.value || '').trim(); let ok = true, first = null;
  const bad = (n, m) => { $('#e-' + n).textContent = m; if (m) { ok = false; first = first || f.elements[n]; } };
  ['org', 'inn', 'name', 'phone', 'email', 'address', 'consent'].forEach(n => bad(n, ''));
  if (org && v('org').length < 2) bad('org', 'Укажите название организации');
  if (org && !/^(\d{10}|\d{12})$/.test(v('inn'))) bad('inn', 'ИНН: 10 или 12 цифр');
  if (v('name').length < 2) bad('name', 'Укажите имя');
  if (v('phone').replace(/\D/g, '').length < 10) bad('phone', 'Введите телефон полностью');
  if ((org || v('email')) && !/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(v('email'))) bad('email', 'Проверьте e-mail');
  if ((org || f.elements.delivery.value !== 'Самовывоз') && v('address').length < 5) bad('address', 'Укажите адрес доставки');
  if (!f.elements.consent.checked) bad('consent', 'Необходимо согласие');
  if (!ok) { first && first.focus(); return; }
  const btn = $('#fo-btn'), box = $('#fo-err'); btn.disabled = true; box.hidden = true;
  try {
    const r = await api('/orders', { method: 'POST', body: { idem_key: idem, buyer_type: f.dataset.type, consent: true, items: Object.entries(cart).map(([id, qty]) => ({ id: +id, qty })), customer: { name: v('name'), phone: v('phone'), email: v('email'), address: v('address'), org: v('org'), inn: v('inn'), kpp: v('kpp'), position: v('position'), delivery: v('delivery'), comment: v('comment') } } });
    cart = {}; saveCart();
    app.innerHTML = `<div class="ok2"><h1 class="h1">${org ? 'Заявка принята' : 'Заказ оформлен'}</h1><p>Номер: <b>${esc(r.number)}</b>. Сумма: <b>${rub(r.total_kop)}</b>.</p><p>${org ? 'Менеджер свяжется с вами для согласования счёта, условий поставки и документов.' : 'Менеджер свяжется с вами для подтверждения заказа.'} Онлайн-оплата не подключена: способ оплаты согласуется отдельно.</p><a class="btn o" href="#/catalog">В каталог</a></div>`;
  } catch (er) {
    box.textContent = er.msg; box.hidden = false; btn.disabled = false;
    if (er.status === 409) { await quote(); toast('Корзина обновлена по актуальным остаткам'); }
  }
}
async function infoPage(key, title) {
  const d = await api('/page/' + key); setMeta(title);
  app.innerHTML = `<h1 class="h1">${esc(title)}</h1><div class="tp wide">${d.text ? paras(d.text) : '<div class="warn">Раздел ещё не заполнен владельцем магазина (редактируется в админке).</div>'}</div>`;
}
const notFound = () => { setMeta('Страница не найдена'); app.innerHTML = '<h1 class="h1">Страница не найдена</h1><p><a class="btn o s" href="#/">На главную</a></p>'; };

// ---------------------------------------------------------------- маршрутизация
let rid = 0;
async function route() {
  const my = ++rid, h = location.hash.slice(1) || '/', [path, qs] = h.split('?'), s = path.split('/').filter(Boolean);
  $('#nav').classList.remove('open'); $('#bg').setAttribute('aria-expanded', 'false');
  const nav = s[0] === 'catalog' ? (new URLSearchParams(qs).get('dir') || 'catalog') : s[0] === 'page' ? s[1] : s[0];
  $$('#nav a').forEach(a => a.classList.toggle('on', a.dataset.n === nav));
  app.setAttribute('aria-busy', 'true');
  try {
    const T = { about: 'О нас', delivery: 'Доставка и оплата', contacts: 'Контакты', privacy: 'Политика обработки персональных данных', kindergarten: 'Для детских садов и организаций' };
    if (!s.length) await home();
    else if (s[0] === 'catalog') await catalog(qs);
    else if (s[0] === 'product' && /^\d+$/.test(s[1] || '')) await product(s[1]);
    else if (s[0] === 'cart') await cartPage();
    else if (s[0] === 'checkout') await checkout('p');
    else if (s[0] === 'org') await checkout('d');
    else if (T[s[0]]) await infoPage(s[0], T[s[0]]);
    else if (s[0] === 'page' && T[s[1]]) await infoPage(s[1], T[s[1]]);
    else notFound();
    if (my === rid) { scrollTo(0, 0); badges(); }
  } catch (e) {
    if (my !== rid) return;
    if (e.status === 404) notFound(); else app.innerHTML = errBox(e);
  } finally { if (my === rid) app.removeAttribute('aria-busy'); }
}

// ---------------------------------------------------------------- события
document.addEventListener('click', async ev => {
  const b = ev.target.closest('[data-act]'); if (!b) return;
  const a = b.dataset.act, id = +b.dataset.id;
  if (a === 'dec' || a === 'inc') {
    const q = b.closest('[data-q]'), out = $('[data-qv]', q), max = +(q.closest('.pc,.pd')?.querySelector('[data-act=add]')?.dataset.max || 99);
    out.textContent = clampInt(+out.textContent + (a === 'inc' ? 1 : -1), 1, max);
  } else if (a === 'add') {
    const root = b.closest('.pc,.pd'), qty = clampInt($('[data-qv]', root).textContent, 1, 99), max = +b.dataset.max, cur = cart[id] || 0, next = Math.min(cur + qty, max);
    if (next <= cur) return toast('В корзине уже максимум доступного количества');
    cart[id] = next; saveCart(); toast(next < cur + qty ? `Добавлено ${next - cur} шт. — больше нет в наличии` : 'Товар добавлен в корзину');
  } else if (a === 'fav') {
    fav = fav.includes(id) ? fav.filter(x => x !== id) : [...fav, id]; saveCart();
    $$(`[data-act=fav][data-id="${id}"]`).forEach(x => { const on = fav.includes(id); x.setAttribute('aria-pressed', on); if (x.classList.contains('fav')) { x.classList.toggle('on', on); x.textContent = on ? '♥' : '♡'; x.setAttribute('aria-label', on ? 'Убрать из избранного' : 'В избранное'); } else x.textContent = on ? '♥ В избранном' : '♡ В избранное'; });
    if (location.hash.includes('fav=1')) route();
  } else if (a === 'cinc' || a === 'cdec' || a === 'crm' || a === 'cclear') {
    if (a === 'cclear') { if (!confirm('Очистить корзину?')) return; cart = {}; } else if (a === 'crm') delete cart[id]; else { const n = (cart[id] || 0) + (a === 'cinc' ? 1 : -1); if (n < 1) delete cart[id]; else cart[id] = Math.min(n, 99); }
    saveCart(); cartPage().catch(e => { app.innerHTML = errBox(e); });
  } else if (a === 'car') { const tr = $('#track'); tr.scrollBy({ left: +b.dataset.dir * Math.max(240, tr.clientWidth * .85), behavior: motion() }); }
  else if (a === 'thumb') { $('#big').innerHTML = `<img src="${esc(b.dataset.src)}" alt="" width="600" height="600">`; }
  else if (a === 'btype') { const f = $('#fo'); f.dataset.type = btype = b.dataset.k; $$('.seg button').forEach(x => { x.classList.toggle('on', x === b); x.setAttribute('aria-pressed', x === b); }); $('h1').textContent = b.dataset.k === 'p' ? 'Оформление заказа' : 'Заявка для организации'; $('#fo-btn').textContent = b.dataset.k === 'p' ? 'Подтвердить заказ' : 'Отправить заявку'; }
  else if (a === 'menu') { const n = $('#nav'), o = n.classList.toggle('open'); b.setAttribute('aria-expanded', o); }
  else if (a === 'filters') { const s = $('#side'), o = s.classList.toggle('open'); b.setAttribute('aria-expanded', o); }
  else if (a === 'reset') location.hash = b.dataset.href;
  else if (a === 'retry') route();
});
document.addEventListener('change', ev => {
  const t = ev.target;
  if (t.id === 'so') location.hash = t.dataset.base + (t.dataset.base.includes('?') ? '&' : '?') + 'sort=' + t.value;
  else if (t.closest('#flt')) { const f = $('#flt'), p = new URLSearchParams(); ['min', 'max'].forEach(n => f.elements[n].value && p.set(n, f.elements[n].value)); if (f.elements.instock.checked) p.set('instock', '1'); const base = f.dataset.base; location.hash = base + (p.toString() ? (base.includes('?') ? '&' : '?') + p : ''); }
});
$('#q').addEventListener('keydown', e => { if (e.key === 'Enter') location.hash = '#/catalog?q=' + encodeURIComponent(e.target.value.trim()); });
addEventListener('hashchange', route);
addEventListener('storage', e => { if (e.key === 'lp_cart2' || e.key === 'lp_fav2') { cart = loadCart(); fav = store.get('lp_fav2', []); badges(); } });
badges(); route();
})();
