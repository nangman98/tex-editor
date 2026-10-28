#!/usr/bin/env python3
"""TeX 편집기 — 로컬 tex 파일을 편집하고, 저장되면 tectonic으로 자동 컴파일해 PDF를 옆에 보여 준다.

실행: python3 texview.py [폴더]   → 브라우저에서 http://127.0.0.1:8765
- 127.0.0.1에만 열린다. 선택한 폴더 밖의 파일은 읽거나 쓰지 않는다.
- 폴더 안의 .tex/.sty/.bib/.cls가 바뀌면(편집기에서 저장하든 다른 프로그램이 고치든) 보고 있는 본판을 다시 컴파일한다.
- PDF는 폴더에 `컴파일_PDF/`가 있으면 그곳에, 없으면 폴더 바로 아래에 본판 이름으로 만든다.
"""
import json
import os
import shutil
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

HOST = "127.0.0.1"
PORT = int(os.environ.get("TEXVIEW_PORT", 8765))
APP_DIR = Path(__file__).resolve().parent
CONFIG_PATH = Path(os.environ.get("TEXVIEW_CONFIG", APP_DIR / "config.json"))
INDEX_HTML = APP_DIR / "index.html"
TECTONIC = shutil.which("tectonic") or "/opt/homebrew/bin/tectonic"
SRC_EXT = {".tex", ".sty", ".bib", ".cls"}
SKIP_DIRS = {".git", "__pycache__", "node_modules"}

lock = threading.Lock()
state = {"root": None, "recent": [], "active": None, "builds": {}, "last_main": {}}


def load_config():
    try:
        cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        cfg = {}
    state["recent"] = [r for r in cfg.get("recent", []) if Path(r).is_dir()]
    state["last_main"] = cfg.get("last_main", {})
    root = cfg.get("root")
    if root and Path(root).is_dir():
        state["root"] = Path(root)
        state["active"] = state["last_main"].get(str(state["root"]))


def save_config():
    cfg = {"root": str(state["root"]) if state["root"] else None, "recent": state["recent"],
           "last_main": state["last_main"]}
    CONFIG_PATH.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")


def set_root(path):
    p = Path(path).expanduser().resolve()
    if not p.is_dir():
        raise ValueError(f"폴더가 아닙니다: {p}")
    with lock:
        state["root"] = p
        state["active"] = state["last_main"].get(str(p))
        state["builds"] = {}
        state["recent"] = [str(p)] + [r for r in state["recent"] if r != str(p)][:9]
    save_config()


def safe_path(rel):
    root = state["root"]
    if root is None:
        raise PermissionError("폴더가 정해지지 않았습니다")
    p = (root / rel).resolve()
    if p != root and root not in p.parents:
        raise PermissionError("폴더 밖의 경로입니다")
    return p


def list_sources():
    root = state["root"]
    out = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS and not d.startswith("."))
        for f in sorted(filenames):
            if Path(f).suffix in SRC_EXT and not f.startswith("."):
                out.append(str((Path(dirpath) / f).relative_to(root)))
    return out


def find_mains(files):
    mains = []
    for rel in files:
        if not rel.endswith(".tex"):
            continue
        try:
            head = (state["root"] / rel).read_text(encoding="utf-8", errors="ignore")[:6000]
        except OSError:
            continue
        if "\\documentclass" in head:
            mains.append(rel)
    return mains


def outdir():
    d = state["root"] / "컴파일_PDF"
    return d if d.is_dir() else state["root"]


def pdf_path(main):
    return outdir() / (Path(main).stem + ".pdf")


def src_mtime():
    m = 0.0
    for rel in list_sources():
        try:
            m = max(m, (state["root"] / rel).stat().st_mtime)
        except OSError:
            pass
    return m


def new_build():
    return {"state": "idle", "log": "", "errors": [], "started": 0.0, "finished": 0.0,
            "pdf_mtime": 0.0, "pending": False}


def compile_main(main):
    with lock:
        b = state["builds"].setdefault(main, new_build())
        if b["state"] == "running":
            b["pending"] = True
            return
        b["state"] = "running"
        b["started"] = time.time()
        b["pending"] = False
    threading.Thread(target=_run_compile, args=(main, state["root"]), daemon=True).start()


