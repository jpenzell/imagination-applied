// Guardian: the shield in the menu bar.
//
// This app is only a face. It reads one small file the helper (guardian.py watch) writes after
// every sample, ~/Library/Logs/guardian/state.json, and a click becomes a small request file in
// ~/.config/guardian/requests/ that the helper picks up within a second. It needs no special
// permission and does nothing to the Mac itself, except restart the helper when it has died.
//
// Build: ./build.sh (Apple's Command Line Tools; no Xcode project, no packages).
// Check without a menu bar:
//   Guardian --render DIR         status glyphs and the app icon as PNG files
//   Guardian --menu [state.json]  the menu, as text, for a given state
//   Guardian --icon FILE SIZE     the app icon at SIZE pixels

import AppKit

// MARK: - Paths

let fm = FileManager.default
let home = fm.homeDirectoryForCurrentUser
let stateURL = home.appendingPathComponent("Library/Logs/guardian/state.json")
let logsURL = home.appendingPathComponent("Library/Logs/guardian", isDirectory: true)
let requestsURL = home.appendingPathComponent(".config/guardian/requests", isDirectory: true)
let helperLabel = "local.guardian"

// MARK: - State (what the helper last said)

struct Action {
    let id: String
    let label: String
    let args: [String: Any]
    let busy: Bool
    let warning: String
}

struct Issue {
    let id: String
    let severity: String
    let title: String
    let detail: String
    let action: Action?
}

struct AppUse {
    let key: String
    let gb: Double
    let n: Int
}

struct GState {
    var ts: Double = 0
    var headline = ""
    var level = 1
    var freePct: Double?
    var memTotalMB: Double?
    var swapUsedMB: Double?
    var swapTotalMB: Double?
    var diskFreeGB: Double?
    var attention = "none"
    var paused = false
    var quiet = ""
    var mode = "nudge"
    var busy = ""
    var top: [AppUse] = []
    var issues: [Issue] = []
    var lastText = ""
    var lastTS: Double = 0
    var lastOK = true
    var refreshable: [String] = []
    var trim: [(app: String, n: Int, mb: Double)] = []
    var chromeRunning = false
    var notify = true
    var notifyLevel = "important"
    var refreshModes: [String: String] = [:]
    var archiveOffer = true
    var trimAuto = false
    var lagLevel = "none"
    var swapInMBs: Double?
    var decompressMBs: Double?

    var age: Double { Date().timeIntervalSince1970 - ts }
    var helperDown: Bool { age > 150 }
}

func num(_ v: Any?) -> Double? {
    if let n = v as? NSNumber { return n.doubleValue }
    if let s = v as? String { return Double(s) }
    return nil
}

func loadState(_ url: URL) -> GState? {
    guard let data = try? Data(contentsOf: url),
          let d = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any] else { return nil }
    var s = GState()
    s.ts = num(d["ts"]) ?? 0
    s.headline = d["headline"] as? String ?? ""
    s.level = Int(num(d["level"]) ?? 1)
    s.freePct = num(d["free_pct"])
    s.memTotalMB = num(d["mem_total_mb"])
    s.swapUsedMB = num(d["swap_used_mb"])
    s.swapTotalMB = num(d["swap_total_mb"])
    s.diskFreeGB = num(d["disk_free_gb"])
    s.attention = d["attention"] as? String ?? "none"
    s.paused = (d["paused"] as? Bool) ?? false
    s.quiet = d["quiet"] as? String ?? ""
    s.mode = d["mode"] as? String ?? "nudge"
    s.busy = d["busy"] as? String ?? ""
    for t in d["top"] as? [[String: Any]] ?? [] {
        s.top.append(AppUse(key: t["key"] as? String ?? "?", gb: num(t["gb"]) ?? 0, n: Int(num(t["n"]) ?? 1)))
    }
    for i in d["issues"] as? [[String: Any]] ?? [] {
        var action: Action?
        if let a = i["action"] as? [String: Any], let id = a["id"] as? String {
            action = Action(id: id, label: a["label"] as? String ?? id, args: a["args"] as? [String: Any] ?? [:],
                            busy: (a["busy"] as? Bool) ?? false, warning: a["warning"] as? String ?? "")
        }
        s.issues.append(Issue(id: i["id"] as? String ?? "", severity: i["severity"] as? String ?? "info",
                              title: i["title"] as? String ?? "", detail: i["detail"] as? String ?? "",
                              action: action))
    }
    if let l = d["last_action"] as? [String: Any] {
        s.lastText = l["text"] as? String ?? ""
        s.lastTS = num(l["ts"]) ?? 0
        s.lastOK = (l["ok"] as? Bool) ?? true
    }
    if let lag = d["lag"] as? [String: Any] {
        s.lagLevel = lag["level"] as? String ?? "none"
        s.swapInMBs = num(lag["swapin_mb_s"])
        s.decompressMBs = num(lag["decompress_mb_s"])
    }
    s.refreshable = d["refreshable"] as? [String] ?? []
    for t in d["trim"] as? [[String: Any]] ?? [] {
        s.trim.append((app: t["app"] as? String ?? "?", n: Int(num(t["n"]) ?? 0), mb: num(t["mb"]) ?? 0))
    }
    s.chromeRunning = (d["chrome_running"] as? Bool) ?? false
    if let st = d["settings"] as? [String: Any] {
        s.notify = (st["notify"] as? Bool) ?? true
        s.notifyLevel = st["notify_level"] as? String ?? "important"
        s.refreshModes = st["refresh"] as? [String: String] ?? [:]
        s.archiveOffer = (st["archive_offer"] as? Bool) ?? true
        s.trimAuto = (st["trim_auto"] as? Bool) ?? false
    }
    return s
}

