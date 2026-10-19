#!/usr/bin/env python3
"""«Лавка логопеда» — сервер магазина и CMS.

Только стандартная библиотека Python + Pillow (проверка и перекодирование картинок).
Запуск:  python3 server/app.py          (см. README.md)
"""
import base64, getpass, hashlib, hmac, io, json, mimetypes, os, re, secrets, sqlite3, sys, threading, time
from datetime import datetime
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlparse

try:
    from PIL import Image
except ImportError:  # загрузка картинок отключится с понятной ошибкой
    Image = None

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PUBLIC = os.path.join(ROOT, "public")
DATA = os.environ.get("LP_DATA_DIR", os.path.join(ROOT, "data"))
UPLOADS = os.path.join(DATA, "uploads")
DB_PATH = os.environ.get("LP_DB", os.path.join(DATA, "shop.db"))
SECURE_COOKIES = os.environ.get("LP_SECURE_COOKIES") == "1"
TRUST_PROXY = os.environ.get("LP_TRUST_PROXY") == "1"
SESSION_TTL = 8 * 3600
DIRECTIONS = {"logoped": "Логопедические товары", "stationery": "Канцелярия"}
PRODUCT_STATUSES = ("published", "hidden", "archived")
ORDER_STATUSES = ("request", "new", "processing", "shipped", "completed", "cancelled")

# ----------------------------------------------------------------------------- БД
SCHEMA_V1 = """
CREATE TABLE categories(
  id INTEGER PRIMARY KEY, slug TEXT NOT NULL UNIQUE, name TEXT NOT NULL,
  direction TEXT NOT NULL CHECK(direction IN('logoped','stationery')),
  description TEXT NOT NULL DEFAULT '', image TEXT, sort INTEGER NOT NULL DEFAULT 100,
  home_order INTEGER NOT NULL DEFAULT 100, active INTEGER NOT NULL DEFAULT 1,
  seo_title TEXT NOT NULL DEFAULT '', seo_desc TEXT NOT NULL DEFAULT '');
CREATE TABLE products(
  id INTEGER PRIMARY KEY, sku TEXT NOT NULL UNIQUE, name TEXT NOT NULL,
  description TEXT NOT NULL DEFAULT '', price_kop INTEGER NOT NULL CHECK(price_kop>0),
  stock INTEGER NOT NULL DEFAULT 0 CHECK(stock>=0),
  category_id INTEGER REFERENCES categories(id),
  status TEXT NOT NULL DEFAULT 'hidden' CHECK(status IN('published','hidden','archived')),
  featured INTEGER NOT NULL DEFAULT 0, sort INTEGER NOT NULL DEFAULT 100,
  is_demo INTEGER NOT NULL DEFAULT 0, seo_title TEXT NOT NULL DEFAULT '', seo_desc TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE INDEX idx_products_cat ON products(category_id, status);
CREATE TABLE product_images(
  id INTEGER PRIMARY KEY, product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
  path TEXT NOT NULL, sort INTEGER NOT NULL DEFAULT 0);
CREATE TABLE settings(key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE users(id INTEGER PRIMARY KEY, username TEXT NOT NULL UNIQUE, salt TEXT NOT NULL, pw_hash TEXT NOT NULL);
CREATE TABLE sessions(token_hash TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  csrf TEXT NOT NULL, expires_at INTEGER NOT NULL);
CREATE TABLE orders(
  id INTEGER PRIMARY KEY, number TEXT UNIQUE, idem_key TEXT NOT NULL UNIQUE,
  status TEXT NOT NULL CHECK(status IN('request','new','processing','shipped','completed','cancelled')),
  buyer_type TEXT NOT NULL CHECK(buyer_type IN('p','u','d')), name TEXT NOT NULL, phone TEXT NOT NULL,
  email TEXT NOT NULL DEFAULT '', address TEXT NOT NULL DEFAULT '', org TEXT NOT NULL DEFAULT '',
  inn TEXT NOT NULL DEFAULT '', kpp TEXT NOT NULL DEFAULT '', position TEXT NOT NULL DEFAULT '',
  delivery TEXT NOT NULL DEFAULT '', comment TEXT NOT NULL DEFAULT '', total_kop INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL);
CREATE TABLE order_items(
  id INTEGER PRIMARY KEY, order_id INTEGER NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
  product_id INTEGER, sku TEXT NOT NULL, name TEXT NOT NULL, price_kop INTEGER NOT NULL, qty INTEGER NOT NULL CHECK(qty>0));
CREATE TABLE order_history(id INTEGER PRIMARY KEY, order_id INTEGER NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
  status TEXT NOT NULL, note TEXT NOT NULL DEFAULT '', at TEXT NOT NULL);
CREATE TABLE audit_log(id INTEGER PRIMARY KEY, at TEXT NOT NULL, user TEXT NOT NULL, action TEXT NOT NULL,
  entity TEXT NOT NULL, entity_id TEXT NOT NULL DEFAULT '', ip TEXT NOT NULL DEFAULT '');
"""
MIGRATIONS = [SCHEMA_V1]  # новые миграции — добавлять в конец списка, существующие не менять


def now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def connect():
    c = sqlite3.connect(DB_PATH, timeout=10, isolation_level=None)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys=ON")
    c.create_function("plower", 1, lambda s: (s or "").lower())  # LIKE в SQLite не понимает кириллицу в нижнем регистре
    return c


def migrate(c):
    ver = c.execute("PRAGMA user_version").fetchone()[0]
    for i in range(ver, len(MIGRATIONS)):
        c.executescript("BEGIN;" + MIGRATIONS[i] + f"PRAGMA user_version={i + 1};COMMIT;")


CATEGORIES = [  # (slug, название, направление, порядок)
    ("probes", "Логопедические зонды и инструменты", "logoped", 10), ("cards", "Логопедические карточки и наглядные пособия", "logoped", 20),
    ("speech", "Материалы для развития речи", "logoped", 30), ("artic", "Артикуляционная гимнастика", "logoped", 40),
    ("games", "Дидактические игры", "logoped", 50), ("sounds", "Материалы для автоматизации звуков", "logoped", 60),
    ("phonemic", "Развитие фонематического слуха", "logoped", 70), ("vocab", "Развитие словаря и связной речи", "logoped", 80),
    ("motor", "Развитие мелкой моторики", "logoped", 90), ("school", "Материалы для подготовки к школе", "logoped", 100),
    ("books", "Книги, альбомы и методические пособия", "logoped", 110),
    ("paper", "Бумага и картон", "stationery", 10), ("albums", "Альбомы и тетради", "stationery", 20),
    ("pens", "Ручки, карандаши и фломастеры", "stationery", 30), ("paints", "Краски, кисти и принадлежности для рисования", "stationery", 40),
    ("glue", "Клей, ножницы и инструменты для творчества", "stationery", 50), ("clay", "Пластилин и материалы для лепки", "stationery", 60),
    ("colorpaper", "Цветная бумага и наборы для творчества", "stationery", 70), ("folders", "Папки, файлы и принадлежности для хранения", "stationery", 80),
    ("other", "Прочая канцелярия", "stationery", 90)]
