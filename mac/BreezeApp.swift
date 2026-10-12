import AppKit
import Combine
import SwiftUI

@main
@MainActor
final class AppDelegate: NSObject, NSApplicationDelegate, NSWindowDelegate {
    private let helper = Helper()
    private lazy var client = ACClient(token: helper.token)
    private var statusItem: NSStatusItem?
    private var panel: ACMenuPanel?
    private var window: NSWindow?
    private var acWatch: AnyCancellable?
    private let notifier = Notifier()

    static func main() {
        let app = NSApplication.shared
        let delegate = AppDelegate()
        app.delegate = delegate
        app.run()
    }

    /// Asks an already running Breeze to show its window; see `handOffToRunningCopy`.
    private static let showWindowNotification = Notification.Name("com.abiodun.breeze.showWindow")

    func applicationDidFinishLaunching(_ notification: Notification) {
        let background = CommandLine.arguments.contains(LoginItem.backgroundArgument)
        if handOffToRunningCopy(background: background) { return }

        // No Dock icon until the window opens, so login start is menu bar only.
        NSApp.setActivationPolicy(.accessory)
        buildMenu()
        buildStatusItem()
        client.onLinkLost = { [weak self] in _ = await self?.helper.ensureRunning() }
        notifier.askPermission()
        notifier.onTurnBackOn = { [weak self] in self?.client.restoreAC() }
        client.onEvent = { [weak self] kind, text in self?.notifier.post(kind: kind, text: text) }
        Task {
            if !(await helper.ensureRunning()) {
                client.show("Breeze could not reach its helper yet. Retrying.")
            }
            // Connect either way: a failed link restarts the helper and retries with backoff.
            client.connect()
        }
        DistributedNotificationCenter.default().addObserver(
            self, selector: #selector(showWindow), name: Self.showWindowNotification, object: nil)
        if CommandLine.arguments.contains("--show-panel") {
            DispatchQueue.main.asyncAfter(deadline: .now() + 1) { self.togglePanel() }
        } else if !background {
            showWindow()
        }
    }

    /// One Breeze at a time: two would fight over the helper port.
    private func handOffToRunningCopy(background: Bool) -> Bool {
        let me = NSRunningApplication.current
        let others = NSRunningApplication.runningApplications(withBundleIdentifier: LoginItem.label)
            .filter { $0.processIdentifier != me.processIdentifier }
        guard !others.isEmpty else { return false }
        if !background {
            DistributedNotificationCenter.default().postNotificationName(
                Self.showWindowNotification, object: nil, userInfo: nil, deliverImmediately: true)
        }
        NSApp.terminate(nil)
        return true
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { false }

    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool {
        if !flag { showWindow() }
        return true
    }

    func applicationWillTerminate(_ notification: Notification) {
        helper.stop()
    }

    // MARK: window

    @objc func showWindow() {
        if window == nil {
            let size = NSSize(width: RemoteWindowView.size.width + 100, height: RemoteWindowView.size.height + 110)
            let window = NSWindow(contentRect: NSRect(origin: .zero, size: size),
                                  styleMask: [.titled, .closable, .miniaturizable, .fullSizeContentView],
                                  backing: .buffered, defer: false)
            window.title = "Breeze"
            window.titlebarAppearsTransparent = true
            window.isReleasedWhenClosed = false
            window.contentView = NSHostingView(rootView: RemoteWindowView(client: client))
            window.setFrameAutosaveName("BreezeWindow")
            if !window.setFrameUsingName("BreezeWindow") { window.center() }
            window.delegate = self
            self.window = window
        }
        panel?.close()
        NSApp.setActivationPolicy(.regular)
        window?.makeKeyAndOrderFront(nil)
        NSApp.activate()
    }

    func windowWillClose(_ notification: Notification) {
        // Back to a menu bar only app once the window is gone.
        NSApp.setActivationPolicy(.accessory)
    }

    // MARK: menu bar

    private func buildStatusItem() {
        let item = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
        item.autosaveName = "BreezeStatusItem"
        item.button?.target = self
        item.button?.action = #selector(iconClicked)
        // Right click (and Control click) opens the icon's menu, like every menu bar app.
        item.button?.sendAction(on: [.leftMouseUp, .rightMouseUp])
        item.button?.imagePosition = .imageLeading
        statusItem = item
        panel = ACMenuPanel(client: client, openWindow: { [weak self] in self?.showWindow() })
        acWatch = client.$ac.receive(on: RunLoop.main).sink { [weak self] ac in
            MainActor.assumeIsolated { self?.updateStatusItem(ac) }
        }
        updateStatusItem(nil)
    }

    /// The AC icon, plus the set temperature while it runs, like "16°".
    private func updateStatusItem(_ ac: ACState?) {
        guard let button = statusItem?.button else { return }
        let running = ac?.isOnline == true && ac?.power == true
        button.image = NSImage(systemSymbolName: "air.conditioner.horizontal", accessibilityDescription: "Breeze")
        button.title = running ? ac?.target.map { " \(Int($0))°" } ?? "" : ""
        button.appearsDisabled = ac?.isOnline != true
        switch ac?.status {
        case .online?:
            button.toolTip = ac?.cleaning == true ? "Air conditioner self-cleaning" : running ? "Air conditioner on, set to \(ac?.target.map { "\(Int($0))°C" } ?? "--")" : "Air conditioner off"
        case .offline?:
            button.toolTip = "Air conditioner not reachable"
        case .unlinked?:
            button.toolTip = "Breeze: link your air conditioner"
        default:
            button.toolTip = "Breeze"
        }
    }

    @objc func togglePanel() {
        panel?.toggle(below: statusItem?.button)
    }

    @objc private func iconClicked() {
        let event = NSApp.currentEvent
        if event?.type == .rightMouseUp || event?.modifierFlags.contains(.control) == true {
            showIconMenu()
        } else {
            togglePanel()
        }
    }

    /// The icon's own menu: open the remote window, the panel, or quit.
    private func showIconMenu() {
        guard let button = statusItem?.button else { return }
        panel?.close()
        let menu = NSMenu()
        menu.addItem(withTitle: "Open Breeze Remote", action: #selector(showWindow), keyEquivalent: "").target = self
        menu.addItem(withTitle: "Show Panel", action: #selector(togglePanel), keyEquivalent: "").target = self
        menu.addItem(.separator())
        menu.addItem(withTitle: "Quit Breeze", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
        // The status button is flipped, so y past its height is just under the icon.
        menu.popUp(positioning: nil, at: NSPoint(x: 0, y: button.bounds.height + 4), in: button)
    }

    private func buildMenu() {
        let main = NSMenu()
        let appItem = NSMenuItem()
        let appMenu = NSMenu()
        appMenu.addItem(withTitle: "About Breeze", action: #selector(NSApplication.orderFrontStandardAboutPanel(_:)), keyEquivalent: "")
        appMenu.addItem(.separator())
        appMenu.addItem(withTitle: "Hide Breeze", action: #selector(NSApplication.hide(_:)), keyEquivalent: "h")
        appMenu.addItem(withTitle: "Quit Breeze", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
        appItem.submenu = appMenu
        main.addItem(appItem)

        let windowItem = NSMenuItem()
        let windowMenu = NSMenu(title: "Window")
        windowMenu.addItem(withTitle: "Remote", action: #selector(showWindow), keyEquivalent: "1").target = self
        windowMenu.addItem(withTitle: "Close", action: #selector(NSWindow.performClose(_:)), keyEquivalent: "w")
        windowMenu.addItem(withTitle: "Minimize", action: #selector(NSWindow.performMiniaturize(_:)), keyEquivalent: "m")
        windowItem.submenu = windowMenu
        main.addItem(windowItem)
        NSApp.mainMenu = main
        NSApp.windowsMenu = windowMenu
    }
}