// MARK: - Drawing

enum Glyph { case normal, critical, paused, down }

/// A shield in the given rectangle (y up).
func shieldPath(_ r: NSRect) -> NSBezierPath {
    let x = r.minX, y = r.minY, w = r.width, h = r.height
    func pt(_ fx: CGFloat, _ fy: CGFloat) -> NSPoint { NSPoint(x: x + w * fx, y: y + h * fy) }
    let p = NSBezierPath()
    p.move(to: pt(0.5, 1.0))
    p.curve(to: pt(1.0, 0.80), controlPoint1: pt(0.66, 0.90), controlPoint2: pt(0.84, 0.83))
    p.curve(to: pt(0.5, 0.0), controlPoint1: pt(1.0, 0.36), controlPoint2: pt(0.80, 0.12))
    p.curve(to: pt(0.0, 0.80), controlPoint1: pt(0.20, 0.12), controlPoint2: pt(0.0, 0.36))
    p.curve(to: pt(0.5, 1.0), controlPoint1: pt(0.16, 0.83), controlPoint2: pt(0.34, 0.90))
    p.close()
    return p
}

/// A heartbeat line across the given rectangle.
func pulsePath(_ r: NSRect) -> NSBezierPath {
    let x = r.minX, y = r.midY, w = r.width, h = r.height
    let p = NSBezierPath()
    p.move(to: NSPoint(x: x, y: y))
    p.line(to: NSPoint(x: x + w * 0.28, y: y))
    p.line(to: NSPoint(x: x + w * 0.42, y: y + h * 0.5))
    p.line(to: NSPoint(x: x + w * 0.60, y: y - h * 0.5))
    p.line(to: NSPoint(x: x + w * 0.72, y: y))
    p.line(to: NSPoint(x: x + w, y: y))
    p.lineJoinStyle = .round
    p.lineCapStyle = .round
    return p
}

/// The menu bar glyph, drawn in `color` inside `rect` (designed on an 18 pt square).
func drawGlyph(_ glyph: Glyph, in rect: NSRect, color: NSColor) {
    let u = rect.width / 18
    let r = NSRect(x: rect.minX + 2.6 * u, y: rect.minY + 1.3 * u, width: 12.8 * u, height: 15.4 * u)
    let shield = shieldPath(r)
    color.set()
    switch glyph {
    case .critical:
        shield.fill()
        if let ctx = NSGraphicsContext.current?.cgContext {     // an exclamation mark, cut out
            ctx.saveGState()
            ctx.setBlendMode(.clear)
            NSBezierPath(roundedRect: NSRect(x: rect.midX - 0.85 * u, y: rect.minY + 7.6 * u, width: 1.7 * u,
                                             height: 5.6 * u), xRadius: 0.85 * u, yRadius: 0.85 * u).fill()
            NSBezierPath(ovalIn: NSRect(x: rect.midX - 0.95 * u, y: rect.minY + 4.6 * u, width: 1.9 * u,
                                        height: 1.9 * u)).fill()
            ctx.restoreGState()
        }
    case .normal:
        shield.lineWidth = 1.35 * u
        shield.stroke()
        let pulse = pulsePath(NSRect(x: rect.minX + 5.0 * u, y: rect.minY + 7.2 * u, width: 8.0 * u, height: 4.6 * u))
        pulse.lineWidth = 1.15 * u
        pulse.stroke()
    case .paused:
        shield.lineWidth = 1.35 * u
        shield.stroke()
        for dx in [-1.9, 0.7] as [CGFloat] {
            NSBezierPath(roundedRect: NSRect(x: rect.midX + dx * u, y: rect.minY + 6.4 * u, width: 1.3 * u,
                                             height: 5.2 * u), xRadius: 0.4 * u, yRadius: 0.4 * u).fill()
        }
    case .down:
        shield.lineWidth = 1.2 * u
        shield.setLineDash([2.2 * u, 1.6 * u], count: 2, phase: 0)
        shield.stroke()
        let q = NSBezierPath()
        q.move(to: NSPoint(x: rect.midX - 2.2 * u, y: rect.minY + 6.6 * u))
        q.line(to: NSPoint(x: rect.midX + 2.2 * u, y: rect.minY + 11.0 * u))
        q.move(to: NSPoint(x: rect.midX + 2.2 * u, y: rect.minY + 6.6 * u))
        q.line(to: NSPoint(x: rect.midX - 2.2 * u, y: rect.minY + 11.0 * u))
        q.lineWidth = 1.2 * u
        q.lineCapStyle = .round
        q.stroke()
    }
}