# Демо-товары (is_demo=1): названия — типовые, цены и остатки условные. Заменить реальными через админку.
DEMO = [("games", "10234", "Настольная игра «Развиваем речь»", 890, 12), ("cards", "10452", "Набор карточек «Эмоции»", 650, 8),
        ("games", "10721", "Пазл «Домашние животные»", 790, 5), ("sounds", "10876", "Логопедическое лото «Звуки и буквы»", 720, 9),
        ("motor", "10903", "Набор для развития мелкой моторики", 1190, 0), ("vocab", "11012", "Дидактический материал «Слоги и слова»", 550, 14),
        ("probes", "D-001", "Набор логопедических зондов", 1450, 6), ("artic", "D-002", "Карточки артикуляционной гимнастики", 480, 20),
        ("books", "D-003", "Методическое пособие для логопеда", 960, 7), ("school", "D-004", "Прописи для подготовки к школе", 240, 30),
        ("paper", "S-001", "Картон цветной, набор", 210, 40), ("albums", "S-002", "Альбом для рисования А4", 120, 60),
        ("pens", "S-003", "Набор цветных карандашей, 12 цветов", 190, 50), ("paints", "S-004", "Акварельные краски, 12 цветов", 260, 25),
        ("glue", "S-005", "Клей-карандаш", 70, 80), ("clay", "S-006", "Пластилин, 12 цветов", 230, 35),
        ("colorpaper", "S-007", "Цветная бумага, набор", 150, 45), ("folders", "S-008", "Папка с файлами А4", 180, 18)]
DEFAULT_SETTINGS = {
    "hero_title": "Всё для речи и развития дошкольника",
    "hero_sub": "Игры, пособия, книги и канцелярия для логопедов, родителей и образовательных учреждений.",
    "hero_btn_text": "Перейти в каталог", "hero_btn_link": "#/catalog",
    "hero_btn2_text": "Заказать для детского сада", "hero_btn2_link": "#/org", "hero_image": "",
    "showcase_enabled": True, "showcase_title": "Товары в наличии", "hide_empty_categories": True,
    "contacts": "Телефон: 8-914-999-95-01",
    "pages": {"about": "", "delivery": "", "contacts": "", "privacy": "", "kindergarten": ""},
}


def get_settings(c):
    s = json.loads(json.dumps(DEFAULT_SETTINGS))
    row = c.execute("SELECT value FROM settings WHERE key='site'").fetchone()
    if row:
        stored = json.loads(row["value"])
        for k, v in stored.items():
            if k == "pages":
                s["pages"].update(v)
            elif k in s:
                s[k] = v
    return s


def hash_pw(pw, salt):
    return hashlib.scrypt(pw.encode(), salt=bytes.fromhex(salt), n=2 ** 14, r=8, p=1, dklen=32).hex()


def set_admin(c, pw):
    salt = secrets.token_hex(16)
    c.execute("INSERT INTO users(username,salt,pw_hash) VALUES('admin',?,?) ON CONFLICT(username) DO UPDATE SET salt=excluded.salt, pw_hash=excluded.pw_hash",
              (salt, hash_pw(pw, salt)))
    c.execute("DELETE FROM sessions")


def init_db():
    os.makedirs(UPLOADS, exist_ok=True)
    c = connect()
    c.execute("PRAGMA journal_mode=WAL")
    migrate(c)
    if c.execute("SELECT COUNT(*) FROM categories").fetchone()[0] == 0:
        for slug, name, d, o in CATEGORIES:
            c.execute("INSERT INTO categories(slug,name,direction,sort,home_order) VALUES(?,?,?,?,?)", (slug, name, d, o, o))
    if os.environ.get("LP_SEED_DEMO", "1") != "0" and c.execute("SELECT COUNT(*) FROM products").fetchone()[0] == 0:
        for i, (cat, sku, name, price, stock) in enumerate(DEMO):
            cid = c.execute("SELECT id FROM categories WHERE slug=?", (cat,)).fetchone()[0]
            c.execute("INSERT INTO products(sku,name,description,price_kop,stock,category_id,status,sort,is_demo,created_at,updated_at) VALUES(?,?,?,?,?,?, 'published',?,1,?,?)",
                      (sku, name, "Демонстрационный товар: описание, цена и остаток условные.", price * 100, stock, cid, i * 10, now(), now()))
    if c.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0:
        pw = os.environ.get("LP_ADMIN_PASSWORD", "")
        generated = False
        if len(pw) < 10:
            pw, generated = secrets.token_urlsafe(14), True
        set_admin(c, pw)
        if generated:
            print(f"\n[!] Создан администратор. Логин: admin   Пароль: {pw}\n    Показывается один раз — сохраните. Сменить: python3 server/app.py --reset-admin\n", file=sys.stderr)
    c.close()


# ----------------------------------------------------------------------------- утилиты
class ApiError(Exception):
    def __init__(self, code, msg, extra=None):
        self.code, self.msg, self.extra = code, msg, extra or {}


_rl, _rl_lock = {}, threading.Lock()


def rate_ok(bucket, key, limit, window):
    t = time.time()
    with _rl_lock:
        q = [x for x in _rl.get((bucket, key), []) if t - x < window]
        if len(q) >= limit:
            _rl[(bucket, key)] = q
            return False
        q.append(t)
        _rl[(bucket, key)] = q
        return True


CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def text(d, key, lo=0, hi=200, required=False, label=None):
    v = d.get(key, "")
    if v is None:
        v = ""
    if not isinstance(v, str):
        raise ApiError(400, f"Поле «{label or key}» должно быть текстом")
    v = CTRL.sub("", v).strip()
    if (required or lo) and len(v) < max(lo, 1):
        raise ApiError(400, f"Заполните поле «{label or key}»")
    if len(v) > hi:
        raise ApiError(400, f"Поле «{label or key}» слишком длинное (максимум {hi})")
    return v


def to_int(v, lo, hi, label):
    if isinstance(v, bool) or not isinstance(v, (int, str)) or (isinstance(v, str) and not re.fullmatch(r"-?\d{1,12}", v.strip())):
        raise ApiError(400, f"«{label}» должно быть целым числом")
    v = int(v)
    if not lo <= v <= hi:
        raise ApiError(400, f"«{label}» должно быть от {lo} до {hi}")
    return v


