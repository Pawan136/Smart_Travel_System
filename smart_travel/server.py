"""
Smart Travel Companion — Web Server - 

Run: python server.py
Open: http://localhost:5000

Works with OR without Flask installed.
"""
import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from backend.engine import TravelEngine

try:
    from flask import Flask, request, jsonify, send_from_directory
    HAS_FLASK = True
except ImportError:
    HAS_FLASK = False


def run_flask():
    app = Flask(__name__, static_folder="frontend", static_url_path="")

    @app.after_request
    def cors(response):
        response.headers["Access-Control-Allow-Origin"]  = "*"
        response.headers["Access-Control-Allow-Headers"] = "Content-Type"
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
        return response

    sessions = {}

    def get_engine(sid):
        if sid not in sessions:
            sessions[sid] = TravelEngine()
        return sessions[sid]

    @app.route("/")
    def index():
        return send_from_directory("frontend", "index.html")

    @app.route("/api/chat", methods=["POST", "OPTIONS"])
    def chat():
        if request.method == "OPTIONS":
            return "", 204
        data = request.get_json()
        sid  = data.get("session_id", "default")
        msg  = data.get("message", "").strip()
        if not msg:
            return jsonify({"responses": []})
        resp = get_engine(sid).process(msg)
        return jsonify({"responses": resp})

    @app.route("/api/memory")
    def memory():
        sid = request.args.get("session_id", "default")
        return jsonify(get_engine(sid).get_memory_snapshot())

    @app.route("/api/reset", methods=["POST", "OPTIONS"])
    def reset():
        if request.method == "OPTIONS":
            return "", 204
        sid = request.get_json().get("session_id", "default")
        sessions.pop(sid, None)
        return jsonify({"ok": True})

    print("\n" + "-"*50)
    print("  Smart Travel Companion")
    print("  Open: http://localhost:5000")
    print("-"*50 + "\n")
    app.run(debug=False, port=5000, host="0.0.0.0")


def run_stdlib():
    from http.server import HTTPServer, BaseHTTPRequestHandler
    import urllib.parse

    sessions = {}

    def get_engine(sid):
        if sid not in sessions:
            sessions[sid] = TravelEngine()
        return sessions[sid]

    BASE = os.path.dirname(os.path.abspath(__file__))

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args): pass

        def send_cors(self):
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")

        def do_OPTIONS(self):
            self.send_response(204); self.send_cors(); self.end_headers()

        def do_GET(self):
            path = self.path.split("?")[0]
            if path in ("/", "/index.html"):
                self._file(os.path.join(BASE, "frontend", "index.html"), "text/html; charset=utf-8")
            elif path == "/api/memory":
                qs  = urllib.parse.parse_qs(self.path.split("?",1)[-1]) if "?" in self.path else {}
                sid = qs.get("session_id", ["default"])[0]
                self._json(get_engine(sid).get_memory_snapshot())
            else:
                self.send_error(404)

        def do_POST(self):
            path   = self.path.split("?")[0]
            length = int(self.headers.get("Content-Length", 0))
            body   = json.loads(self.rfile.read(length)) if length else {}
            if path == "/api/chat":
                sid  = body.get("session_id", "default")
                msg  = body.get("message", "").strip()
                resp = get_engine(sid).process(msg) if msg else []
                self._json({"responses": resp})
            elif path == "/api/reset":
                sessions.pop(body.get("session_id", "default"), None)
                self._json({"ok": True})
            else:
                self.send_error(404)

        def _file(self, path, ct):
            try:
                data = open(path, "rb").read()
                self.send_response(200)
                self.send_header("Content-Type", ct)
                self.send_cors(); self.end_headers()
                self.wfile.write(data)
            except FileNotFoundError:
                self.send_error(404)

        def _json(self, obj):
            data = json.dumps(obj, default=str).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_cors(); self.end_headers()
            self.wfile.write(data)

    server = HTTPServer(("0.0.0.0", 5000), Handler)
    print("\n" + "-"*50)
    print("  Smart Travel Companion (no Flask needed)")
    print("  Open: http://localhost:5000")
    print("-"*50 + "\n")
    server.serve_forever()


if __name__ == "__main__":
    if HAS_FLASK:
        run_flask()
    else:
        run_stdlib()