func statusImage(_ glyph: Glyph) -> NSImage {
    let img = NSImage(size: NSSize(width: 18, height: 18), flipped: false) { rect in
        drawGlyph(glyph, in: rect, color: .black)
        return true
    }
    img.isTemplate = true          // the menu bar tints it for light and dark
    return img
}

func rgb(_ r: CGFloat, _ g: CGFloat, _ b: CGFloat, _ a: CGFloat = 1) -> NSColor {
    NSColor(srgbRed: r / 255, green: g / 255, blue: b / 255, alpha: a)
}

/// The app icon: a white shield with a heartbeat on a deep blue to teal tile.
func drawAppIcon(in rect: NSRect) {
    let px = rect.width
    let box = rect.insetBy(dx: px * 0.098, dy: px * 0.098)
    let tile = NSBezierPath(roundedRect: box, xRadius: box.width * 0.225, yRadius: box.width * 0.225)
    NSGraphicsContext.saveGraphicsState()
    let shadow = NSShadow()
    shadow.shadowColor = NSColor.black.withAlphaComponent(0.28)
    shadow.shadowBlurRadius = px * 0.030
    shadow.shadowOffset = NSSize(width: 0, height: -px * 0.012)
    shadow.set()
    rgb(18, 44, 84).setFill()
    tile.fill()
    NSGraphicsContext.restoreGraphicsState()
    NSGradient(colors: [rgb(15, 118, 132), rgb(21, 72, 122), rgb(18, 36, 78)])?.draw(in: tile, angle: 90)
    // a soft highlight across the top half
    NSGraphicsContext.saveGraphicsState()
    tile.addClip()
    NSGradient(colors: [NSColor.white.withAlphaComponent(0.16), NSColor.white.withAlphaComponent(0.0)])?
        .draw(in: NSRect(x: box.minX, y: box.midY, width: box.width, height: box.height / 2), angle: -90)
    NSGraphicsContext.restoreGraphicsState()

    let sr = NSRect(x: box.midX - box.width * 0.285, y: box.minY + box.height * 0.150,
                    width: box.width * 0.570, height: box.height * 0.705)
    let shield = shieldPath(sr)
    NSGraphicsContext.saveGraphicsState()
    let drop = NSShadow()
    drop.shadowColor = NSColor.black.withAlphaComponent(0.30)
    drop.shadowBlurRadius = px * 0.022
    drop.shadowOffset = NSSize(width: 0, height: -px * 0.010)
    drop.set()
    NSColor.white.setFill()
    shield.fill()
    NSGraphicsContext.restoreGraphicsState()
    NSGradient(colors: [rgb(226, 236, 244), NSColor.white])?.draw(in: shield, angle: 90)

    let pulse = pulsePath(NSRect(x: sr.minX + sr.width * 0.17, y: sr.minY + sr.height * 0.40,
                                 width: sr.width * 0.66, height: sr.height * 0.34))
    pulse.lineWidth = max(1, px * 0.036)
    rgb(14, 124, 134).setStroke()
    pulse.stroke()
}

func pngData(width: Int, height: Int, _ draw: (NSRect) -> Void) -> Data? {
    guard let rep = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: width, pixelsHigh: height,
                                     bitsPerSample: 8, samplesPerPixel: 4, hasAlpha: true, isPlanar: false,
                                     colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0),
          let ctx = NSGraphicsContext(bitmapImageRep: rep) else { return nil }
    rep.size = NSSize(width: width, height: height)
    NSGraphicsContext.saveGraphicsState()
    NSGraphicsContext.current = ctx
    draw(NSRect(x: 0, y: 0, width: width, height: height))
    ctx.flushGraphics()
    NSGraphicsContext.restoreGraphicsState()
    return rep.representation(using: .png, properties: [:])
}

// MARK: - Menu items

final class ClosureItem: NSMenuItem {
    private var handler: (() -> Void)?

