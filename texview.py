#!/usr/bin/env python3
"""TeX 편집기 — 로컬 tex 파일을 편집하고, 저장되면 tectonic으로 자동 컴파일해 PDF를 옆에 보여 준다.

실행: python3 texview.py [폴더]   → 브라우저에서 http://127.0.0.1:8765
- 127.0.0.1에만 열린다. 선택한 폴더 밖의 파일은 읽거나 쓰지 않는다.
- 폴더 안의 .tex/.sty/.bib/.cls가 바뀌면(편집기에서 저장하든 다른 프로그램이 고치든) 보고 있는 본판을 다시 컴파일한다.
- PDF는 폴더에 `컴파일_PDF/`(또는 `NN_컴파일_PDF/`)가 있으면 그곳에, 없으면 폴더 바로 아래에 본판 이름으로 만든다.
"""
import hashlib
import json
import os
import re
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
QUICK_RERUNS = "1"   # 미리보기 컴파일: TeX 2회(차례·참조가 들어가는 최소). 정식 컴파일은 tectonic 기본(수렴할 때까지)
SETTLE_DELAY = 1.5   # 미리보기 뒤 입력이 이만큼(초) 멈추면 정식 컴파일
WATCH_INTERVAL = 0.3 # 다른 프로그램의 파일 수정을 확인하는 주기(초)
BUILD_DIR = APP_DIR / ".build"

lock = threading.Lock()
state = {"root": None, "recent": [], "active": None, "builds": {}, "last_main": {}, "seen": None}


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
        for b in state["builds"].values():
            b.close()
        state["root"] = p
        state["active"] = state["last_main"].get(str(p))
        state["builds"] = {}
        state["seen"] = None
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


def outdir(root=None):
    root = root or state["root"]
    for d in sorted(root.iterdir()):  # "컴파일_PDF" 또는 번호 붙은 "NN_컴파일_PDF"
        if d.is_dir() and re.fullmatch(r"(\d\d_)?컴파일_PDF", d.name):
            return d
    return root


def pdf_path(main, root=None):
    return outdir(root) / (Path(main).stem + ".pdf")


def src_mtime():
    m = 0.0
    for rel in list_sources():
        try:
            m = max(m, (state["root"] / rel).stat().st_mtime)
        except OSError:
            pass
    return m


def new_info():
    return {"state": "idle", "mode": "", "log": "", "errors": [], "started": 0.0,
            "finished": 0.0, "pdf_mtime": 0.0}


