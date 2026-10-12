import AppKit
import Combine
import SwiftUI

/// The panel that drops from the menu bar icon.
///
/// A plain NSPopover anchors to the status item. On a MacBook with a notch, a full menu bar
/// hides the item behind the notch and the popover opens off screen. This panel always lands
/// fully on screen: under the icon when the icon is visible, otherwise at the top right.
@MainActor
final class ACMenuPanel: NSObject, NSWindowDelegate {
    private let panel: NSPanel
    private let host: NSHostingView<ACPanelView>
    private var lastClosed = Date.distantPast
    private weak var anchorButton: NSStatusBarButton?
    private var contentWatch: AnyCancellable?
    private static let gap: CGFloat = 6
    /// A click on the icon first takes focus from the panel, which closes it; a toggle this
    /// soon after a close is that same click.
    private static let reopenGuard: TimeInterval = 0.3

    init(client: ACClient) {
        host = NSHostingView(rootView: ACPanelView(client: client))
        panel = KeyablePanel(contentRect: .zero, styleMask: [.borderless, .nonactivatingPanel], backing: .buffered, defer: true)
        super.init()
        panel.isFloatingPanel = true
        panel.level = .popUpMenu
        panel.backgroundColor = .clear
        panel.isOpaque = false
        panel.hasShadow = true
        panel.hidesOnDeactivate = false
        panel.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary]
        panel.contentView = host
        panel.delegate = self
        // The panel grows when the AC comes online or a message shows; keep it fitted.
        contentWatch = client.objectWillChange.receive(on: RunLoop.main).sink { [weak self] _ in
            MainActor.assumeIsolated {
                guard let self, self.panel.isVisible else { return }
                DispatchQueue.main.async { self.place() }
            }
        }
    }

    var isShown: Bool { panel.isVisible }

    func toggle(below button: NSStatusBarButton?) {
        if isShown || Date().timeIntervalSince(lastClosed) < Self.reopenGuard {
            close()
        } else {
            anchorButton = button
            place()
            NSApp.activate()
            panel.makeKeyAndOrderFront(nil)
        }
    }

    private func place() {
        let anchor = Self.visibleAnchor(of: anchorButton)
        guard let screen = anchor?.screen ?? NSScreen.main ?? NSScreen.screens.first else { return }
        let area = screen.visibleFrame
        host.layoutSubtreeIfNeeded()
        let size = host.fittingSize
        let centerX = anchor?.frame.midX ?? area.maxX
        let x = min(max(centerX - size.width / 2, area.minX + Self.gap), area.maxX - size.width - Self.gap)
        let height = min(size.height, area.height - Self.gap * 2)
        let frame = NSRect(x: x, y: area.maxY - height - Self.gap, width: size.width, height: height)
        if frame != panel.frame { panel.setFrame(frame, display: true) }
    }

    func close() {
        guard panel.isVisible else { return }
        panel.orderOut(nil)
        lastClosed = Date()
    }

    /// Close like a menu when the user clicks elsewhere.
    func windowDidResignKey(_ notification: Notification) {
        close()
    }

    /// The status item's frame on screen, or nil when macOS has hidden it (notch overflow).
    private static func visibleAnchor(of button: NSStatusBarButton?) -> (frame: NSRect, screen: NSScreen)? {
        guard let button, let window = button.window, window.isVisible, let screen = window.screen else { return nil }
        let frame = window.convertToScreen(button.convert(button.bounds, to: nil))
        guard screen.visibleFrame.insetBy(dx: -1, dy: -40).contains(NSPoint(x: frame.midX, y: frame.midY)) else { return nil }
        return (frame, screen)
    }
}

/// Borderless panels refuse key status by default; the menus inside need it.
final class KeyablePanel: NSPanel {
    override var canBecomeKey: Bool { true }
}