    convenience init(_ title: String, checked: Bool = false, enabled: Bool = true, _ handler: (() -> Void)? = nil) {
        self.init(title: title, action: nil, keyEquivalent: "")
        self.handler = handler
        if handler != nil {
            target = self
            action = #selector(fire)
        }
        state = checked ? .on : .off
        isEnabled = enabled && handler != nil
    }

    @objc private func fire() { handler?() }
}

func symbol(_ name: String, _ color: NSColor) -> NSImage? {
    guard let img = NSImage(systemSymbolName: name, accessibilityDescription: nil) else { return nil }
    let cfg = NSImage.SymbolConfiguration(pointSize: 13, weight: .semibold)
        .applying(NSImage.SymbolConfiguration(paletteColors: [color]))
    return img.withSymbolConfiguration(cfg)
}

func gb(_ mb: Double?) -> String {
    guard let mb = mb else { return "?" }
    return String(format: "%.1f GB", mb / 1024)
}

func ago(_ ts: Double) -> String {
    let s = Int(Date().timeIntervalSince1970 - ts)
    if s < 90 { return "just now" }
    if s < 5400 { return "\(s / 60) min ago" }
    return "\(s / 3600) h ago"
}

/// A greyed-out line with a right-aligned value: "ChatGPT ........ 10.3 GB".
func infoItem(_ left: String, _ right: String = "") -> NSMenuItem {
    let item = NSMenuItem(title: left, action: nil, keyEquivalent: "")
    item.isEnabled = false
    let para = NSMutableParagraphStyle()
    para.tabStops = [NSTextTab(textAlignment: .right, location: 262)]
    let text = NSMutableAttributedString(
        string: right.isEmpty ? left : "\(left)\t\(right)",
        attributes: [.font: NSFont.menuFont(ofSize: 13), .foregroundColor: NSColor.secondaryLabelColor,
                     .paragraphStyle: para])
    if !right.isEmpty {
        text.addAttributes([.font: NSFont.monospacedDigitSystemFont(ofSize: 13, weight: .regular)],
                           range: NSRange(location: left.count + 1, length: right.count))
    }
    item.attributedTitle = text
    return item
}

func sectionTitle(_ title: String) -> NSMenuItem {
    if #available(macOS 14.0, *) { return NSMenuItem.sectionHeader(title: title) }
    let item = NSMenuItem(title: title.uppercased(), action: nil, keyEquivalent: "")
    item.isEnabled = false
    return item
}

func headerView(title: String, line: String, color: NSColor, glyph: Glyph) -> NSView {
    let view = NSView(frame: NSRect(x: 0, y: 0, width: 300, height: 52))
    let icon = NSImageView(frame: NSRect(x: 14, y: 10, width: 32, height: 32))
    icon.image = NSImage(size: NSSize(width: 32, height: 32), flipped: false) { rect in
        drawGlyph(glyph, in: rect, color: color)
        return true
    }
    view.addSubview(icon)
    let name = NSTextField(labelWithString: title)
    name.font = NSFont.systemFont(ofSize: 14, weight: .semibold)
    name.frame = NSRect(x: 54, y: 27, width: 236, height: 18)
    view.addSubview(name)
    let sub = NSTextField(labelWithString: line)
    sub.font = NSFont.systemFont(ofSize: 11.5)
    sub.textColor = .secondaryLabelColor
    sub.lineBreakMode = .byTruncatingTail
    sub.frame = NSRect(x: 54, y: 9, width: 236, height: 16)
    view.addSubview(sub)
    return view
}

// MARK: - The app

final class AppDelegate: NSObject, NSApplicationDelegate, NSMenuDelegate {
    private var item: NSStatusItem?
    private var state: GState?
    private var timer: Timer?
    private var shown = ""
    private var sentNote = ""
    private var sentAt: Double = 0

    func applicationDidFinishLaunching(_ note: Notification) {
        let status = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
        status.autosaveName = "local.guardian.menubar"
        let menu = NSMenu()
        menu.delegate = self
        menu.autoenablesItems = false
        status.menu = menu
        item = status
        reload()
        let t = Timer(timeInterval: 5, repeats: true) { [weak self] _ in self?.reload() }
        t.tolerance = 1.5
        RunLoop.main.add(t, forMode: .common)
        timer = t
    }

    /// `kill -USR1 <pid>`: write what is really in the menu bar to the log folder, so an
    /// install can be checked without anyone looking at the screen.
    func snapshot() {
        guard let button = item?.button else { return }
        var lines = ["time: \(Date())", "visible: \(item?.isVisible ?? false)"]
        if let w = button.window {
            lines.append("on screen: \(w.occlusionState.contains(.visible))")
            lines.append("frame: \(Int(w.frame.minX)),\(Int(w.frame.minY)) \(Int(w.frame.width))x\(Int(w.frame.height))")
            if let sc = w.screen { lines.append("screen: \(Int(sc.frame.width))x\(Int(sc.frame.height))") }
        }
        lines.append("tooltip: \(button.toolTip ?? "")")
        lines.append("dot: \(button.attributedTitle.string.isEmpty ? "none" : "shown")")
        try? lines.joined(separator: "\n").write(to: logsURL.appendingPathComponent("menubar-check.txt"),
                                                  atomically: true, encoding: .utf8)
    }

