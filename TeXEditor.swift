// TeX 편집기 네이티브 창 (2026-11-09). Chrome 없이 macOS 내장 WebKit 창으로 http://127.0.0.1:8765 을 연다.
// - 서버(texview.py)가 꺼져 있으면 켜고, 이 앱이 켠 서버는 앱을 끌 때 같이 끈다.
// - 창을 닫거나 ⌘Q로 끌 때 저장 안 된 편집이 있으면 먼저 저장한다.
// - "새 창"(PDF) 버튼은 실제 PDF 파일을 미리보기 앱으로 연다.
// 빌드는 make_app.sh가 한다. 저장소 경로와 python3 경로는 Info.plist의 TexviewDir · TexviewPython에서 읽는다.
import Cocoa
import WebKit

let info = Bundle.main.infoDictionary ?? [:]
let appDir = info["TexviewDir"] as? String ?? (NSHomeDirectory() + "/TeX편집기")
let python = info["TexviewPython"] as? String ?? "/usr/bin/python3"
let port = ProcessInfo.processInfo.environment["TEXVIEW_PORT"] ?? "8765"
let base = URL(string: "http://127.0.0.1:\(port)/")!

func fetch(_ path: String, timeout: TimeInterval = 0.5) -> Data? {
    var req = URLRequest(url: URL(string: path, relativeTo: base)!)
    req.timeoutInterval = timeout
    let sem = DispatchSemaphore(value: 0)
    var out: Data?
    URLSession.shared.dataTask(with: req) { data, resp, _ in
        if (resp as? HTTPURLResponse)?.statusCode == 200 { out = data }
        sem.signal()
    }.resume()
    _ = sem.wait(timeout: .now() + timeout + 0.5)
    return out
}

final class AppDelegate: NSObject, NSApplicationDelegate, NSWindowDelegate, WKUIDelegate {
    var window: NSWindow!
    var web: WKWebView!
    var server: Process?
    var closing = false