def price_to_kop(v):
    s = str(v).strip().replace(",", ".")
    if isinstance(v, bool) or not re.fullmatch(r"\d{1,8}(\.\d{1,2})?", s):
        raise ApiError(400, "Цена: число, не более двух знаков после запятой")
    kop = round(float(s) * 100)
    if kop <= 0:
        raise ApiError(400, "Цена должна быть больше нуля")
    return kop


SAFE_LINK = re.compile(r"^(#/[\w/?=&%.,-]*|/(?!/)[\w/.-]*|https?://[\w.-]+(:\d+)?(/[\w/.?=&%#,-]*)?)$")
UPLOAD_PATH = re.compile(r"^/uploads/[0-9a-f]{32}\.webp$")


def audit(c, user, action, entity, entity_id="", ip=""):
    c.execute("INSERT INTO audit_log(at,user,action,entity,entity_id,ip) VALUES(?,?,?,?,?,?)", (now(), user, action, entity, str(entity_id), ip))


# ----------------------------------------------------------------------------- публичное API
def images_for(c, ids):
    out = {i: [] for i in ids}
    if ids:
        q = ",".join("?" * len(ids))
        for r in c.execute(f"SELECT product_id,path FROM product_images WHERE product_id IN ({q}) ORDER BY sort,id", list(ids)):
            out[r["product_id"]].append(r["path"])
    return out


def pub_product(r, imgs):
    stock = r["stock"]
    return {"id": r["id"], "sku": r["sku"], "name": r["name"], "description": r["description"], "price_kop": r["price_kop"],
            "in_stock": stock > 0, "max_qty": min(stock, 99), "demo": bool(r["is_demo"]), "images": imgs,
            "category": {"slug": r["cat_slug"], "name": r["cat_name"], "direction": r["direction"], "direction_name": DIRECTIONS[r["direction"]]}}


PRODUCT_SELECT = ("SELECT p.*, c.slug AS cat_slug, c.name AS cat_name, c.direction FROM products p "
                  "JOIN categories c ON c.id=p.category_id WHERE p.status='published' AND c.active=1")


def h_categories(rq, m):
    s = get_settings(rq.c)
    rows = rq.c.execute("SELECT c.*, (SELECT COUNT(*) FROM products p WHERE p.category_id=c.id AND p.status='published') AS cnt "
                        "FROM categories c WHERE c.active=1 ORDER BY c.sort,c.id").fetchall()
    cats = [{"slug": r["slug"], "name": r["name"], "direction": r["direction"], "description": r["description"], "count": r["cnt"]}
            for r in rows if r["cnt"] > 0 or not s["hide_empty_categories"]]
    return {"directions": [{"id": k, "name": v} for k, v in DIRECTIONS.items()], "categories": cats}


SORTS = {"popular": "(p.stock>0) DESC, p.featured DESC, p.sort, p.id", "price_asc": "p.price_kop ASC, p.id", "price_desc": "p.price_kop DESC, p.id",
         "new": "p.id DESC", "name": "p.name COLLATE NOCASE ASC"}