    // MARK: icon

    func look(_ s: GState?) -> (glyph: Glyph, dot: NSColor?, tip: String) {
        guard let s = s else { return (.down, nil, "Guardian: waiting for its helper") }
        if s.helperDown { return (.down, .systemOrange, "Guardian's helper is not running") }
        if s.paused { return (.paused, nil, "Guardian: \(s.headline)") }
        if s.attention == "crit" { return (.critical, .systemRed, "Guardian: \(s.headline)") }
        if s.attention == "warn" {
            return (.normal, .systemOrange, "Guardian: \(s.issues.first?.title ?? s.headline)")
        }
        return (.normal, nil, "Guardian: \(s.headline)")
    }

    func reload() {
        state = loadState(stateURL)
        let l = look(state)
        let signature = "\(l.glyph)|\(l.dot?.description ?? "")|\(l.tip)"
        guard signature != shown, let button = item?.button else { return }
        shown = signature
        button.image = statusImage(l.glyph)
        button.imagePosition = .imageLeading
        if let dot = l.dot {
            button.attributedTitle = NSAttributedString(
                string: "\u{25CF}", attributes: [.foregroundColor: dot, .font: NSFont.systemFont(ofSize: 7.5),
                                                .baselineOffset: 4.5])
        } else {
            button.attributedTitle = NSAttributedString(string: "")
        }
        button.toolTip = l.tip
    }

    // MARK: requests

    func send(_ action: String, _ args: [String: Any] = [:], note: String) {
        var body = args
        body["action"] = action
        body["ts"] = Date().timeIntervalSince1970
        guard let data = try? JSONSerialization.data(withJSONObject: body) else { return }
        try? fm.createDirectory(at: requestsURL, withIntermediateDirectories: true)
        let name = "\(Int(Date().timeIntervalSince1970 * 1000))-\(action).json"
        let tmp = requestsURL.appendingPathComponent("." + name + ".tmp")
        let final = requestsURL.appendingPathComponent(name)
        do {
            try data.write(to: tmp, options: .atomic)
            try fm.moveItem(at: tmp, to: final)       // the helper never sees half a file
            sentNote = note
            sentAt = Date().timeIntervalSince1970
        } catch {
            sentNote = "Could not send that to the helper."
            sentAt = Date().timeIntervalSince1970
        }
        for delay in [1.5, 4.0, 9.0] {
            DispatchQueue.main.asyncAfter(deadline: .now() + delay) { [weak self] in self?.reload() }
        }
    }

    func confirm(_ title: String, _ text: String, button: String) -> Bool {
        NSApp.activate(ignoringOtherApps: true)
        let alert = NSAlert()
        alert.messageText = title
        alert.informativeText = text
        alert.addButton(withTitle: button)
        alert.addButton(withTitle: "Cancel")
        return alert.runModal() == .alertFirstButtonReturn
    }

    func refreshApp(_ app: String) {
        let warning = state?.issues.compactMap { $0.action }
            .first { $0.id == "refresh" && ($0.args["app"] as? String) == app }?.warning ?? ""
        var text = "Guardian quits \(app) cleanly, clears its caches and reopens it. It takes about two minutes. "
            + "Chats and threads are kept; open windows may need reopening."
        if !warning.isEmpty { text += "\n\n" + warning }
        if confirm("Refresh \(app)?", text, button: "Refresh") {
            send("refresh", ["app": app, "force": true], note: "Refreshing \(app)...")
        }
    }

    func trimApp(_ app: String) {
        let t = state?.trim.first { $0.app == app }
        let what = t.map { "\($0.n) helper programs holding about \(gb($0.mb))" } ?? "its idle helper programs"
        let text = "Guardian closes \(what). They are programs \(app) started for its threads that have done nothing "
            + "for at least half an hour. \(app) stays open and what you are doing is not interrupted.\n\n"
            + "If you later go back to an older thread and one of its tools does not respond, refresh \(app)."
        if confirm("Trim idle \(app) helpers?", text, button: "Trim") {
            send("trim", ["app": app], note: "Trimming idle \(app) helpers...")
        }
    }

