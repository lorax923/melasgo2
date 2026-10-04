"""MelasGo2 - server Python (solo libreria standard, nessuna installazione).
Avvio:  python server.py   ->  http://localhost:8000
"""
import json, os, threading, time, uuid, mimetypes
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler

ROOT = os.path.dirname(os.path.abspath(__file__))
STATIC = os.path.join(ROOT, "static")
DB = os.path.join(ROOT, "data.json")
LOCK = threading.Lock()


def load():
    try:
        with open(DB, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"users": {}, "places": [], "chat": []}


def save(d):
    with open(DB, "w", encoding="utf-8") as f:
        json.dump(d, f)


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def send_json(self, obj, code=200):
        b = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/api/state":
            with LOCK:
                return self.send_json(load())
        if path == "/":
            path = "/index.html"
        fp = os.path.realpath(os.path.join(STATIC, path.lstrip("/")))
        if not fp.startswith(STATIC) or not os.path.isfile(fp):
            self.send_response(404)
            self.end_headers()
            return
        data = open(fp, "rb").read()
        self.send_response(200)
        self.send_header("Content-Type", mimetypes.guess_type(fp)[0] or "application/octet-stream")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        try:
            n = int(self.headers.get("Content-Length", 0))
            if n > 200000:
                return self.send_json({"error": "troppo grande"}, 413)
            b = json.loads(self.rfile.read(n) or b"{}")
        except Exception:
            return self.send_json({"error": "bad"}, 400)
        route = self.path.split("?")[0]
        with LOCK:
            d = load()
            uid = b.get("user")
            if route == "/api/login":
                name = str(b.get("name", "")).strip()[:30]
                if not name:
                    return self.send_json({"error": "nome"}, 400)
                uid = uid if uid in d["users"] else uuid.uuid4().hex[:10]
                d["users"][uid] = {"name": name, "photo": str(b.get("photo", ""))[:60000]}
                save(d)
                return self.send_json({"id": uid})
            if uid not in d["users"]:
                return self.send_json({"error": "login"}, 401)
            if route == "/api/place":
                t = str(b.get("title", "")).strip()[:60]
                if t:
                    d["places"].append({
                        "id": uuid.uuid4().hex[:8], "title": t,
                        "desc": str(b.get("desc", ""))[:200],
                        "cost": str(b.get("cost", ""))[:20],
                        "by": uid, "votes": [uid]})
            elif route == "/api/vote":
                for p in d["places"]:
                    if p["id"] == b.get("place"):
                        p["votes"] = [v for v in p["votes"] if v != uid] if uid in p["votes"] else p["votes"] + [uid]
            elif route == "/api/chat":
                t = str(b.get("text", "")).strip()[:500]
                if t:
                    d["chat"].append({"user": uid, "text": t, "ts": int(time.time())})
                    d["chat"] = d["chat"][-300:]
            elif route == "/api/reset":  # nuovo sabato: azzera proposte
                d["places"] = []
            save(d)
            return self.send_json({"ok": True})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    print(f"MelasGo2 attivo su http://0.0.0.0:{port}")
    ThreadingHTTPServer(("0.0.0.0", port), H).serve_forever()
