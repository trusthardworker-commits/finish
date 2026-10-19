(() => {
'use strict';
const h = (t, a = {}, ...c) => { const e = document.createElement(t); for (const [k, v] of Object.entries(a)) { if (k === 'class') e.className = v; else if (k.startsWith('on')) e.addEventListener(k.slice(2), v); else if (v === true) e.setAttribute(k, ''); else if (v !== false && v != null) e.setAttribute(k, v); } for (const x of c.flat()) e.append(x && x.nodeType ? x : document.createTextNode(x ?? '')); return e; };
const root = document.getElementById('root');
let csrf = '', cats = [], dirs = [], tab = 'products', main;
const rub = k => (k / 100).toLocaleString('ru-RU') + ' ₽';
const ST = { published: 'Опубликован', hidden: 'Скрыт', archived: 'В архиве' }, OST = { request: 'Запрос КП', new: 'Новый', processing: 'В работе', shipped: 'Отправлен', completed: 'Выполнен', cancelled: 'Отменён' };
const BT = { p: 'Физлицо', u: 'Юрлицо / ИП', d: 'Детсад / бюджет. учреждение' };

async function api(path, method = 'GET', body) {
  const r = await fetch('/api/admin' + path, { method, credentials: 'same-origin', headers: { ...(body ? { 'Content-Type': 'application/json' } : {}), ...(method !== 'GET' ? { 'X-CSRF-Token': csrf } : {}) }, body: body ? JSON.stringify(body) : undefined });
  let d = {}; try { d = await r.json(); } catch (e) { /* нет тела */ }
  if (r.status === 401 && path !== '/login') { login(); throw { msg: 'Требуется вход', silent: true }; }
  if (!r.ok) throw { status: r.status, msg: d.error || 'Ошибка', data: d };
  return d;
}
const say = (text, err) => { const m = h('div', { class: 'msg' + (err ? ' err' : ''), role: err ? 'alert' : 'status' }, text); const old = main.querySelector('.msg'); old ? old.replaceWith(m) : main.prepend(m); scrollTo(0, 0); };
const guard = f => async (...a) => { try { await f(...a); } catch (e) { if (!e.silent) say(e.msg || 'Ошибка', true); } };
const fld = (label, input, cls = '') => h('div', { class: cls }, h('label', { class: 'l' }, label), input);

function login() {
  const u = h('input', { value: 'admin', autocomplete: 'username', 'aria-label': 'Логин' }), p = h('input', { type: 'password', autocomplete: 'current-password', 'aria-label': 'Пароль' }), err = h('div', { class: 'msg err', hidden: true, role: 'alert' });
  const go = async e => { e.preventDefault(); try { const d = await api('/login', 'POST', { username: u.value, password: p.value }); csrf = d.csrf; shell(); } catch (er) { err.textContent = er.msg; err.hidden = false; } };
  root.replaceChildren(h('form', { class: 'card login', onsubmit: go }, h('h1', {}, 'Вход в админку'), err, fld('Логин', u), fld('Пароль', p), h('button', { class: 'btn o', type: 'submit' }, 'Войти')));
  p.focus();
}
function shell() {
  main = h('main');
  const tabs = [['products', 'Товары'], ['cats', 'Категории'], ['site', 'Главная и страницы'], ['orders', 'Заказы'], ['audit', 'Журнал']];
  const bar = h('div', { class: 'top' }, h('b', {}, 'Лавка логопеда · админка'), tabs.map(([k, n]) => h('button', { type: 'button', class: tab === k ? 'on' : '', onclick: () => { tab = k; shell(); } }, n)), h('span', { class: 'sp' }), h('a', { href: '/', style: 'color:#fff', target: '_blank', rel: 'noopener' }, 'Сайт'),
    h('button', { type: 'button', onclick: guard(async () => { await api('/logout', 'POST', {}); csrf = ''; login(); }) }, 'Выйти'));
  root.replaceChildren(bar, main);
  guard(async () => { const c = await api('/categories'); cats = c.items; dirs = c.directions; ({ products, cats: catsView, site, orders, audit: auditView })[tab](); })();
}
const catName = id => { const c = cats.find(x => x.id === id); return c ? `${dirs.find(d => d.id === c.direction).name} → ${c.name}` : '—'; };

// ---- товары
function products() {
  const q = h('input', { type: 'search', placeholder: 'Поиск по названию или артикулу', 'aria-label': 'Поиск' }), st = h('select', { 'aria-label': 'Статус' }, h('option', { value: '' }, 'Все статусы'), Object.entries(ST).map(([k, v]) => h('option', { value: k }, v)));
  const box = h('div', { class: 'tw' });
  const load = guard(async () => { const d = await api(`/products?q=${encodeURIComponent(q.value)}&status=${st.value}`); box.replaceChildren(h('table', {}, h('thead', {}, h('tr', {}, ['Артикул', 'Название', 'Категория', 'Цена', 'Остаток', 'Статус', ''].map(x => h('th', {}, x)))),
    h('tbody', {}, d.items.map(p => h('tr', {}, h('td', {}, p.sku), h('td', {}, p.name, p.featured ? ' ★' : '', p.is_demo ? ' (демо)' : ''), h('td', {}, catName(p.category_id)), h('td', {}, p.price + ' ₽'), h('td', {}, String(p.stock)), h('td', {}, h('span', { class: 'pill ' + p.status }, ST[p.status])), h('td', {}, h('button', { class: 'btn l s', type: 'button', onclick: () => productForm(p) }, 'Изменить'))))))); if (!d.items.length) box.append(h('p', {}, 'Ничего не найдено')); });
  q.addEventListener('input', load); st.addEventListener('change', load);
  main.replaceChildren(h('h1', {}, 'Товары'), h('div', { class: 'tb' }, q, st, h('button', { class: 'btn o s', type: 'button', onclick: () => productForm(null) }, '+ Новый товар')), h('div', { class: 'card' }, box)); load();
}
function imageUploader(list, render) {
  const inp = h('input', { type: 'file', accept: 'image/jpeg,image/png,image/webp', 'aria-label': 'Загрузить изображение' });
  inp.addEventListener('change', guard(async () => {
    const f = inp.files[0]; if (!f) return; if (f.size > 5e6) throw { msg: 'Файл больше 5 МБ' };
    const b64 = await new Promise((ok, no) => { const r = new FileReader(); r.onload = () => ok(String(r.result).split(',')[1]); r.onerror = no; r.readAsDataURL(f); });
    const d = await api('/upload', 'POST', { data: b64 }); list.push(d.path); inp.value = ''; render();
  }));
  return inp;
}
function productForm(p) {
  const v = p || { sku: '', name: '', description: '', price: '', stock: 0, category_id: '', status: 'hidden', featured: false, sort: 100, seo_title: '', seo_desc: '', images: [] };
  const imgs = [...v.images], I = {
    sku: h('input', { value: v.sku, maxlength: 64 }), name: h('input', { value: v.name, maxlength: 200 }), price: h('input', { value: v.price, inputmode: 'decimal' }), stock: h('input', { type: 'number', min: 0, value: v.stock }),
    cat: h('select', {}, h('option', { value: '' }, '— выберите —'), cats.map(c => h('option', { value: c.id, selected: c.id === v.category_id }, `${dirs.find(d => d.id === c.direction).name} → ${c.name}`))),
    status: h('select', {}, Object.entries(ST).map(([k, n]) => h('option', { value: k, selected: k === v.status }, n))), featured: h('input', { type: 'checkbox', checked: v.featured }), sort: h('input', { type: 'number', value: v.sort }),
    desc: h('textarea', { rows: 5, maxlength: 5000 }, v.description), st: h('input', { value: v.seo_title, maxlength: 200 }), sd: h('input', { value: v.seo_desc, maxlength: 400 })
  };
  const gal = h('div', { class: 'imgs' }), render = () => gal.replaceChildren(...imgs.map((s, i) => h('div', {}, h('img', { src: s, alt: '' }), h('div', {}, i === 0 ? 'Основное' : h('button', { type: 'button', class: 'btn l s', onclick: () => { imgs.unshift(...imgs.splice(i, 1)); render(); } }, 'Сделать основным')), h('button', { type: 'button', class: 'btn l s', onclick: () => { imgs.splice(i, 1); render(); } }, 'Убрать')))); render();
  const save = guard(async e => { e.preventDefault(); const body = { sku: I.sku.value, name: I.name.value, price: I.price.value, stock: I.stock.value, category_id: I.cat.value, status: I.status.value, featured: I.featured.checked, sort: I.sort.value, description: I.desc.value, seo_title: I.st.value, seo_desc: I.sd.value, images: imgs }; await api(p ? '/products/' + p.id : '/products', p ? 'PUT' : 'POST', body); tab = 'products'; shell(); setTimeout(() => say('Товар сохранён'), 150); });
  const del = guard(async () => { if (!confirm('Удалить товар безвозвратно? Если он есть в заказах, удаление будет отклонено — используйте архив.')) return; await api('/products/' + p.id + '?confirm=1', 'DELETE'); tab = 'products'; shell(); });
  main.replaceChildren(h('h1', {}, p ? 'Редактирование товара' : 'Новый товар'), h('form', { class: 'card', onsubmit: save }, h('div', { class: 'fg' }, fld('Название *', I.name, 'w2'), fld('Артикул *', I.sku), fld('Цена, ₽ *', I.price), fld('Остаток, шт.', I.stock), fld('Категория *', I.cat), fld('Статус', I.status), fld('Порядок (меньше — выше)', I.sort),
    fld('Рекомендуемый (приоритет на главной)', I.featured), fld('Описание', I.desc, 'w2'), fld('Изображения (JPEG, PNG, WebP до 5 МБ)', h('div', {}, gal, imageUploader(imgs, render)), 'w2'), fld('SEO: заголовок', I.st), fld('SEO: описание', I.sd)),
    h('p', {}, h('button', { class: 'btn o', type: 'submit' }, 'Сохранить'), ' ', h('button', { class: 'btn l', type: 'button', onclick: () => { tab = 'products'; shell(); } }, 'Отмена'), ' ', p ? h('button', { class: 'btn l', type: 'button', onclick: del }, 'Удалить') : '')));
}

// ---- категории
function catsView() {
  main.replaceChildren(h('h1', {}, 'Категории'), h('div', { class: 'tb' }, h('button', { class: 'btn o s', type: 'button', onclick: () => catForm(null) }, '+ Новая категория')),
    h('div', { class: 'card tw' }, h('table', {}, h('thead', {}, h('tr', {}, ['Направление', 'Название', 'URL', 'Товаров', 'Порядок', 'Видима', ''].map(x => h('th', {}, x)))),
      h('tbody', {}, cats.map(c => h('tr', {}, h('td', {}, dirs.find(d => d.id === c.direction).name), h('td', {}, c.name), h('td', {}, c.slug), h('td', {}, String(c.products)), h('td', {}, String(c.sort)), h('td', {}, c.active ? 'да' : 'нет'), h('td', {}, h('button', { class: 'btn l s', type: 'button', onclick: () => catForm(c) }, 'Изменить'))))))));
}
function catForm(c) {
  const v = c || { slug: '', name: '', direction: 'logoped', description: '', sort: 100, home_order: 100, active: true, seo_title: '', seo_desc: '' };
  const I = { name: h('input', { value: v.name, maxlength: 150 }), slug: h('input', { value: v.slug, maxlength: 64 }), dir: h('select', {}, dirs.map(d => h('option', { value: d.id, selected: d.id === v.direction }, d.name))), sort: h('input', { type: 'number', value: v.sort }), home: h('input', { type: 'number', value: v.home_order }),
    active: h('input', { type: 'checkbox', checked: v.active }), desc: h('textarea', { rows: 3, maxlength: 1000 }, v.description), st: h('input', { value: v.seo_title }), sd: h('input', { value: v.seo_desc }) };
  const save = guard(async e => { e.preventDefault(); await api(c ? '/categories/' + c.id : '/categories', c ? 'PUT' : 'POST', { name: I.name.value, slug: I.slug.value, direction: I.dir.value, sort: I.sort.value, home_order: I.home.value, active: I.active.checked, description: I.desc.value, seo_title: I.st.value, seo_desc: I.sd.value }); tab = 'cats'; shell(); });
  const tgt = h('select', {}, cats.filter(x => !c || x.id !== c.id).map(x => h('option', { value: x.id }, `${dirs.find(d => d.id === x.direction).name} → ${x.name}`))), reass = h('div', { class: 'card', hidden: true }, h('p', {}, 'В категории есть товары. Перенесите их в другую категорию перед удалением:'), tgt,
    ' ', h('button', { class: 'btn o s', type: 'button', onclick: guard(async () => { await api(`/categories/${c.id}?reassign=${tgt.value}`, 'DELETE'); tab = 'cats'; shell(); }) }, 'Перенести и удалить'));
  const del = guard(async () => { if (!confirm('Удалить категорию?')) return; try { await api('/categories/' + c.id, 'DELETE'); tab = 'cats'; shell(); } catch (e) { if (e.status === 409 && e.data.products) reass.hidden = false; else throw e; } });
  main.replaceChildren(h('h1', {}, c ? 'Редактирование категории' : 'Новая категория'), h('form', { class: 'card', onsubmit: save }, h('div', { class: 'fg' }, fld('Название *', I.name), fld('URL-идентификатор * (латиница, дефисы)', I.slug), fld('Направление *', I.dir), fld('Порядок в каталоге', I.sort), fld('Порядок на главной', I.home), fld('Показывать на сайте', I.active), fld('Описание', I.desc, 'w2'), fld('SEO: заголовок', I.st), fld('SEO: описание', I.sd)),
    h('p', {}, h('button', { class: 'btn o', type: 'submit' }, 'Сохранить'), ' ', h('button', { class: 'btn l', type: 'button', onclick: () => { tab = 'cats'; shell(); } }, 'Отмена'), ' ', c ? h('button', { class: 'btn l', type: 'button', onclick: del }, 'Удалить') : '')), reass);
}

// ---- главная и страницы
function site() {
  guard(async () => {
    const s = await api('/settings'), heroImg = { v: s.hero_image };
    const I = { t: h('input', { value: s.hero_title, maxlength: 600 }), s: h('textarea', { rows: 2 }, s.hero_sub), b1: h('input', { value: s.hero_btn_text }), l1: h('input', { value: s.hero_btn_link }), b2: h('input', { value: s.hero_btn2_text }), l2: h('input', { value: s.hero_btn2_link }),
      se: h('input', { type: 'checkbox', checked: s.showcase_enabled }), st: h('input', { value: s.showcase_title }), he: h('input', { type: 'checkbox', checked: s.hide_empty_categories }), c: h('textarea', { rows: 2 }, s.contacts) };
    const pagesI = Object.fromEntries(Object.keys(s.pages).map(k => [k, h('textarea', { rows: 6 }, s.pages[k])])), names = { about: 'О нас', delivery: 'Доставка и оплата', contacts: 'Контакты (страница)', privacy: 'Политика обработки персональных данных', kindergarten: 'Информация для детских садов' };
    const hv = h('span', {}, s.hero_image || 'по умолчанию'), up = []; const upl = imageUploader(up, () => { heroImg.v = up[up.length - 1]; hv.textContent = heroImg.v; });
    const save = guard(async e => { e.preventDefault(); await api('/settings', 'PUT', { hero_title: I.t.value, hero_sub: I.s.value, hero_btn_text: I.b1.value, hero_btn_link: I.l1.value, hero_btn2_text: I.b2.value, hero_btn2_link: I.l2.value, hero_image: heroImg.v, showcase_enabled: I.se.checked, showcase_title: I.st.value, hide_empty_categories: I.he.checked, contacts: I.c.value, pages: Object.fromEntries(Object.entries(pagesI).map(([k, x]) => [k, x.value])) }); say('Настройки сохранены'); });
    main.replaceChildren(h('h1', {}, 'Главная и страницы'), h('form', { class: 'card', onsubmit: save }, h('div', { class: 'fg' }, fld('Заголовок баннера', I.t, 'w2'), fld('Подзаголовок', I.s, 'w2'), fld('Кнопка 1: текст', I.b1), fld('Кнопка 1: ссылка (#/… или /…)', I.l1), fld('Кнопка 2: текст (пусто — скрыть)', I.b2), fld('Кнопка 2: ссылка', I.l2),
      fld('Изображение баннера', h('div', {}, hv, ' ', upl, h('button', { class: 'btn l s', type: 'button', onclick: () => { heroImg.v = ''; hv.textContent = 'по умолчанию'; } }, 'Вернуть стандартное')), 'w2'), fld('Показывать блок «товары в наличии»', I.se), fld('Заголовок блока товаров', I.st), fld('Скрывать пустые категории', I.he), fld('Контакты (кратко)', I.c, 'w2'),
      Object.entries(pagesI).map(([k, x]) => fld(names[k], x, 'w2'))), h('p', {}, h('button', { class: 'btn o', type: 'submit' }, 'Сохранить'))));
  })();
}

// ---- заказы
function orders() {
  const q = h('input', { type: 'search', placeholder: 'Номер, имя, телефон, организация', 'aria-label': 'Поиск' }), st = h('select', { 'aria-label': 'Статус' }, h('option', { value: '' }, 'Все статусы'), Object.entries(OST).map(([k, v]) => h('option', { value: k }, v))), box = h('div', { class: 'tw' });
  const load = guard(async () => { const d = await api(`/orders?q=${encodeURIComponent(q.value)}&status=${st.value}`); box.replaceChildren(d.items.length ? h('table', {}, h('thead', {}, h('tr', {}, ['Номер', 'Дата', 'Покупатель', 'Тип', 'Сумма', 'Статус', ''].map(x => h('th', {}, x)))), h('tbody', {}, d.items.map(o => h('tr', {}, h('td', {}, o.number), h('td', {}, o.created_at), h('td', {}, o.org || o.name), h('td', {}, BT[o.buyer_type]), h('td', {}, rub(o.total_kop)), h('td', {}, h('span', { class: 'pill ' + o.status }, OST[o.status])), h('td', {}, h('button', { class: 'btn l s', type: 'button', onclick: () => orderView(o.id) }, 'Открыть')))))) : h('p', {}, 'Заказов нет')); });
  q.addEventListener('input', load); st.addEventListener('change', load);
  main.replaceChildren(h('h1', {}, 'Заказы'), h('div', { class: 'tb' }, q, st), h('div', { class: 'card' }, box)); load();
}
const orderView = guard(async id => {
  const o = await api('/orders/' + id), sel = h('select', {}, Object.entries(OST).map(([k, v]) => h('option', { value: k, selected: k === o.status }, v))), note = h('input', { placeholder: 'Комментарий к смене статуса', maxlength: 500 });
  const row = (a, b) => h('tr', {}, h('th', {}, a), h('td', {}, b || '—'));
  main.replaceChildren(h('h1', {}, 'Заказ ' + o.number), h('div', { class: 'card tw' }, h('table', {}, row('Дата', o.created_at), row('Тип', BT[o.buyer_type]), row('Имя / контакт', o.name), row('Телефон', o.phone), row('E-mail', o.email), row('Организация', o.org), row('ИНН / КПП', [o.inn, o.kpp].filter(Boolean).join(' / ')), row('Должность', o.position), row('Адрес', o.address), row('Доставка', o.delivery), row('Комментарий', o.comment))),
    h('div', { class: 'card tw' }, h('h2', {}, 'Состав (цены зафиксированы при оформлении)'), h('table', {}, h('thead', {}, h('tr', {}, ['Артикул', 'Название', 'Цена', 'Кол-во', 'Сумма'].map(x => h('th', {}, x)))), h('tbody', {}, o.items.map(i => h('tr', {}, h('td', {}, i.sku), h('td', {}, i.name), h('td', {}, rub(i.price_kop)), h('td', {}, String(i.qty)), h('td', {}, rub(i.price_kop * i.qty))))), h('tfoot', {}, h('tr', {}, h('th', { colspan: 4 }, 'Итого'), h('th', {}, rub(o.total_kop)))))),
    h('div', { class: 'card' }, h('h2', {}, 'Статус'), h('div', { class: 'tb' }, sel, note, h('button', { class: 'btn o s', type: 'button', onclick: guard(async () => { await api(`/orders/${id}/status`, 'PUT', { status: sel.value, note: note.value }); orderView(id); }) }, 'Сохранить статус')), h('p', { class: 'note' }, 'При отмене заказа остатки возвращаются на склад.'),
      h('ul', {}, o.history.map(x => h('li', {}, `${x.at} — ${OST[x.status]}${x.note ? ': ' + x.note : ''}`)))), h('button', { class: 'btn l', type: 'button', onclick: () => { tab = 'orders'; shell(); } }, '← К списку'));
});
function audit() { guard(async () => { const d = await api('/audit'); main.replaceChildren(h('h1', {}, 'Журнал действий'), h('div', { class: 'card tw' }, h('table', {}, h('thead', {}, h('tr', {}, ['Время', 'Пользователь', 'Действие', 'Объект', 'ID', 'IP'].map(x => h('th', {}, x)))), h('tbody', {}, d.items.map(r => h('tr', {}, [r.at, r.user, r.action, r.entity, r.entity_id, r.ip].map(x => h('td', {}, x)))))))); })(); }
const auditView = audit;

(async () => { try { const m = await api('/me'); csrf = m.csrf; shell(); } catch (e) { /* login() уже показан */ } })();
})();
