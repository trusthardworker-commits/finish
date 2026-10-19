import base64, http.client, io, json, os, sys, tempfile, threading, unittest, uuid

TMP = tempfile.mkdtemp()
os.environ.update(LP_DATA_DIR=TMP, LP_DB=os.path.join(TMP, "t.db"), LP_ADMIN_PASSWORD="Test-Passw0rd-123", LP_SEED_DEMO="1")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "server"))
import app  # noqa: E402

SRV = app.make_server("127.0.0.1", 0)
PORT = SRV.server_address[1]
threading.Thread(target=SRV.serve_forever, daemon=True).start()
PW = "Test-Passw0rd-123"


def call(method, path, body=None, cookie=None, csrf=None, headers=None, raw=None):
    c = http.client.HTTPConnection("127.0.0.1", PORT, timeout=15)
    h = dict(headers or {})
    data = raw
    if body is not None:
        data = json.dumps(body); h["Content-Type"] = "application/json"
    if cookie: h["Cookie"] = cookie
    if csrf: h["X-CSRF-Token"] = csrf
    c.request(method, path, data, h)
    r = c.getresponse(); b = r.read()
    try: j = json.loads(b)
    except ValueError: j = None
    hd = {k.lower(): v for k, v in r.getheaders()}
    c.close()
    return r.status, j, hd, b


def login():
    s, j, hd, _ = call("POST", "/api/admin/login", {"username": "admin", "password": PW})
    assert s == 200, j
    return hd["set-cookie"].split(";")[0], j["csrf"]


def png(color=(200, 30, 30), size=(64, 64)):
    from PIL import Image
    b = io.BytesIO(); Image.new("RGB", size, color).save(b, "PNG"); return base64.b64encode(b.getvalue()).decode()


class Base(unittest.TestCase):
    def setUp(self):
        with app._rl_lock: app._rl.clear()

    def adm(self, method, path, body=None, ck=None):
        ck = ck or self.ck
        return call(method, "/api/admin" + path, body, cookie=ck[0], csrf=ck[1])

    @classmethod
    def setUpClass(cls):
        cls.ck = login()


class TestPublic(Base):
    def test_home_banner_and_showcase(self):
        s, j, *_ = call("GET", "/api/home")
        self.assertEqual(j["settings"]["hero_title"], "Всё для речи и развития дошкольника")
        slugs = [p["category"]["slug"] for p in j["showcase"]]
        self.assertEqual(len(slugs), len(set(slugs)), "по одному товару из категории")
        self.assertTrue(all(p["in_stock"] for p in j["showcase"]))
        self.assertNotIn("motor", slugs, "товар с нулевым остатком не показывается")
        self.assertGreater(len(slugs), 10)

    def test_removed_categories_absent_and_directions(self):
        s, j, *_ = call("GET", "/api/categories")
        names = " ".join(c["name"] for c in j["categories"])
        self.assertNotIn("Готовые комплекты", names); self.assertNotIn("Оборудование для кабинета", names)
        self.assertEqual({c["direction"] for c in j["categories"]}, {"logoped", "stationery"})

    def test_catalog_filters_sort_search(self):
        s, j, *_ = call("GET", "/api/catalog?dir=stationery&per=48")
        self.assertTrue(j["items"] and all(p["category"]["direction"] == "stationery" for p in j["items"]))
        s, j, *_ = call("GET", "/api/catalog?q=" + "%D0%9A%D0%90%D0%A0%D0%90%D0%9D%D0%94%D0%90%D0%A8")  # верхний регистр кириллицы
        self.assertTrue(any("карандаш" in p["name"].lower() for p in j["items"]))
        s, j, *_ = call("GET", "/api/catalog?sort=price_asc&per=48&instock=1&min=100&max=300")
        pr = [p["price_kop"] for p in j["items"]]
        self.assertEqual(pr, sorted(pr)); self.assertTrue(all(10000 <= x <= 30000 for x in pr))

    def test_catalog_bad_input(self):
        for q in ("sort=price_asc%3BDROP%20TABLE%20products", "min=abc", "page=0", "per=1000", "dir=evil", "ids=1,x"):
            self.assertEqual(call("GET", "/api/catalog?" + q)[0], 400, q)
        for q in ("q=%27%20OR%201%3D1--", "cat=%27%3B%20DROP%20TABLE%20products%3B--", "q=%25%5F"):
            s, j, *_ = call("GET", "/api/catalog?" + q); self.assertEqual(s, 200); self.assertEqual(j["total"] if "OR" in q or "DROP" in q else 0, 0)
        self.assertGreater(call("GET", "/api/catalog")[1]["total"], 0, "таблица цела")

    def test_unknown_product_404(self):
        self.assertEqual(call("GET", "/api/product/999999")[0], 404)