    func perform(_ a: Action) {
        switch a.id {
        case "refresh":
            if let app = a.args["app"] as? String { refreshApp(app) }
        case "trim":
            if let app = a.args["app"] as? String { trimApp(app) }
        case "threads": send("threads", note: "Opening the list of threads...")
        case "second_copy": send("second_copy", a.args, note: "Looking at where your archives live...")
        case "reclaim": send("reclaim", note: "Clearing caches...")
        case "archive": send("archive", note: "Measuring your work folders...")
        case "close_duplicate_tabs": send("close_duplicate_tabs", note: "Asking Chrome for its tabs...")
        case "doctor": send("doctor", note: "Running the check-up...")
        default: send(a.id, a.args, note: "Working...")
        }
    }

    func startHelper() {
        let p = Process()
        p.executableURL = URL(fileURLWithPath: "/bin/launchctl")
        p.arguments = ["kickstart", "-k", "gui/\(getuid())/\(helperLabel)"]
        try? p.run()
        sentNote = "Starting the helper..."
        sentAt = Date().timeIntervalSince1970
        for delay in [3.0, 8.0, 20.0] {
            DispatchQueue.main.asyncAfter(deadline: .now() + delay) { [weak self] in self?.reload() }
        }
    }

    // MARK: menu

    func menuNeedsUpdate(_ menu: NSMenu) {
        reload()
        build(menu, state)
    }