def _run_compile(main, root):
    od = outdir()
    try:
        r = subprocess.run([TECTONIC, "--outdir", str(od), main], cwd=root,
                           capture_output=True, text=True, timeout=600)
        log, ok = r.stdout + r.stderr, r.returncode == 0
    except (OSError, subprocess.SubprocessError) as e:
        log, ok = f"tectonic 실행 실패: {e}", False
    errors = [ln for ln in log.splitlines() if ln.startswith("error") or ln.startswith("!")][:30]
    pdf = pdf_path(main)
    with lock:
        if state["root"] != root:  # 컴파일 중에 폴더가 바뀜
            return
        b = state["builds"][main]
        b.update(state="ok" if ok else "error", log=log[-30000:], errors=errors,
                 finished=time.time(), pdf_mtime=pdf.stat().st_mtime if pdf.exists() else 0.0)
        again = b["pending"]
        b["pending"] = False
    if again:
        compile_main(main)


def watcher():
    last = None
    while True:
        time.sleep(1.0)
        if state["root"] is None or state["active"] is None:
            last = None
            continue
        try:
            m = src_mtime()
        except OSError:
            continue
        if last is not None and m > last:
            compile_main(state["active"])
        last = m


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def send_json(self, obj, code=200):
        data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def read_json(self):
        n = int(self.headers.get("Content-Length", 0))
        return json.loads(self.rfile.read(n).decode("utf-8")) if n else {}

    def do_GET(self):
        u = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        try:
            if u.path == "/":
                data = INDEX_HTML.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
            elif u.path == "/api/ping":
                self.send_json({"ok": True})
            elif u.path == "/api/state":
                if state["root"] is None:
                    self.send_json({"root": None, "recent": state["recent"], "files": [], "mains": []})
                    return
                files = list_sources()
                self.send_json({"root": str(state["root"]), "recent": state["recent"], "files": files,
                                "mains": find_mains(files), "active": state["active"],
                                "outdir": str(outdir().relative_to(state["root"]))})
            elif u.path == "/api/file":
                p = safe_path(q["path"])
                mtime = p.stat().st_mtime
                if q.get("meta"):
                    self.send_json({"mtime": mtime})
                else:
                    self.send_json({"text": p.read_text(encoding="utf-8"), "mtime": mtime})
            elif u.path == "/api/status":
                main = q.get("main")
                with lock:
                    b = dict(state["builds"].get(main, new_build()))
                b["log"] = b["log"][-6000:]
                b["src_mtime"] = src_mtime()
                self.send_json(b)
            elif u.path == "/pdf":
                p = pdf_path(q["main"])
                data = p.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "application/pdf")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
            else:
                self.send_json({"error": "없는 주소"}, 404)
        except PermissionError as e:
            self.send_json({"error": str(e)}, 403)
        except (OSError, KeyError, ValueError) as e:
            self.send_json({"error": f"{type(e).__name__}: {e}"}, 500)

    def do_POST(self):
        u = urlparse(self.path)
        try:
            body = self.read_json()
            if u.path == "/api/root":
                set_root(body["root"])
                self.send_json({"ok": True})
            elif u.path == "/api/file":
                p = safe_path(body["path"])
                text, base = body["text"], body.get("base_mtime")
                if p.exists() and base is not None and abs(p.stat().st_mtime - base) > 1e-3:
                    disk = p.read_text(encoding="utf-8")
                    if disk != text:
                        self.send_json({"conflict": True, "disk_text": disk,
                                        "mtime": p.stat().st_mtime}, 409)
                        return
                p.write_text(text, encoding="utf-8")
                self.send_json({"mtime": p.stat().st_mtime})
            elif u.path == "/api/activate":
                main = body["main"]
                safe_path(main)
                with lock:
                    state["active"] = main
                    state["last_main"][str(state["root"])] = main
                    b = state["builds"].setdefault(main, new_build())
                save_config()
                pdf = pdf_path(main)
                if b["state"] != "running":
                    if not pdf.exists() or pdf.stat().st_mtime < src_mtime():
                        compile_main(main)
                    else:
                        with lock:
                            b.update(state="ok", pdf_mtime=pdf.stat().st_mtime)
                self.send_json({"ok": True})
            elif u.path == "/api/clientlog":
                print(f"[화면] {time.strftime('%H:%M:%S')} {body.get('msg', '')}", flush=True)
                self.send_json({"ok": True})
            elif u.path == "/api/compile":
                compile_main(body["main"])
                self.send_json({"ok": True})
            else:
                self.send_json({"error": "없는 주소"}, 404)
        except PermissionError as e:
            self.send_json({"error": str(e)}, 403)
        except (OSError, KeyError, ValueError) as e:
            self.send_json({"error": f"{type(e).__name__}: {e}"}, 500)


def main():
    load_config()
    if len(sys.argv) > 1:
        set_root(sys.argv[1])
    threading.Thread(target=watcher, daemon=True).start()
    srv = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"TeX 편집기: http://{HOST}:{PORT}  (폴더: {state['root']})", flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