def h_catalog(rq, m):
    q, sql, args = rq.query, PRODUCT_SELECT, []
    d = q.get("dir", "")
    if d:
        if d not in DIRECTIONS:
            raise ApiError(400, "Неизвестное направление")
        sql += " AND c.direction=?"; args.append(d)
    if q.get("cat"):
        sql += " AND c.slug=?"; args.append(q["cat"][:64])
    if q.get("q"):
        sql += " AND (plower(p.name) LIKE ? ESCAPE '\\' OR plower(p.sku) LIKE ? ESCAPE '\\' OR plower(p.description) LIKE ? ESCAPE '\\')"
        like = "%" + q["q"][:80].lower().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        args += [like] * 3
    if q.get("min"):
        sql += " AND p.price_kop>=?"; args.append(to_int(q["min"], 0, 10 ** 9, "Цена от") * 100)
    if q.get("max"):
        sql += " AND p.price_kop<=?"; args.append(to_int(q["max"], 0, 10 ** 9, "Цена до") * 100)
    if q.get("instock") == "1":
        sql += " AND p.stock>0"
    if q.get("ids"):
        ids = [to_int(x, 1, 10 ** 9, "id") for x in q["ids"].split(",")[:50]]
        sql += f" AND p.id IN ({','.join('?' * len(ids))})"; args += ids
    order = SORTS.get(q.get("sort", "popular"))
    if not order:
        raise ApiError(400, "Неизвестная сортировка")
    per = to_int(q.get("per", "12"), 1, 48, "На странице")
    page = to_int(q.get("page", "1"), 1, 10000, "Страница")
    total = rq.c.execute(f"SELECT COUNT(*) FROM ({sql})", args).fetchone()[0]
    rows = rq.c.execute(f"{sql} ORDER BY {order} LIMIT ? OFFSET ?", args + [per, (page - 1) * per]).fetchall()
    imgs = images_for(rq.c, [r["id"] for r in rows])
    return {"items": [pub_product(r, imgs[r["id"]]) for r in rows], "total": total, "page": page, "pages": max(1, -(-total // per))}


def h_product(rq, m):
    r = rq.c.execute(PRODUCT_SELECT + " AND p.id=?", (int(m.group(1)),)).fetchone()
    if not r:
        raise ApiError(404, "Товар не найден")
    sim = rq.c.execute(PRODUCT_SELECT + " AND p.category_id=? AND p.id<>? ORDER BY (p.stock>0) DESC, p.sort LIMIT 4", (r["category_id"], r["id"])).fetchall()
    imgs = images_for(rq.c, [r["id"]] + [x["id"] for x in sim])
    out = pub_product(r, imgs[r["id"]])
    out["similar"] = [pub_product(x, imgs[x["id"]]) for x in sim]
    return out


def h_home(rq, m):
    s = get_settings(rq.c)
    public = {k: s[k] for k in ("hero_title", "hero_sub", "hero_btn_text", "hero_btn_link", "hero_btn2_text", "hero_btn2_link", "hero_image",
                                "showcase_enabled", "showcase_title", "contacts")}
    showcase = []
    if s["showcase_enabled"]:
        cats = rq.c.execute("SELECT id FROM categories WHERE active=1 ORDER BY CASE direction WHEN 'logoped' THEN 0 ELSE 1 END, home_order, id").fetchall()
        for cat in cats:  # по одному товару из каждой категории: рекомендованный, затем по порядку; только с остатком > 0
            r = rq.c.execute(PRODUCT_SELECT + " AND p.category_id=? AND p.stock>0 ORDER BY p.featured DESC, p.sort, p.id LIMIT 1", (cat["id"],)).fetchone()
            if r:
                showcase.append(r)
    imgs = images_for(rq.c, [r["id"] for r in showcase])
    demo = rq.c.execute("SELECT COUNT(*) FROM products WHERE is_demo=1 AND status='published'").fetchone()[0] > 0
    return {"settings": public, "showcase": [pub_product(r, imgs[r["id"]]) for r in showcase], "demo": demo}


def h_page(rq, m):
    pages = get_settings(rq.c)["pages"]
    if m.group(1) not in pages:
        raise ApiError(404, "Страница не найдена")
    return {"key": m.group(1), "text": pages[m.group(1)]}


def clean_items(body):
    items = body.get("items")
    if not isinstance(items, list) or len(items) > 100:
        raise ApiError(400, "Некорректный состав корзины")
    merged = {}
    for it in items:
        if not isinstance(it, dict):
            raise ApiError(400, "Некорректный состав корзины")
        pid, qty = to_int(it.get("id"), 1, 10 ** 9, "Товар"), to_int(it.get("qty"), 1, 999, "Количество")
        merged[pid] = min(merged.get(pid, 0) + qty, 999)
    return merged


def h_quote(rq, m):
    if not rate_ok("quote", rq.ip, 120, 60):
        raise ApiError(429, "Слишком много запросов")
    lines, total = [], 0
    merged = clean_items(rq.body())
    for pid, qty in merged.items():
        r = rq.c.execute(PRODUCT_SELECT + " AND p.id=?", (pid,)).fetchone()
        if not r:
            lines.append({"id": pid, "available": False, "qty": 0, "note": "Товар больше недоступен"}); continue
        eff = min(qty, r["stock"], 99)
        note = "" if eff == qty else ("Нет в наличии" if eff == 0 else f"В наличии только {eff} шт.")
        img = images_for(rq.c, [pid])[pid]
        lines.append({"id": pid, "sku": r["sku"], "name": r["name"], "price_kop": r["price_kop"], "qty": eff, "max_qty": min(r["stock"], 99),
                      "available": eff > 0, "note": note, "image": img[0] if img else "", "line_kop": r["price_kop"] * eff})
        total += r["price_kop"] * eff
    return {"lines": lines, "total_kop": total}


def valid_inn(v):
    return bool(re.fullmatch(r"\d{10}|\d{12}", v))


def h_order(rq, m):
    if not rate_ok("order", rq.ip, 10, 3600):
        raise ApiError(429, "Слишком много заказов с этого адреса. Попробуйте позже")
    b = rq.body()
    key = b.get("idem_key", "")
    if not isinstance(key, str) or not re.fullmatch(r"[A-Za-z0-9-]{16,64}", key):
        raise ApiError(400, "Некорректный ключ запроса")
    old = rq.c.execute("SELECT number,total_kop,status FROM orders WHERE idem_key=?", (key,)).fetchone()
    if old:
        return {"number": old["number"], "total_kop": old["total_kop"], "status": old["status"], "duplicate": True}
    if b.get("consent") is not True:
        raise ApiError(400, "Необходимо согласие на обработку персональных данных")
    bt = b.get("buyer_type")
    if bt not in ("p", "u", "d"):
        raise ApiError(400, "Выберите тип покупателя")
    org = bt != "p"
    cu = b.get("customer")
    if not isinstance(cu, dict):
        raise ApiError(400, "Заполните данные покупателя")
    name = text(cu, "name", 2, 120, label="Имя")
    phone = re.sub(r"[^\d+]", "", text(cu, "phone", 0, 30, True, "Телефон"))
    if len(re.sub(r"\D", "", phone)) < 10:
        raise ApiError(400, "Введите телефон полностью")
    email = text(cu, "email", 0, 120, org, "E-mail")
    if email and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        raise ApiError(400, "Проверьте e-mail")
    addr = text(cu, "address", 5, 300, label="Адрес доставки") if (org or cu.get("delivery") != "Самовывоз") else text(cu, "address", 0, 300)
    orgname, inn, kpp, pos = "", "", "", ""
    if org:
        orgname = text(cu, "org", 2, 250, label="Организация")
        inn = text(cu, "inn", 0, 12, True, "ИНН")
        if not valid_inn(inn):
            raise ApiError(400, "ИНН: 10 или 12 цифр")
        kpp = text(cu, "kpp", 0, 9)
        if kpp and not re.fullmatch(r"\d{9}", kpp):
            raise ApiError(400, "КПП: 9 цифр")
        pos = text(cu, "position", 0, 120)
    delivery, comment = text(cu, "delivery", 0, 120), text(cu, "comment", 0, 2000)
    merged = clean_items(b) if b.get("items") else {}
    if not merged and not org:
        raise ApiError(400, "Корзина пуста")
    c = rq.c
    c.execute("BEGIN IMMEDIATE")  # блокировка записи: проверка и списание остатков — атомарно
    try:
        old = c.execute("SELECT number,total_kop,status FROM orders WHERE idem_key=?", (key,)).fetchone()
        if old:  # параллельный дубль того же запроса, дождавшийся блокировки
            c.execute("ROLLBACK")
            return {"number": old["number"], "total_kop": old["total_kop"], "status": old["status"], "duplicate": True}
        rows, total = [], 0
        for pid, qty in merged.items():
            r = c.execute(PRODUCT_SELECT + " AND p.id=?", (pid,)).fetchone()
            if not r:
                raise ApiError(409, "Один из товаров больше недоступен. Обновите корзину", {"id": pid})
            if r["stock"] < qty:
                raise ApiError(409, f"«{r['name']}»: в наличии {r['stock']} шт.", {"id": pid, "available": r["stock"]})
            rows.append((r, qty)); total += r["price_kop"] * qty  # цена — только из БД
        status = "new" if rows else "request"
        cur = c.execute("INSERT INTO orders(idem_key,status,buyer_type,name,phone,email,address,org,inn,kpp,position,delivery,comment,total_kop,created_at) "
                        "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (key, status, bt, name, phone, email, addr, orgname, inn, kpp, pos, delivery, comment, total, now()))
        oid = cur.lastrowid
        number = f"LP-{datetime.now():%Y%m%d}-{oid:05d}"
        c.execute("UPDATE orders SET number=? WHERE id=?", (number, oid))
        for r, qty in rows:
            c.execute("INSERT INTO order_items(order_id,product_id,sku,name,price_kop,qty) VALUES(?,?,?,?,?,?)", (oid, r["id"], r["sku"], r["name"], r["price_kop"], qty))
            c.execute("UPDATE products SET stock=stock-?, updated_at=? WHERE id=? AND stock>=?", (qty, now(), r["id"], qty))
        c.execute("INSERT INTO order_history(order_id,status,note,at) VALUES(?,?,?,?)", (oid, status, "Создан", now()))
        c.execute("COMMIT")
    except BaseException:
        c.execute("ROLLBACK")
        raise
    return {"number": number, "total_kop": total, "status": status, "duplicate": False}


# ----------------------------------------------------------------------------- админ-API
def h_login(rq, m):
    if not rate_ok("login", rq.ip, 8, 900) or not rate_ok("login-all", "x", 40, 900):
        raise ApiError(429, "Слишком много попыток входа. Подождите 15 минут")
    b = rq.body()
    u = rq.c.execute("SELECT * FROM users WHERE username=?", (str(b.get("username", ""))[:64],)).fetchone()
    pw = str(b.get("password", ""))[:256]
    salt = u["salt"] if u else "00" * 16
    ok = hmac.compare_digest(hash_pw(pw, salt), u["pw_hash"] if u else "0" * 64) and u is not None  # время ответа не выдаёт существование логина
    if not ok:
        raise ApiError(401, "Неверный логин или пароль")
    token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(24)
    rq.c.execute("DELETE FROM sessions WHERE expires_at<?", (int(time.time()),))
    rq.c.execute("INSERT INTO sessions(token_hash,user_id,csrf,expires_at) VALUES(?,?,?,?)",
                 (hashlib.sha256(token.encode()).hexdigest(), u["id"], csrf, int(time.time()) + SESSION_TTL))
    audit(rq.c, u["username"], "login", "session", "", rq.ip)
    rq.set_cookie = f"lp_sid={token}; HttpOnly; SameSite=Strict; Path=/; Max-Age={SESSION_TTL}" + ("; Secure" if SECURE_COOKIES else "")
    return {"ok": True, "csrf": csrf, "user": u["username"]}


def h_logout(rq, m):
    rq.c.execute("DELETE FROM sessions WHERE token_hash=?", (rq.session_hash,))
    audit(rq.c, rq.user, "logout", "session", "", rq.ip)
    rq.set_cookie = "lp_sid=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0" + ("; Secure" if SECURE_COOKIES else "")
    return {"ok": True}


def h_me(rq, m):
    return {"user": rq.user, "csrf": rq.csrf}


def admin_product_row(c, r):
    imgs = [x["path"] for x in c.execute("SELECT path FROM product_images WHERE product_id=? ORDER BY sort,id", (r["id"],))]
    return {"id": r["id"], "sku": r["sku"], "name": r["name"], "description": r["description"], "price": r["price_kop"] / 100, "stock": r["stock"],
            "category_id": r["category_id"], "status": r["status"], "featured": bool(r["featured"]), "sort": r["sort"], "is_demo": bool(r["is_demo"]),
            "seo_title": r["seo_title"], "seo_desc": r["seo_desc"], "images": imgs}


def h_a_products(rq, m):
    q, sql, args = rq.query, "SELECT * FROM products WHERE 1=1", []
    if q.get("status") in PRODUCT_STATUSES:
        sql += " AND status=?"; args.append(q["status"])
    if q.get("q"):
        sql += " AND (plower(name) LIKE ? ESCAPE '\\' OR plower(sku) LIKE ? ESCAPE '\\')"
        like = "%" + q["q"][:80].lower().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        args += [like, like]
    rows = rq.c.execute(sql + " ORDER BY id DESC LIMIT 500", args).fetchall()
    return {"items": [admin_product_row(rq.c, r) for r in rows]}


def clean_product(rq, d, existing=None):
    c = rq.c
    name, sku = text(d, "name", 2, 200, label="Название"), text(d, "sku", 1, 64, label="Артикул")
    if not re.fullmatch(r"[A-Za-z0-9._-]+", sku):
        raise ApiError(400, "Артикул: латиница, цифры, точка, дефис, подчёркивание")
    cat = d.get("category_id")
    if cat in (None, ""):
        cat = None
    else:
        cat = to_int(cat, 1, 10 ** 9, "Категория")
        if not c.execute("SELECT 1 FROM categories WHERE id=?", (cat,)).fetchone():
            raise ApiError(400, "Категория не найдена")
    status = d.get("status", "hidden")
    if status not in PRODUCT_STATUSES:
        raise ApiError(400, "Недопустимый статус")
    price = price_to_kop(d.get("price")) if d.get("price") not in (None, "") else None
    if status == "published" and (price is None or cat is None):
        raise ApiError(400, "Нельзя опубликовать товар без цены и категории")
    if price is None:
        raise ApiError(400, "Укажите цену")
    imgs = d.get("images", [])
    if not isinstance(imgs, list) or len(imgs) > 10 or not all(isinstance(x, str) and UPLOAD_PATH.match(x) and os.path.exists(os.path.join(UPLOADS, x.split("/")[-1])) for x in imgs):
        raise ApiError(400, "Некорректный список изображений")
    return {"name": name, "sku": sku, "description": text(d, "description", 0, 5000), "price_kop": price, "stock": to_int(d.get("stock", 0), 0, 10 ** 6, "Остаток"),
            "category_id": cat, "status": status, "featured": 1 if d.get("featured") else 0, "sort": to_int(d.get("sort", 100), -10 ** 6, 10 ** 6, "Порядок"),
            "seo_title": text(d, "seo_title", 0, 200), "seo_desc": text(d, "seo_desc", 0, 400)}, imgs


def save_product(rq, pid, d):
    v, imgs = clean_product(rq, d)
    c = rq.c
    try:
        c.execute("BEGIN IMMEDIATE")
        if pid is None:
            cur = c.execute("INSERT INTO products(sku,name,description,price_kop,stock,category_id,status,featured,sort,seo_title,seo_desc,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                            (v["sku"], v["name"], v["description"], v["price_kop"], v["stock"], v["category_id"], v["status"], v["featured"], v["sort"], v["seo_title"], v["seo_desc"], now(), now()))
            pid = cur.lastrowid
        else:
            if not c.execute("SELECT 1 FROM products WHERE id=?", (pid,)).fetchone():
                raise ApiError(404, "Товар не найден")
            c.execute("UPDATE products SET sku=?,name=?,description=?,price_kop=?,stock=?,category_id=?,status=?,featured=?,sort=?,seo_title=?,seo_desc=?,updated_at=?,is_demo=0 WHERE id=?",
                      (v["sku"], v["name"], v["description"], v["price_kop"], v["stock"], v["category_id"], v["status"], v["featured"], v["sort"], v["seo_title"], v["seo_desc"], now(), pid))
            c.execute("DELETE FROM product_images WHERE product_id=?", (pid,))
        for i, p in enumerate(imgs):
            c.execute("INSERT INTO product_images(product_id,path,sort) VALUES(?,?,?)", (pid, p, i))
        audit(c, rq.user, "save", "product", pid, rq.ip)
        c.execute("COMMIT")
    except sqlite3.IntegrityError:
        c.execute("ROLLBACK"); raise ApiError(409, "Товар с таким артикулом уже существует")
    except BaseException:
        if c.in_transaction: c.execute("ROLLBACK")
        raise
    return admin_product_row(c, c.execute("SELECT * FROM products WHERE id=?", (pid,)).fetchone())


def h_a_product_create(rq, m):
    return save_product(rq, None, rq.body())


def h_a_product_get(rq, m):
    r = rq.c.execute("SELECT * FROM products WHERE id=?", (int(m.group(1)),)).fetchone()
    if not r:
        raise ApiError(404, "Товар не найден")
    return admin_product_row(rq.c, r)


def h_a_product_put(rq, m):
    return save_product(rq, int(m.group(1)), rq.body())


def h_a_product_del(rq, m):
    pid = int(m.group(1))
    if rq.c.execute("SELECT 1 FROM order_items WHERE product_id=? LIMIT 1", (pid,)).fetchone():
        raise ApiError(409, "Товар есть в заказах — удалять нельзя. Переведите его в архив")
    if rq.query.get("confirm") != "1":
        raise ApiError(400, "Требуется подтверждение удаления")
    rq.c.execute("DELETE FROM products WHERE id=?", (pid,))
    audit(rq.c, rq.user, "delete", "product", pid, rq.ip)
    return {"ok": True}


def admin_cat(r, cnt):
    return {"id": r["id"], "slug": r["slug"], "name": r["name"], "direction": r["direction"], "description": r["description"], "sort": r["sort"],
            "home_order": r["home_order"], "active": bool(r["active"]), "seo_title": r["seo_title"], "seo_desc": r["seo_desc"], "products": cnt}


def h_a_cats(rq, m):
    rows = rq.c.execute("SELECT c.*,(SELECT COUNT(*) FROM products p WHERE p.category_id=c.id) cnt FROM categories c ORDER BY direction DESC, sort, id").fetchall()
    return {"items": [admin_cat(r, r["cnt"]) for r in rows], "directions": [{"id": k, "name": v} for k, v in DIRECTIONS.items()]}


def clean_cat(d):
    slug = text(d, "slug", 2, 64, label="URL-идентификатор").lower()
    if not re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", slug):
        raise ApiError(400, "URL-идентификатор: латиница, цифры и дефисы")
    if d.get("direction") not in DIRECTIONS:
        raise ApiError(400, "Выберите направление")
    return (slug, text(d, "name", 2, 150, label="Название"), d["direction"], text(d, "description", 0, 1000), to_int(d.get("sort", 100), -10 ** 6, 10 ** 6, "Порядок"),
            to_int(d.get("home_order", 100), -10 ** 6, 10 ** 6, "Порядок на главной"), 1 if d.get("active", True) else 0, text(d, "seo_title", 0, 200), text(d, "seo_desc", 0, 400))


def h_a_cat_create(rq, m):
    v = clean_cat(rq.body())
    try:
        cur = rq.c.execute("INSERT INTO categories(slug,name,direction,description,sort,home_order,active,seo_title,seo_desc) VALUES(?,?,?,?,?,?,?,?,?)", v)
    except sqlite3.IntegrityError:
        raise ApiError(409, "Категория с таким URL-идентификатором уже существует")
    audit(rq.c, rq.user, "create", "category", cur.lastrowid, rq.ip)
    return {"id": cur.lastrowid}


def h_a_cat_put(rq, m):
    cid, v = int(m.group(1)), clean_cat(rq.body())
    if not rq.c.execute("SELECT 1 FROM categories WHERE id=?", (cid,)).fetchone():
        raise ApiError(404, "Категория не найдена")
    try:
        rq.c.execute("UPDATE categories SET slug=?,name=?,direction=?,description=?,sort=?,home_order=?,active=?,seo_title=?,seo_desc=? WHERE id=?", v + (cid,))
    except sqlite3.IntegrityError:
        raise ApiError(409, "Категория с таким URL-идентификатором уже существует")
    audit(rq.c, rq.user, "update", "category", cid, rq.ip)
    return {"ok": True}


def h_a_cat_del(rq, m):
    cid = int(m.group(1))
    cnt = rq.c.execute("SELECT COUNT(*) FROM products WHERE category_id=?", (cid,)).fetchone()[0]
    target = rq.query.get("reassign")
    if cnt and not target:
        raise ApiError(409, f"В категории {cnt} товаров. Укажите категорию для переноса", {"products": cnt})
    rq.c.execute("BEGIN IMMEDIATE")
    try:
        if cnt:
            t = to_int(target, 1, 10 ** 9, "Категория переноса")
            if t == cid or not rq.c.execute("SELECT 1 FROM categories WHERE id=?", (t,)).fetchone():
                raise ApiError(400, "Некорректная категория переноса")
            rq.c.execute("UPDATE products SET category_id=? WHERE category_id=?", (t, cid))
        rq.c.execute("DELETE FROM categories WHERE id=?", (cid,))
        audit(rq.c, rq.user, "delete", "category", cid, rq.ip)
        rq.c.execute("COMMIT")
    except BaseException:
        rq.c.execute("ROLLBACK"); raise
    return {"ok": True}


def h_a_settings_get(rq, m):
    return get_settings(rq.c)


def h_a_settings_put(rq, m):
    b, s = rq.body(), get_settings(rq.c)
    for k in ("hero_title", "hero_sub", "hero_btn_text", "hero_btn2_text", "showcase_title", "contacts"):
        if k in b:
            s[k] = text(b, k, 0, 600, label=k)
    for k in ("hero_btn_link", "hero_btn2_link"):
        if k in b:
            v = text(b, k, 1, 300, label=k)
            if not SAFE_LINK.match(v):
                raise ApiError(400, "Ссылка: допустимы только внутренние адреса (#/…, /…) и http(s)")
            s[k] = v
    if "hero_image" in b:
        v = text(b, "hero_image", 0, 100)
        if v and not (UPLOAD_PATH.match(v) or v == "assets/hero.webp"):
            raise ApiError(400, "Некорректное изображение баннера")
        s["hero_image"] = v
    for k in ("showcase_enabled", "hide_empty_categories"):
        if k in b:
            s[k] = bool(b[k])
    if isinstance(b.get("pages"), dict):
        for k, v in b["pages"].items():
            if k in s["pages"]:
                s["pages"][k] = text(b["pages"], k, 0, 30000, label=k)
    rq.c.execute("INSERT INTO settings(key,value) VALUES('site',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (json.dumps(s, ensure_ascii=False),))
    audit(rq.c, rq.user, "update", "settings", "site", rq.ip)
    return s


def h_a_orders(rq, m):
    q, sql, args = rq.query, "SELECT * FROM orders WHERE 1=1", []
    if q.get("status") in ORDER_STATUSES:
        sql += " AND status=?"; args.append(q["status"])
    if q.get("q"):
        sql += " AND (plower(number) LIKE ? OR plower(name) LIKE ? OR phone LIKE ? OR plower(org) LIKE ?)"
        like = "%" + q["q"][:60].lower().replace("\\", "").replace("%", "").replace("_", "") + "%"
        args += [like] * 4
    rows = rq.c.execute(sql + " ORDER BY id DESC LIMIT 300", args).fetchall()
    return {"items": [{k: r[k] for k in ("id", "number", "status", "buyer_type", "name", "org", "total_kop", "created_at")} for r in rows], "statuses": ORDER_STATUSES}


def h_a_order(rq, m):
    r = rq.c.execute("SELECT * FROM orders WHERE id=?", (int(m.group(1)),)).fetchone()
    if not r:
        raise ApiError(404, "Заказ не найден")
    out = {k: r[k] for k in r.keys() if k != "idem_key"}
    out["items"] = [dict(x) for x in rq.c.execute("SELECT sku,name,price_kop,qty FROM order_items WHERE order_id=?", (r["id"],))]
    out["history"] = [dict(x) for x in rq.c.execute("SELECT status,note,at FROM order_history WHERE order_id=? ORDER BY id", (r["id"],))]
    return out


def h_a_order_status(rq, m):
    oid, b = int(m.group(1)), rq.body()
    st, note = b.get("status"), text(b, "note", 0, 500)
    if st not in ORDER_STATUSES:
        raise ApiError(400, "Недопустимый статус")
    rq.c.execute("BEGIN IMMEDIATE")
    try:
        o = rq.c.execute("SELECT status FROM orders WHERE id=?", (oid,)).fetchone()
        if not o:
            raise ApiError(404, "Заказ не найден")
        if o["status"] == "cancelled" and st != "cancelled":
            raise ApiError(409, "Отменённый заказ нельзя возобновить")
        if st == "cancelled" and o["status"] != "cancelled":  # возврат остатков при отмене
            for it in rq.c.execute("SELECT product_id,qty FROM order_items WHERE order_id=?", (oid,)).fetchall():
                rq.c.execute("UPDATE products SET stock=stock+? WHERE id=?", (it["qty"], it["product_id"]))
        rq.c.execute("UPDATE orders SET status=? WHERE id=?", (st, oid))
        rq.c.execute("INSERT INTO order_history(order_id,status,note,at) VALUES(?,?,?,?)", (oid, st, note, now()))
        audit(rq.c, rq.user, "status:" + st, "order", oid, rq.ip)
        rq.c.execute("COMMIT")
    except BaseException:
        rq.c.execute("ROLLBACK"); raise
    return {"ok": True}


def h_a_audit(rq, m):
    return {"items": [dict(r) for r in rq.c.execute("SELECT * FROM audit_log ORDER BY id DESC LIMIT 200")]}


def h_a_upload(rq, m):
    if Image is None:
        raise ApiError(503, "Загрузка изображений недоступна: не установлен Pillow")
    if not rate_ok("upload", rq.ip, 60, 600):
        raise ApiError(429, "Слишком много загрузок")
    try:
        raw = base64.b64decode(str(rq.body().get("data", "")), validate=True)
    except Exception:
        raise ApiError(400, "Некорректные данные файла")
    if not 100 < len(raw) <= 5_000_000:
        raise ApiError(400, "Размер файла: до 5 МБ")
    try:  # формат определяется по содержимому, расширение и MIME клиента игнорируются; SVG и прочее не откроется
        im = Image.open(io.BytesIO(raw))
        if im.format not in ("JPEG", "PNG", "WEBP"):
            raise ValueError
        im.load()
        if im.width > 8000 or im.height > 8000:
            raise ValueError
        im = im.convert("RGBA" if "A" in im.getbands() or im.mode == "P" else "RGB")
        im.thumbnail((1600, 1600))
        name = secrets.token_hex(16) + ".webp"
        im.save(os.path.join(UPLOADS, name), "WEBP", quality=84, method=4)  # перекодирование убирает метаданные и встроенные payload'ы
    except Exception:
        raise ApiError(400, "Допустимы только изображения JPEG, PNG или WebP (до 8000×8000 пикселей)")
    audit(rq.c, rq.user, "upload", "image", name, rq.ip)
    return {"path": "/uploads/" + name}


R = re.compile
PUBLIC_ROUTES = [("GET", R(r"^/api/home$"), h_home), ("GET", R(r"^/api/categories$"), h_categories), ("GET", R(r"^/api/catalog$"), h_catalog),
                 ("GET", R(r"^/api/product/(\d{1,9})$"), h_product), ("GET", R(r"^/api/page/([a-z]{1,20})$"), h_page),
                 ("POST", R(r"^/api/cart/quote$"), h_quote), ("POST", R(r"^/api/orders$"), h_order), ("POST", R(r"^/api/admin/login$"), h_login)]
ADMIN_ROUTES = [("POST", R(r"^/api/admin/logout$"), h_logout), ("GET", R(r"^/api/admin/me$"), h_me),
                ("GET", R(r"^/api/admin/products$"), h_a_products), ("POST", R(r"^/api/admin/products$"), h_a_product_create),
                ("GET", R(r"^/api/admin/products/(\d{1,9})$"), h_a_product_get), ("PUT", R(r"^/api/admin/products/(\d{1,9})$"), h_a_product_put),
                ("DELETE", R(r"^/api/admin/products/(\d{1,9})$"), h_a_product_del),
                ("GET", R(r"^/api/admin/categories$"), h_a_cats), ("POST", R(r"^/api/admin/categories$"), h_a_cat_create),
                ("PUT", R(r"^/api/admin/categories/(\d{1,9})$"), h_a_cat_put), ("DELETE", R(r"^/api/admin/categories/(\d{1,9})$"), h_a_cat_del),
                ("GET", R(r"^/api/admin/settings$"), h_a_settings_get), ("PUT", R(r"^/api/admin/settings$"), h_a_settings_put),
                ("GET", R(r"^/api/admin/orders$"), h_a_orders), ("GET", R(r"^/api/admin/orders/(\d{1,9})$"), h_a_order),
                ("PUT", R(r"^/api/admin/orders/(\d{1,9})/status$"), h_a_order_status),
                ("GET", R(r"^/api/admin/audit$"), h_a_audit), ("POST", R(r"^/api/admin/upload$"), h_a_upload)]

CSP = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; font-src https://fonts.gstatic.com; "
       "img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'")


class Handler(BaseHTTPRequestHandler):
    server_version = "Lavka"
    sys_version = ""
    protocol_version = "HTTP/1.0"  # без keep-alive: непрочитанное тело отклонённого запроса не «склеивается» со следующим

    def log_message(self, fmt, *a):  # без query-строки и персональных данных
        sys.stderr.write("%s %s\n" % (self.address_string(), (fmt % a).split("?")[0]))

    # --- ответ
    def _send(self, code, body, ctype, extra=None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        for k, v in {"X-Content-Type-Options": "nosniff", "Referrer-Policy": "strict-origin-when-cross-origin", "Content-Security-Policy": CSP,
                     "X-Frame-Options": "DENY", "Permissions-Policy": "camera=(), microphone=(), geolocation=()", **(extra or {})}.items():
            self.send_header(k, v)
        if getattr(self, "set_cookie", None):
            self.send_header("Set-Cookie", self.set_cookie)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, code, obj):
        self._send(code, json.dumps(obj, ensure_ascii=False).encode(), "application/json; charset=utf-8", {"Cache-Control": "no-store"})

    def body(self):
        ct = (self.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        if ct != "application/json":
            raise ApiError(415, "Ожидается application/json")
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            raise ApiError(400, "Некорректный запрос")
        if n > (8_000_000 if self.path.startswith("/api/admin/upload") else 100_000):
            raise ApiError(413, "Слишком большой запрос")
        try:
            d = json.loads(self.rfile.read(n) or b"{}")
        except ValueError:
            raise ApiError(400, "Некорректный JSON")
        if not isinstance(d, dict):
            raise ApiError(400, "Ожидается объект JSON")
        return d

    # --- маршрутизация
    def do_GET(self): self.dispatch()
    do_HEAD = do_POST = do_PUT = do_DELETE = do_GET

    def do_OPTIONS(self):  # CORS не включаем: сайт и API — один origin
        self._send(204, b"", "text/plain")

    def dispatch(self):
        self.set_cookie, self.c = None, None
        u = urlparse(self.path)
        try:
            self.query = {k: v[0] for k, v in parse_qs(u.query, max_num_fields=20).items()}
        except ValueError:
            self.query = {}
        self.ip = (self.headers.get("X-Forwarded-For", "").split(",")[-1].strip() if TRUST_PROXY else "") or self.client_address[0]
        method = "GET" if self.command == "HEAD" else self.command
        try:
            if u.path.startswith("/api/"):
                self.api(method, u.path)
            elif method == "GET":
                self.static(u.path)
            else:
                raise ApiError(405, "Метод не поддерживается")
        except ApiError as e:
            if u.path.startswith("/api/"):
                self._json(e.code, {"error": e.msg, **e.extra})
            else:
                self._send(e.code, e.msg.encode(), "text/plain; charset=utf-8")
        except Exception as e:  # детали — только в лог сервера
            sys.stderr.write(f"ERROR {type(e).__name__}: {e}\n")
            self._json(500, {"error": "Внутренняя ошибка сервера"})
        finally:
            if self.c:
                self.c.close()

    def api(self, method, path):
        route, adm = None, False
        for rows, a in ((PUBLIC_ROUTES, False), (ADMIN_ROUTES, True)):
            for mt, rx, fn in rows:
                mo = rx.match(path)
                if mo and mt == method:
                    route, adm = (fn, mo), a
        if not route:
            raise ApiError(404, "Не найдено")
        self.c = connect()
        self.user = self.csrf = self.session_hash = None
        if adm:
            self.auth(method)
        self._json(200, route[0](self, route[1]))

    def auth(self, method):
        ck = SimpleCookie(self.headers.get("Cookie", ""))
        tok = ck["lp_sid"].value if "lp_sid" in ck else ""
        h = hashlib.sha256(tok.encode()).hexdigest()
        r = self.c.execute("SELECT s.csrf,u.username FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.token_hash=? AND s.expires_at>?", (h, int(time.time()))).fetchone() if tok else None
        if not r:
            raise ApiError(401, "Требуется вход")
        self.user, self.csrf, self.session_hash = r["username"], r["csrf"], h
        if method != "GET":
            origin = self.headers.get("Origin")
            if origin and urlparse(origin).netloc != self.headers.get("Host"):
                raise ApiError(403, "Недопустимый источник запроса")
            if not hmac.compare_digest(self.headers.get("X-CSRF-Token", ""), r["csrf"]):
                raise ApiError(403, "Недействительный CSRF-токен")

    def static(self, path):
        path = unquote(path)
        if "\x00" in path:
            raise ApiError(404, "Не найдено")
        if re.fullmatch(r"/uploads/[0-9a-f]{32}\.webp", path):
            f = os.path.join(UPLOADS, path.split("/")[-1])
            ctrl = {"Cache-Control": "public, max-age=31536000, immutable"}
        else:
            if path == "/admin":
                return self._send(301, b"", "text/plain", {"Location": "/admin/"})
            if path.endswith("/"):
                path += "index.html"
            f = os.path.realpath(os.path.join(PUBLIC, path.lstrip("/")))
            if "\x00" in path or not (f == PUBLIC or f.startswith(PUBLIC + os.sep)):
                raise ApiError(404, "Не найдено")
            ctrl = {"Cache-Control": "no-cache"}
            if path.startswith("/admin/"):
                ctrl["X-Robots-Tag"] = "noindex, nofollow"
        if not os.path.isfile(f):
            raise ApiError(404, "Страница не найдена")
        ctype = mimetypes.guess_type(f)[0] or "application/octet-stream"
        if ctype in ("text/html", "text/css", "application/javascript", "text/javascript"):
            ctype += "; charset=utf-8"
        with open(f, "rb") as fh:
            self._send(200, fh.read(), ctype, ctrl)


def make_server(host, port):
    init_db()
    return ThreadingHTTPServer((host, port), Handler)


def backup():
    os.makedirs(os.path.join(DATA, "backups"), exist_ok=True)
    dst = os.path.join(DATA, "backups", f"shop-{datetime.now():%Y%m%d-%H%M%S}.db")
    src, out = connect(), sqlite3.connect(dst)
    src.backup(out); out.close(); src.close()
    print("Резервная копия:", dst)


if __name__ == "__main__":
    if "--backup" in sys.argv:
        backup()
    elif "--reset-admin" in sys.argv:
        init_db(); c = connect(); pw = getpass.getpass("Новый пароль администратора (мин. 10 символов): ")
        if len(pw) < 10:
            sys.exit("Пароль слишком короткий")
        set_admin(c, pw); print("Пароль изменён, все сессии завершены.")
    else:
        host, port = os.environ.get("LP_HOST", "127.0.0.1"), int(os.environ.get("LP_PORT", "8000"))
        srv = make_server(host, port)
        print(f"Лавка логопеда: http://{host}:{port}  (админка: /admin/)", file=sys.stderr)
        try:
            srv.serve_forever()
        except KeyboardInterrupt:
            pass