    func build(_ menu: NSMenu, _ state: GState?) {
        menu.removeAllItems()
        let l = look(state)
        let tint: NSColor = l.dot ?? .labelColor

        guard let s = state, !s.helperDown else {
            let head = NSMenuItem()
            head.view = headerView(title: "Guardian's helper is not running",
                                   line: state == nil ? "It has not written its status yet."
                                       : "Last heard from \(ago(state!.ts)).", color: .systemOrange, glyph: .down)
            menu.addItem(head)
            menu.addItem(.separator())
            menu.addItem(ClosureItem("Start it") { [weak self] in self?.startHelper() })
            if !sentNote.isEmpty, Date().timeIntervalSince1970 - sentAt < 60 { menu.addItem(infoItem(sentNote)) }
            menu.addItem(ClosureItem("Open the log folder") { NSWorkspace.shared.open(logsURL) })
            menu.addItem(.separator())
            menu.addItem(ClosureItem("Quit the menu bar icon") { NSApp.terminate(nil) })
            return
        }

        // ---- header
        var bits: [String] = []
        if s.lagLevel != "none", let rate = s.swapInMBs, rate >= 30 {
            bits.append("\(Int(rate)) MB/s to and from disk")
        } else if s.lagLevel != "none", let rate = s.decompressMBs {
            bits.append("\(Int(rate)) MB/s being squeezed")
        } else if let f = s.freePct {
            bits.append("\(Int(f))% memory free")
        }
        if let u = s.swapUsedMB { bits.append("\(gb(u)) swap") }
        if let d = s.diskFreeGB { bits.append(String(format: "%.0f GB disk free", d)) }
        let head = NSMenuItem()
        head.view = headerView(title: s.headline.isEmpty ? "Guardian" : s.headline,
                               line: bits.joined(separator: "  \u{00B7}  "), color: tint, glyph: l.glyph)
        menu.addItem(head)
        if !s.quiet.isEmpty { menu.addItem(infoItem("Staying quiet while \(s.quiet) is running")) }

        // ---- what just happened
        let now = Date().timeIntervalSince1970
        if !s.busy.isEmpty {
            menu.addItem(infoItem("Working: \(s.busy.replacingOccurrences(of: "menu:", with: ""))..."))
        }
        if !s.lastText.isEmpty, now - s.lastTS < 900, s.lastTS >= sentAt - 2 {
            let line = ClosureItem("\(s.lastOK ? "\u{2713}" : "\u{26A0}\u{FE0E}") \(s.lastText)")
            line.isEnabled = false
            line.toolTip = "\(s.lastText) (\(ago(s.lastTS)))"
            menu.addItem(line)
        } else if !sentNote.isEmpty, now - sentAt < 45 {
            menu.addItem(infoItem(sentNote))
        }

        // ---- needs attention
        if !s.issues.isEmpty {
            menu.addItem(.separator())
            menu.addItem(sectionTitle("Needs a look"))
            for issue in s.issues {
                let title = issue.action == nil ? issue.title : "\(issue.title)"
                let row: ClosureItem
                if let a = issue.action {
                    row = ClosureItem(title) { [weak self] in self?.perform(a) }
                } else {
                    row = ClosureItem(title)
                    row.isEnabled = false
                }
                switch issue.severity {
                case "crit": row.image = symbol("exclamationmark.octagon.fill", .systemRed)
                case "warn": row.image = symbol("exclamationmark.triangle.fill", .systemOrange)
                default: row.image = symbol("lightbulb.fill", .systemTeal)
                }
                let hint = issue.action.map { "\($0.label). " } ?? ""
                if #available(macOS 14.4, *) { row.subtitle = hint + issue.detail }
                row.toolTip = hint + issue.detail
                menu.addItem(row)
            }
        }

        // ---- memory
        menu.addItem(.separator())
        menu.addItem(sectionTitle("Using the most memory"))
        for t in s.top.prefix(5) {
            let names = ["agent:claude": "Claude Code", "agent:codex": "Codex (command line)"]
            menu.addItem(infoItem(names[t.key] ?? t.key.replacingOccurrences(of: "agent:", with: ""),
                                  String(format: "%.1f GB", t.gb)))
        }

        // ---- fix it now
        menu.addItem(.separator())
        menu.addItem(sectionTitle("Fix it now"))
        for t in s.trim where t.mb >= 100 {
            let app = t.app
            menu.addItem(ClosureItem("Trim idle \(app) helpers (\(gb(t.mb)))\u{2026}") { [weak self] in
                self?.trimApp(app)
            })
        }
        for app in s.refreshable {
            menu.addItem(ClosureItem("Refresh \(app)\u{2026}") { [weak self] in self?.refreshApp(app) })
        }
        if s.chromeRunning {
            menu.addItem(ClosureItem("Close duplicate Chrome tabs") { [weak self] in
                self?.send("close_duplicate_tabs", note: "Asking Chrome for its tabs...")
            })
        }
        menu.addItem(ClosureItem("Clear rebuildable caches") { [weak self] in
            self?.send("reclaim", note: "Clearing caches...")
        })
        menu.addItem(ClosureItem("Move old work folders to a drive\u{2026}") { [weak self] in
            self?.send("archive", note: "Measuring your work folders...")
        })

        // ---- pause
        menu.addItem(.separator())
        if s.paused {
            menu.addItem(ClosureItem("Resume Guardian") { [weak self] in self?.send("resume", note: "Resuming...") })
        } else {
            let pause = NSMenuItem(title: "Pause Guardian", action: nil, keyEquivalent: "")
            let sub = NSMenu()
            sub.autoenablesItems = false
            for (label, minutes) in [("For 30 minutes", 30), ("For 1 hour", 60), ("For 3 hours", 180),
                                     ("Until tomorrow", 1440)] {
                sub.addItem(ClosureItem(label) { [weak self] in
                    self?.send("pause", ["minutes": minutes], note: "Pausing...")
                })
            }
            pause.submenu = sub
            menu.addItem(pause)
        }

        // ---- settings
        let settings = NSMenuItem(title: "Settings", action: nil, keyEquivalent: "")
        let sm = NSMenu()
        sm.autoenablesItems = false
        func choice(_ title: String, _ on: Bool, _ key: String, _ value: Any, extra: [String: Any] = [:]) {
            sm.addItem(ClosureItem(title, checked: on) { [weak self] in
                var args: [String: Any] = ["key": key, "value": value]
                for (k, v) in extra { args[k] = v }
                self?.send("set", args, note: "Saving...")
            })
        }
        sm.addItem(sectionTitle("Guardian should"))
        choice("Fix safe things on its own (autopilot)", s.mode == "act", "mode", "act")
        choice("Only tell me", s.mode == "nudge", "mode", "nudge")
        choice("Just keep a diary", s.mode == "observe", "mode", "observe")
        sm.addItem(.separator())
        sm.addItem(sectionTitle("Notify me"))
        choice("Only when it is serious", s.notify && s.notifyLevel != "all", "notifications", "important")
        choice("Whenever memory is tight", s.notify && s.notifyLevel == "all", "notifications", "all")
        choice("Never", !s.notify, "notifications", "none")
        for (app, mode) in s.refreshModes.sorted(by: { $0.key < $1.key }) {
            sm.addItem(.separator())
            sm.addItem(sectionTitle("When \(app) grows"))
            choice("Ask me first", mode == "ask", "refresh", "ask", extra: ["app": app])
            choice("Refresh it when it is idle and I am away", mode == "auto", "refresh", "auto", extra: ["app": app])
            choice("Leave it alone", mode == "never", "refresh", "never", extra: ["app": app])
        }
        sm.addItem(.separator())
        sm.addItem(sectionTitle("When memory fills up fast"))
        choice("Trim idle helpers on its own", s.trimAuto, "trim_auto", true)
        choice("Only show the dot", !s.trimAuto, "trim_auto", false)
        sm.addItem(.separator())
        choice("Offer to move old work folders to a drive", s.archiveOffer, "archive_offer", !s.archiveOffer)
        settings.submenu = sm
        menu.addItem(settings)

        // ---- look
        menu.addItem(.separator())
        menu.addItem(ClosureItem("Agent threads and their size") { [weak self] in
            self?.send("threads", note: "Opening the list of threads...")
        })
        menu.addItem(ClosureItem("Today's report") { [weak self] in self?.send("report", note: "Opening the report...") })
        menu.addItem(ClosureItem("Run a check-up") { [weak self] in self?.send("doctor", note: "Running the check-up...") })
        menu.addItem(ClosureItem("Ask the AI what is slowing this Mac\u{2026}") { [weak self] in
            guard let me = self else { return }
            if me.confirm("Ask the AI for a diagnosis?",
                          "Guardian hands today's diary to Claude Code or Codex on this Mac and opens the answer. "
                              + "It takes a few minutes.", button: "Ask") {
                me.send("diagnose", note: "Asking the AI (a few minutes)...")
            }
        })
        menu.addItem(ClosureItem("Open the log folder") { NSWorkspace.shared.open(logsURL) })
        menu.addItem(.separator())
        menu.addItem(ClosureItem("Quit the menu bar icon") { NSApp.terminate(nil) })
    }
}