class Builder:
    """본판 하나의 컴파일 담당.

    저장되면 미리보기 컴파일(quick, TeX 2회)을 바로 돌리고, 입력이 SETTLE_DELAY초 멈추면 정식 컴파일(full)로
    한 번 더 맞춘다. 정식 컴파일 중에 새 저장이 오면 정식을 끊고 미리보기를 먼저 한다.
    결과는 BUILD_DIR에서 만든 뒤 내용이 바뀐 경우에만 PDF 자리로 통째로 바꿔 넣는다.
    """

    def __init__(self, root, main):
        self.root, self.main = root, main
        self.tmp = BUILD_DIR / hashlib.sha1(f"{root}|{main}".encode()).hexdigest()[:12]
        self.cv = threading.Condition()
        self.want = None
        self.full_due = None
        self.proc = None
        self.closed = False
        self.info = new_info()
        pdf = self.pdf()
        if pdf.exists():
            self.info.update(state="ok", pdf_mtime=pdf.stat().st_mtime)
        threading.Thread(target=self.loop, daemon=True).start()

    def pdf(self):
        return pdf_path(self.main, self.root)

    def request(self, mode):
        with self.cv:
            if mode == "quick":
                self.want, self.full_due = "quick", None
                if self.proc is not None and self.info["mode"] == "full":
                    self.proc.terminate()
            elif self.want is None:
                self.want = "full"
            self.cv.notify()

    def close(self):
        with self.cv:
            self.closed = True
            if self.proc is not None:
                self.proc.terminate()
            self.cv.notify()

    def loop(self):
        while True:
            with self.cv:
                while self.want is None and not self.closed:
                    if self.full_due is not None and time.time() >= self.full_due:
                        self.want, self.full_due = "full", None
                        break
                    self.cv.wait(None if self.full_due is None else max(0.05, self.full_due - time.time()))
                if self.closed:
                    return
                mode, self.want = self.want, None
            self.run(mode)

    def run(self, mode):
        self.tmp.mkdir(parents=True, exist_ok=True)
        args = [TECTONIC, "--outdir", str(self.tmp)]
        if mode == "quick":
            args += ["--reruns", QUICK_RERUNS]
        args.append(self.main)
        with self.cv:
            if self.closed:
                return
            try:
                proc = self.proc = subprocess.Popen(args, cwd=self.root, stdout=subprocess.PIPE,
                                                    stderr=subprocess.STDOUT, text=True)
            except OSError as e:
                self.info.update(state="error", mode=mode, log=f"tectonic 실행 실패: {e}",
                                 errors=[str(e)], finished=time.time())
                return
            self.info.update(state="running", mode=mode, started=time.time())
        try:
            log, _ = proc.communicate(timeout=600)
        except subprocess.TimeoutExpired:
            proc.kill()
            log, _ = proc.communicate()
        with self.cv:
            self.proc = None
        if proc.returncode < 0 and not self.closed:  # 새 저장 때문에 끊음: 다음 요청이 이어 받는다
            return
        ok = proc.returncode == 0
        built = self.tmp / (Path(self.main).stem + ".pdf")
        dst = self.pdf()
        if ok and built.exists() and (not dst.exists() or dst.read_bytes() != built.read_bytes()):
            part = dst.with_name("." + dst.name + ".part")
            shutil.copyfile(built, part)
            os.replace(part, dst)
        errors = [ln for ln in log.splitlines() if ln.startswith("error") or ln.startswith("!")][:30]
        with self.cv:
            self.info.update(state="ok" if ok else "error", mode=mode, log=log[-30000:], errors=errors,
                             finished=time.time(), pdf_mtime=dst.stat().st_mtime if dst.exists() else 0.0)
            if ok and mode == "quick" and self.want is None:
                self.full_due = time.time() + SETTLE_DELAY


def builder(main):
    with lock:
        b = state["builds"].get(main)
        if b is None:
            b = state["builds"][main] = Builder(state["root"], main)
        return b


def note_seen(m):
    with lock:
        if state["seen"] is None or m > state["seen"]:
            state["seen"] = m


def watcher():
    while True:
        time.sleep(WATCH_INTERVAL)
        if state["root"] is None or state["active"] is None:
            continue
        try:
            m = src_mtime()
        except OSError:
            continue
        with lock:
            seen = state["seen"]
        note_seen(m)
        if seen is not None and m > seen:
            builder(state["active"]).request("quick")


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
                with lock:
                    b = state["builds"].get(q.get("main"))
                info = dict(b.info) if b else new_info()
                info["log"] = info["log"][-6000:]
                self.send_json(info)
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
                mtime = p.stat().st_mtime
                note_seen(mtime)
                if state["active"]:
                    builder(state["active"]).request("quick")
                self.send_json({"mtime": mtime})
            elif u.path == "/api/activate":
                main = body["main"]
                safe_path(main)
                with lock:
                    state["active"] = main
                    state["last_main"][str(state["root"])] = main
                save_config()
                b = builder(main)
                pdf = b.pdf()
                if not pdf.exists() or pdf.stat().st_mtime < src_mtime():
                    b.request("full")
                self.send_json({"ok": True})
            elif u.path == "/api/clientlog":
                print(f"[화면] {time.strftime('%H:%M:%S')} {body.get('msg', '')}", flush=True)
                self.send_json({"ok": True})
            elif u.path == "/api/compile":
                builder(body["main"]).request("full")
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