class TestCartAndOrders(Base):
    def prod(self, sku):
        return next(p for p in call("GET", "/api/catalog?per=48&q=" + sku)[1]["items"] if p["sku"] == sku)

    def order(self, items, key=None, bt="p", **cu):
        c = {"name": "Иван", "phone": "+7 900 123-45-67", "address": "г. Москва, ул. Ленина, 1", **cu}
        return call("POST", "/api/orders", {"idem_key": key or uuid.uuid4().hex, "buyer_type": bt, "consent": True, "items": items, "customer": c})

    def test_quote_ignores_client_prices_and_clamps(self):
        p = self.prod("10234")
        s, j, *_ = call("POST", "/api/cart/quote", {"items": [{"id": p["id"], "qty": 500, "price_kop": 1, "total": 1}]})
        ln = j["lines"][0]
        self.assertEqual(ln["price_kop"], p["price_kop"]); self.assertLessEqual(ln["qty"], p["max_qty"]); self.assertEqual(j["total_kop"], ln["price_kop"] * ln["qty"])
        self.assertFalse(call("POST", "/api/cart/quote", {"items": [{"id": 999999, "qty": 1}]})[1]["lines"][0]["available"])
        for bad in ({"id": p["id"], "qty": 0}, {"id": p["id"], "qty": -3}, {"id": p["id"], "qty": "1e9"}, {"id": "x", "qty": 1}):
            self.assertEqual(call("POST", "/api/cart/quote", {"items": [bad]})[0], 400, bad)

    def test_order_price_from_db_stock_decrement_and_idempotency(self):
        p = self.prod("S-005"); key = uuid.uuid4().hex
        s, j, *_ = call("POST", "/api/orders", {"idem_key": key, "buyer_type": "p", "consent": True, "total_kop": 1, "items": [{"id": p["id"], "qty": 2, "price_kop": 1}],
                                                  "customer": {"name": "Иван", "phone": "89001234567", "address": "г. Москва, ул. Ленина, 1"}})
        self.assertEqual(s, 200, j); self.assertEqual(j["total_kop"], p["price_kop"] * 2)
        s2, j2, *_ = call("POST", "/api/orders", {"idem_key": key, "buyer_type": "p", "consent": True, "items": [{"id": p["id"], "qty": 2}], "customer": {"name": "Иван", "phone": "89001234567", "address": "г. Москва, ул. Ленина, 1"}})
        self.assertTrue(j2["duplicate"]); self.assertEqual(j2["number"], j["number"])
        after = self.prod("S-005"); self.assertEqual(after["max_qty"], min(80 - 2, 99), "остаток списан один раз")

    def test_order_validation(self):
        p = self.prod("S-002")
        self.assertEqual(self.order([{"id": p["id"], "qty": 9999}])[0], 400)
        self.assertEqual(self.order([{"id": p["id"], "qty": 99}], phone="123")[0], 400)
        self.assertEqual(self.order([])[0], 400, "пустая корзина у физлица")
        s, j, *_ = call("POST", "/api/orders", {"idem_key": uuid.uuid4().hex, "buyer_type": "p", "items": [{"id": p["id"], "qty": 1}], "customer": {"name": "Иван", "phone": "89001234567", "address": "г. Москва, ул. 1"}})
        self.assertEqual(s, 400, "без согласия на обработку ПДн")
        self.assertEqual(self.order([{"id": p["id"], "qty": 1}], key="short")[0], 400)

    def test_oversell_rejected(self):
        p = self.prod("S-008")  # демо-остаток 18
        s, j, *_ = self.order([{"id": p["id"], "qty": 99}])
        self.assertEqual(s, 409, j)

    def test_org_request_without_items_and_inn_validation(self):
        base = dict(org="МБДОУ Детский сад № 1", inn="7707083893", email="a@b.ru", position="Заведующий")
        s, j, *_ = self.order([], bt="d", **base); self.assertEqual(s, 200, j); self.assertEqual(j["status"], "request")
        self.assertEqual(self.order([], bt="d", **{**base, "inn": "123"})[0], 400)
        self.assertEqual(self.order([], bt="u", **{**base, "email": ""})[0], 400)

    def test_concurrent_orders_do_not_oversell(self):
        ck = login()
        s, j, *_ = call("POST", "/api/admin/products", {"sku": "RACE-1", "name": "Товар для гонки", "price": "10", "stock": 3, "category_id": 1, "status": "published"}, cookie=ck[0], csrf=ck[1]); self.assertEqual(s, 200, j)
        pid, res = j["id"], []
        def go():
            res.append(self.order([{"id": pid, "qty": 1}])[0])
        ts = [threading.Thread(target=go) for _ in range(8)]
        [t.start() for t in ts]; [t.join() for t in ts]
        self.assertEqual(sorted(res), [200] * 3 + [409] * 5, res)

    def test_order_rate_limit(self):
        p = self.prod("S-002"); codes = [self.order([{"id": p["id"], "qty": 1}])[0] for _ in range(11)]
        self.assertEqual(codes[-1], 429)


