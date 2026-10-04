"""MelasGo2 v2 - server Python (solo libreria standard).
Avvio: python server.py  ->  http://localhost:8000
Variabile opzionale APK_URL: link di download dell'APK (mostrato nel tasto Scarica).
"""
import json, os, threading, time, uuid, mimetypes, base64
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

ROOT = os.path.dirname(os.path.abspath(__file__))
STATIC = os.path.join(ROOT, "static")
DBF = os.path.join(ROOT, "data.json")
LOCK = threading.Lock()
MAX_USERS = 15
APK_URL = os.environ.get("APK_URL", "")
PRES, TYP = {}, {}  # presenza online e "sta scrivendo" (solo in memoria)


def load():
    try:
        with open(DBF, encoding="utf-8") as f:
            d = json.load(f)
    except Exception:
        d = {}
    for k, v in (("users", {}), ("places", []), ("chat", []), ("mid", 0)):
        d.setdefault(k, v)
    for u in d["users"].values():
        u.setdefault("v", 1)
        u.setdefault("photo", "")
    return d


DB = load()


def save():
    tmp = DBF + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(DB, f)
    os.replace(tmp, DBF)


def state(q):
    uid = q.get("user", [""])[0]
    if uid not in DB["users"]:
        return None
    now = time.time()
    PRES[uid] = now
    if q.get("t", ["0"])[0] == "1":
        TYP[uid] = now
    try:
        after = int(q.get("after", ["0"])[0])
    except ValueError:
        after = 0
    users = {k: {"n": u["name"], "v": u["v"], "p": bool(u["photo"]),
                 "on": now - PRES.get(k, 0) < 9} for k, u in DB["users"].items()}
    return {"users": users,
            "typing": [k for k, t in TYP.items() if k != uid and k in users and now - t < 3.5],
            "places": DB["places"],
            "chat": [m for m in DB["chat"] if m["i"] > after][-150:],
            "mid": DB["mid"], "max": MAX_USERS, "apk": APK_URL}


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def send_json(self, obj, code=200):
        b = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        p = urlparse(self.path)
        q = parse_qs(p.query)
        if p.path == "/api/state":
            with LOCK:
                s = state(q)
            return self.send_json(s if s else {"error": "login"}, 200 if s else 401)
        if p.path == "/api/photo":
            with LOCK:
                u = DB["users"].get(q.get("u", [""])[0])
                ph = u["photo"] if u else ""
            if not ph.startswith("data:"):
                return self.send_error(404)
            head, b64 = ph.split(",", 1)
            data = base64.b64decode(b64)
            self.send_response(200)
            self.send_header("Content-Type", head[5:].split(";")[0])
            self.send_header("Cache-Control", "public, max-age=31536000, immutable")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            return self.wfile.write(data)
        path = "/index.html" if p.path == "/" else p.path
        fp = os.path.realpath(os.path.join(STATIC, path.lstrip("/")))
        if not fp.startswith(STATIC) or not os.path.isfile(fp):
            return self.send_error(404)
        data = open(fp, "rb").read()
        self.send_response(200)
        self.send_header("Content-Type", mimetypes.guess_type(fp)[0] or "application/octet-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        try:
            n = int(self.headers.get("Content-Length", 0))
            if n > 200000:
                return self.send_json({"error": "big"}, 413)
            b = json.loads(self.rfile.read(n) or b"{}")
        except Exception:
            return self.send_json({"error": "bad"}, 400)
        route = urlparse(self.path).path
        with LOCK:
            uid = b.get("user")
            if route == "/api/login":
                name = str(b.get("name", "")).strip()[:20]
                if not name:
                    return self.send_json({"error": "name"}, 400)
                photo = b.get("photo")
                if uid in DB["users"]:
                    u = DB["users"][uid]
                    u["name"] = name
                    if photo is not None:
                        u["photo"] = str(photo)[:60000]
                        u["v"] += 1
                else:
                    if len(DB["users"]) >= MAX_USERS:
                        return self.send_json({"error": "full"}, 403)
                    uid = uuid.uuid4().hex[:10]
                    DB["users"][uid] = {"name": name, "photo": str(photo or "")[:60000], "v": 1}
                save()
                return self.send_json({"id": uid})
            if uid not in DB["users"]:
                return self.send_json({"error": "login"}, 401)
            if route == "/api/place":
                t = str(b.get("title", "")).strip()[:60]
                if t and len(DB["places"]) < 60:
                    DB["places"].append({"id": uuid.uuid4().hex[:8], "title": t,
                                         "desc": str(b.get("desc", ""))[:200],
                                         "cost": str(b.get("cost", ""))[:20],
                                         "by": uid, "votes": [uid], "ts": int(time.time())})
            elif route == "/api/vote":
                for p in DB["places"]:
                    if p["id"] == b.get("place"):
                        p["votes"] = [v for v in p["votes"] if v != uid] if uid in p["votes"] else p["votes"] + [uid]
            elif route == "/api/del":  # solo chi ha proposto
                DB["places"] = [p for p in DB["places"] if not (p["id"] == b.get("place") and p["by"] == uid)]
            elif route == "/api/chat":
                t = str(b.get("text", "")).strip()[:500]
                if t:
                    DB["mid"] += 1
                    DB["chat"].append({"i": DB["mid"], "u": uid, "x": t, "ts": int(time.time())})
                    DB["chat"] = DB["chat"][-500:]
                    TYP.pop(uid, None)
            save()
            return self.send_json({"ok": True})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    print(f"MelasGo2 attivo su http://0.0.0.0:{port}")
    ThreadingHTTPServer(("0.0.0.0", port), H).serve_forever()