    func applicationDidFinishLaunching(_ note: Notification) {
        buildMenu()
        if fetch("api/ping") == nil { startServer() }
        let cfg = WKWebViewConfiguration()
        cfg.preferences.setValue(true, forKey: "developerExtrasEnabled")
        web = WKWebView(frame: .zero, configuration: cfg)
        web.uiDelegate = self
        window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 1500, height: 940),
                          styleMask: [.titled, .closable, .miniaturizable, .resizable],
                          backing: .buffered, defer: false)
        window.title = "TeX 편집기"
        window.contentView = web
        window.delegate = self
        window.center()
        window.setFrameAutosaveName("TeXEditorMain")
        window.makeKeyAndOrderFront(nil)
        web.load(URLRequest(url: base))
        NSApp.activate(ignoringOtherApps: true)
    }

    func startServer() {
        let p = Process()
        p.executableURL = URL(fileURLWithPath: python)
        p.arguments = [appDir + "/texview.py"]
        var env = ProcessInfo.processInfo.environment
        env["PATH"] = "/opt/homebrew/bin:/usr/local/bin:" + (env["PATH"] ?? "/usr/bin:/bin")
        p.environment = env
        let log = appDir + "/server.log"
        if !FileManager.default.fileExists(atPath: log) { FileManager.default.createFile(atPath: log, contents: nil) }
        if let h = FileHandle(forWritingAtPath: log) { h.seekToEndOfFile(); p.standardOutput = h; p.standardError = h }
        do { try p.run(); server = p } catch { NSLog("TeX 편집기 서버 시작 실패: \(error)") }
        for _ in 0..<50 where fetch("api/ping") == nil { Thread.sleep(forTimeInterval: 0.1) }
    }

    // 저장 안 된 편집을 저장한 뒤 done (최대 3초)
    func saveThen(_ done: @escaping () -> Void) {
        var called = false
        let finish = { if !called { called = true; done() } }
        web.callAsyncJavaScript("if (typeof dirty !== 'undefined' && dirty && typeof save === 'function') { await save(); } return true;",
                                arguments: [:], in: nil, in: .page) { _ in finish() }
        DispatchQueue.main.asyncAfter(deadline: .now() + 3, execute: finish)
    }

    func windowShouldClose(_ sender: NSWindow) -> Bool {
        if closing { return true }
        saveThen { self.closing = true; sender.close() }
        return false
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ app: NSApplication) -> Bool { true }

    func applicationShouldTerminate(_ app: NSApplication) -> NSApplication.TerminateReply {
        if closing || web == nil { return .terminateNow }
        saveThen { self.closing = true; NSApp.reply(toApplicationShouldTerminate: true) }
        return .terminateLater
    }

    func applicationWillTerminate(_ note: Notification) {
        if let p = server, p.isRunning { p.terminate() }
    }

    // 화면의 alert / confirm
    func webView(_ webView: WKWebView, runJavaScriptAlertPanelWithMessage message: String,
                 initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping () -> Void) {
        let a = NSAlert(); a.messageText = message; a.runModal(); completionHandler()
    }

    func webView(_ webView: WKWebView, runJavaScriptConfirmPanelWithMessage message: String,
                 initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping (Bool) -> Void) {
        let a = NSAlert(); a.messageText = message
        a.addButton(withTitle: "확인"); a.addButton(withTitle: "취소")
        completionHandler(a.runModal() == .alertFirstButtonReturn)
    }

    // "새 창" 버튼(window.open('/pdf?main=…')) → 그 PDF 파일을 미리보기 앱으로
    func webView(_ webView: WKWebView, createWebViewWith configuration: WKWebViewConfiguration,
                 for action: WKNavigationAction, windowFeatures: WKWindowFeatures) -> WKWebView? {
        guard let url = action.request.url else { return nil }
        let main = URLComponents(url: url, resolvingAgainstBaseURL: false)?.queryItems?.first { $0.name == "main" }?.value
        if let main = main, let data = fetch("api/state", timeout: 2),
           let st = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
           let root = st["root"] as? String, let out = st["outdir"] as? String {
            let stem = ((main as NSString).lastPathComponent as NSString).deletingPathExtension
            let pdf = URL(fileURLWithPath: root).appendingPathComponent(out).appendingPathComponent(stem + ".pdf").standardizedFileURL
            if FileManager.default.fileExists(atPath: pdf.path) { NSWorkspace.shared.open(pdf); return nil }
        }
        NSWorkspace.shared.open(url)
        return nil
    }

    @objc func reload(_ sender: Any?) { web.reload() }
    @objc func zoomIn(_ sender: Any?) { web.pageZoom = min(2.0, web.pageZoom + 0.1) }
    @objc func zoomOut(_ sender: Any?) { web.pageZoom = max(0.6, web.pageZoom - 0.1) }
    @objc func zoomReset(_ sender: Any?) { web.pageZoom = 1.0 }

    func buildMenu() {
        let bar = NSMenu()
        func sub(_ title: String, _ items: [NSMenuItem]) {
            let top = NSMenuItem(); let m = NSMenu(title: title)
            items.forEach { m.addItem($0) }
            top.submenu = m; bar.addItem(top)
        }
        func item(_ t: String, _ a: Selector?, _ k: String, _ mods: NSEvent.ModifierFlags = .command, target: AnyObject? = nil) -> NSMenuItem {
            let i = NSMenuItem(title: t, action: a, keyEquivalent: k)
            i.keyEquivalentModifierMask = mods; i.target = target
            return i
        }
        sub("TeX 편집기", [
            item("TeX 편집기 가리기", #selector(NSApplication.hide(_:)), "h"),
            .separator(),
            item("TeX 편집기 종료", #selector(NSApplication.terminate(_:)), "q"),
        ])
        sub("편집", [
            item("실행 취소", Selector(("undo:")), "z"),
            item("실행 복귀", Selector(("redo:")), "z", [.command, .shift]),
            .separator(),
            item("오려두기", #selector(NSText.cut(_:)), "x"),
            item("복사하기", #selector(NSText.copy(_:)), "c"),
            item("붙여넣기", #selector(NSText.paste(_:)), "v"),
            item("전체 선택", #selector(NSText.selectAll(_:)), "a"),
        ])
        sub("보기", [
            item("새로 고침", #selector(reload(_:)), "r", target: self),
            .separator(),
            item("확대", #selector(zoomIn(_:)), "=", target: self),
            item("축소", #selector(zoomOut(_:)), "-", target: self),
            item("실제 크기", #selector(zoomReset(_:)), "0", target: self),
        ])
        sub("윈도우", [
            item("최소화", #selector(NSWindow.performMiniaturize(_:)), "m"),
            item("닫기", #selector(NSWindow.performClose(_:)), "w"),
        ])
        NSApp.mainMenu = bar
    }
}

let app = NSApplication.shared
let delegate = AppDelegate()
app.delegate = delegate
app.setActivationPolicy(.regular)
app.run()