class TestAdmin(Base):
    def test_requires_auth(self):
        for m, path in (("GET", "/products"), ("POST", "/products"), ("GET", "/orders"), ("PUT", "/settings"), ("POST", "/upload"), ("GET", "/audit"), ("GET", "/me")):
            self.assertEqual(call(m, "/api/admin" + path, {} if m != "GET" else None)[0], 401, path)
        self.assertEqual(call("GET", "/api/admin/me", cookie="lp_sid=forged")[0], 401)

    def test_login_wrong_and_rate_limit(self):
        self.assertEqual(call("POST", "/api/admin/login", {"username": "admin", "password": "wrong"})[0], 401)
        codes = [call("POST", "/api/admin/login", {"username": "admin", "password": "x%d" % i})[0] for i in range(10)]
        self.assertEqual(codes[-1], 429)

    def test_cookie_flags_csrf_origin(self):
        s, j, hd, _ = call("POST", "/api/admin/login", {"username": "admin", "password": PW})
        sc = hd["set-cookie"]; self.assertIn("HttpOnly", sc); self.assertIn("SameSite=Strict", sc)
        ck = (sc.split(";")[0], j["csrf"])
        self.assertEqual(call("POST", "/api/admin/categories", {"x": 1}, cookie=ck[0])[0], 403, "без CSRF-токена")
        self.assertEqual(call("POST", "/api/admin/categories", {"x": 1}, cookie=ck[0], csrf="bad")[0], 403)
        self.assertEqual(call("POST", "/api/admin/categories", {"x": 1}, cookie=ck[0], csrf=ck[1], headers={"Origin": "http://evil.example"})[0], 403)

    def test_logout_invalidates_session(self):
        ck = login(); self.assertEqual(call("GET", "/api/admin/me", cookie=ck[0])[0], 200)
        self.assertEqual(call("POST", "/api/admin/logout", {}, cookie=ck[0], csrf=ck[1])[0], 200)
        self.assertEqual(call("GET", "/api/admin/me", cookie=ck[0])[0], 401)

    def test_category_crud_rules(self):
        body = {"name": "Тест", "slug": "test-cat", "direction": "stationery", "sort": 5}
        s, j, *_ = self.adm("POST", "/categories", body); self.assertEqual(s, 200, j)
        cid = j["id"]
        self.assertEqual(self.adm("POST", "/categories", body)[0], 409, "дубликат URL")
        self.assertEqual(self.adm("POST", "/categories", {**body, "slug": "Bad Slug!"})[0], 400)
        self.assertEqual(self.adm("POST", "/categories", {**body, "slug": "x2", "direction": "evil"})[0], 400)
        s, j, *_ = self.adm("POST", "/products", {"sku": "T-1", "name": "Тестовый товар", "price": "99.50", "stock": 4, "category_id": cid, "status": "published"}); self.assertEqual(s, 200, j)
        self.assertEqual(self.adm("DELETE", f"/categories/{cid}")[0], 409, "в категории есть товары")
        other = next(c for c in self.adm("GET", "/categories")[1]["items"] if c["slug"] == "paper")["id"]
        self.assertEqual(self.adm("DELETE", f"/categories/{cid}?reassign={other}")[0], 200)
        moved = call("GET", "/api/catalog?q=T-1")[1]["items"][0]; self.assertEqual(moved["category"]["slug"], "paper")

    def test_product_validation_and_visibility(self):
        ok = {"sku": "V-1", "name": "Видимый товар", "price": "10", "stock": 2, "category_id": 11, "status": "published"}
        for bad in ({"name": ""}, {"price": "-5"}, {"price": "abc"}, {"price": "1.234"}, {"stock": -1}, {"stock": "x"}, {"sku": "плохой артикул"}, {"category_id": 99999}, {"category_id": None}, {"name": "x" * 300}):
            self.assertEqual(self.adm("POST", "/products", {**ok, "sku": "V-X", **bad})[0], 400, bad)
        s, j, *_ = self.adm("POST", "/products", ok); self.assertEqual(s, 200, j); pid = j["id"]
        self.assertEqual(self.adm("POST", "/products", ok)[0], 409, "дубль артикула")
        self.assertTrue(any(p["sku"] == "V-1" for p in call("GET", "/api/catalog?q=V-1")[1]["items"]))
        self.adm("PUT", f"/products/{pid}", {**ok, "status": "hidden"})
        self.assertEqual(call("GET", f"/api/product/{pid}")[0], 404, "скрытый товар недоступен публично")
        self.assertEqual(call("POST", "/api/cart/quote", {"items": [{"id": pid, "qty": 1}]})[1]["lines"][0]["available"], False)
        self.adm("PUT", f"/products/{pid}", {**ok, "status": "published", "price": "12.5", "stock": 0})
        pub = call("GET", f"/api/product/{pid}")[1]; self.assertEqual(pub["price_kop"], 1250); self.assertFalse(pub["in_stock"])

    def test_xss_payload_stored_as_text_only(self):
        s, j, *_ = self.adm("POST", "/products", {"sku": "XSS-1", "name": "<img src=x onerror=alert(1)>", "description": "<script>alert(1)</script>", "price": "5", "stock": 1, "category_id": 11, "status": "published"})
        self.assertEqual(s, 200); st, d, hd, _ = call("GET", f"/api/product/{j['id']}")
        self.assertIn("application/json", hd["content-type"]); self.assertEqual(d["name"], "<img src=x onerror=alert(1)>")

    def test_delete_product_in_orders_blocked(self):
        p = call("GET", "/api/catalog?q=S-003")[1]["items"][0]
        call("POST", "/api/orders", {"idem_key": uuid.uuid4().hex, "buyer_type": "p", "consent": True, "items": [{"id": p["id"], "qty": 1}], "customer": {"name": "Иван", "phone": "89001234567", "address": "г. Москва, ул. 1-я"}})
        self.assertEqual(self.adm("DELETE", f"/products/{p['id']}?confirm=1")[0], 409)

    def test_upload_rules(self):
        s, j, *_ = self.adm("POST", "/upload", {"data": png()}); self.assertEqual(s, 200, j); path = j["path"]
        self.assertRegex(path, r"^/uploads/[0-9a-f]{32}\.webp$")
        st, _, hd, body = call("GET", path); self.assertEqual(st, 200); self.assertEqual(hd["content-type"], "image/webp"); self.assertEqual(hd["x-content-type-options"], "nosniff")
        evil = {"html": b"<html><script>alert(1)</script></html>", "svg": b"<svg xmlns='http://www.w3.org/2000/svg' onload='alert(1)'><script>alert(1)</script></svg>", "php": b"<?php system($_GET['c']); ?>" + b"x" * 200, "gif-header-php": b"GIF89a<?php evil(); ?>" + b"x" * 200}
        for name, data in evil.items():
            self.assertEqual(self.adm("POST", "/upload", {"data": base64.b64encode(data).decode()})[0], 400, name)
        self.assertEqual(self.adm("POST", "/upload", {"data": "!!!not-base64"})[0], 400)
        self.assertEqual(self.adm("POST", "/upload", {"data": base64.b64encode(b"x" * 5_100_000).decode()})[0], 400)
        s, j, *_ = self.adm("POST", "/products", {"sku": "IMG-1", "name": "С картинкой", "price": "5", "stock": 1, "category_id": 11, "status": "published", "images": [path]}); self.assertEqual(s, 200, j)
        self.assertEqual(self.adm("POST", "/products", {"sku": "IMG-2", "name": "Плохая картинка", "price": "5", "stock": 1, "category_id": 11, "images": ["/uploads/../../etc/passwd"]})[0], 400)

    def test_settings_and_safe_links(self):
        self.assertEqual(self.adm("PUT", "/settings", {"hero_btn_link": "javascript:alert(1)"})[0], 400)
        self.assertEqual(self.adm("PUT", "/settings", {"hero_btn_link": "//evil.example/x"})[0], 400)
        self.assertEqual(self.adm("PUT", "/settings", {"hero_btn_link": "#/catalog?dir=logoped", "showcase_title": "Популярное"})[0], 200)
        self.assertEqual(call("GET", "/api/home")[1]["settings"]["showcase_title"], "Популярное")
        self.adm("PUT", "/settings", {"showcase_title": "Товары в наличии", "hero_btn_link": "#/catalog"})

    def test_order_cancel_restocks_and_history(self):
        p = call("GET", "/api/catalog?q=S-007")[1]["items"][0]; before = p["max_qty"]
        s, j, *_ = call("POST", "/api/orders", {"idem_key": uuid.uuid4().hex, "buyer_type": "p", "consent": True, "items": [{"id": p["id"], "qty": 3}], "customer": {"name": "Иван", "phone": "89001234567", "address": "г. Москва, ул. 1-я"}})
        oid = next(o["id"] for o in self.adm("GET", "/orders")[1]["items"] if o["number"] == j["number"])
        self.assertEqual(call("GET", "/api/catalog?q=S-007")[1]["items"][0]["max_qty"], before - 3)
        self.assertEqual(self.adm("PUT", f"/orders/{oid}/status", {"status": "cancelled", "note": "тест"})[0], 200)
        self.assertEqual(call("GET", "/api/catalog?q=S-007")[1]["items"][0]["max_qty"], before)
        self.assertEqual(self.adm("PUT", f"/orders/{oid}/status", {"status": "new"})[0], 409)
        d = self.adm("GET", f"/orders/{oid}")[1]; self.assertEqual([h["status"] for h in d["history"]], ["new", "cancelled"]); self.assertNotIn("idem_key", d)