// MARK: - Command line checks (no menu bar needed)

func dump(_ menu: NSMenu, _ indent: String = "") {
    for item in menu.items {
        if item.isSeparatorItem { print("\(indent)--------"); continue }
        var line = item.title.isEmpty ? (item.attributedTitle?.string ?? "") : item.title
        if let v = item.view {
            line = "[" + v.subviews.compactMap { ($0 as? NSTextField)?.stringValue }.joined(separator: " | ") + "]"
        }
        line = line.replacingOccurrences(of: "\t", with: "  ....  ")
        var marks = item.state == .on ? "(x) " : ""
        if !item.isEnabled && item.view == nil { marks += "(info) " }
        print("\(indent)\(marks)\(line)")
        if #available(macOS 14.4, *), let sub = item.subtitle, !sub.isEmpty { print("\(indent)      \(sub)") }
        if let sub = item.submenu { dump(sub, indent + "    ") }
    }
}

let argv = CommandLine.arguments
if argv.count >= 4, argv[1] == "--icon", let px = Int(argv[3]) {
    guard let data = pngData(width: px, height: px, drawAppIcon) else { exit(1) }
    try data.write(to: URL(fileURLWithPath: argv[2]))
    exit(0)
}
if argv.count >= 3, argv[1] == "--render" {
    let out = URL(fileURLWithPath: argv[2], isDirectory: true)
    try fm.createDirectory(at: out, withIntermediateDirectories: true)
    try pngData(width: 512, height: 512, drawAppIcon)?.write(to: out.appendingPathComponent("app-icon.png"))
    // every menu bar state, on a light and on a dark bar, six times life size
    let cases: [(String, Glyph, NSColor?)] = [("all-good", .normal, nil), ("needs-a-look", .normal, .systemOrange),
                                              ("critical", .critical, .systemRed), ("paused", .paused, nil),
                                              ("helper-down", .down, .systemOrange)]
    let cell = 150, scale: CGFloat = 6
    let sheet = pngData(width: cell * cases.count, height: cell * 2) { _ in
        for (row, dark) in [false, true].enumerated() {
            for (col, c) in cases.enumerated() {
                let box = NSRect(x: col * cell, y: (1 - row) * cell, width: cell, height: cell)
                (dark ? rgb(38, 40, 46) : rgb(236, 236, 238)).setFill()
                box.fill()
                let g = NSRect(x: box.minX + 12, y: box.midY - 9 * scale, width: 18 * scale, height: 18 * scale)
                drawGlyph(c.1, in: g, color: dark ? .white : rgb(30, 30, 32))
                if let dot = c.2 {
                    dot.setFill()
                    NSBezierPath(ovalIn: NSRect(x: g.maxX + 2, y: g.midY + 6, width: 4.6 * scale / 1.6,
                                                height: 4.6 * scale / 1.6)).fill()
                }
            }
        }
    }
    try sheet?.write(to: out.appendingPathComponent("menu-bar-states.png"))
    print("wrote \(out.path)/app-icon.png and menu-bar-states.png")
    exit(0)
}
if argv.count >= 2, argv[1] == "--menu" {
    let url = argv.count >= 3 ? URL(fileURLWithPath: argv[2]) : stateURL
    let d = AppDelegate()
    let s = loadState(url)
    let l = d.look(s)
    print("icon: \(l.glyph)\(l.dot == nil ? "" : " + dot")   tooltip: \(l.tip)")
    let m = NSMenu()
    d.build(m, s)
    dump(m)
    exit(0)
}

let app = NSApplication.shared
let delegate = AppDelegate()
app.delegate = delegate
signal(SIGUSR1, SIG_IGN)
let checkSignal = DispatchSource.makeSignalSource(signal: SIGUSR1, queue: .main)
checkSignal.setEventHandler { delegate.snapshot() }
checkSignal.resume()
app.setActivationPolicy(.accessory)
app.run()