class TestStaticAndHeaders(Base):
    def test_headers(self):
        _, _, hd, _ = call("GET", "/")
        self.assertIn("default-src 'self'", hd["content-security-policy"]); self.assertIn("frame-ancestors 'none'", hd["content-security-policy"])
        self.assertEqual(hd["x-content-type-options"], "nosniff"); self.assertIn("referrer-policy", hd)
        self.assertNotIn("access-control-allow-origin", hd)
        self.assertIn("noindex", call("GET", "/admin/")[2]["x-robots-tag"])

    def test_path_traversal_and_private_files(self):
        for p in ("/../server/app.py", "/%2e%2e/server/app.py", "/..%2fserver%2fapp.py", "/data/t.db", "/server/app.py", "/.git/config", "/js/../../server/app.py", "/uploads/../t.db", "/%00"):
            s, *_ = call("GET", p); self.assertEqual(s, 404, p)

    def test_errors_do_not_leak_and_method_rules(self):
        s, j, _, b = call("POST", "/api/catalog", {}); self.assertEqual(s, 404); self.assertNotIn(b"Traceback", b)
        s, j, *_ = call("POST", "/api/orders", raw=b"{bad json", headers={"Content-Type": "application/json"}); self.assertEqual(s, 400)
        self.assertEqual(call("POST", "/api/cart/quote", raw=b"items=1", headers={"Content-Type": "application/x-www-form-urlencoded"})[0], 415)
        self.assertEqual(call("POST", "/api/cart/quote", raw=b"x" * 200_000, headers={"Content-Type": "application/json"})[0], 413)


if __name__ == "__main__":
    unittest.main(verbosity=2)
