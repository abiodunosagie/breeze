import Foundation
import UserNotifications

/// Mac notifications for things worth knowing while the panel is closed, like the power coming back.
@MainActor
final class Notifier: NSObject, UNUserNotificationCenterDelegate {
    nonisolated private static let powerBackCategory = "power_back"
    nonisolated private static let turnBackOn = "turn_back_on"
    /// What "Turn back on" does.
    var onTurnBackOn: (() -> Void)?

    override init() {
        super.init()
        let center = UNUserNotificationCenter.current()
        center.delegate = self
        let action = UNNotificationAction(identifier: Self.turnBackOn, title: "Turn Back On", options: [])
        center.setNotificationCategories([
            UNNotificationCategory(identifier: Self.powerBackCategory, actions: [action], intentIdentifiers: []),
        ])
    }

    /// Asks once; macOS remembers the answer.
    func askPermission() {
        UNUserNotificationCenter.current().requestAuthorization(options: [.alert, .sound]) { granted, error in
            // Only whether it worked, never what any notification said.
            NSLog("Breeze notifications allowed: %@, error: %@", granted ? "yes" : "no",
                  error.map { String(describing: type(of: $0)) + " " + String((($0 as NSError).code)) } ?? "none")
        }
    }

    func post(kind: String, text: String) {
        let content = UNMutableNotificationContent()
        content.title = "Breeze"
        content.body = text
        content.sound = .default
        if kind == "power_back" { content.categoryIdentifier = Self.powerBackCategory }
        let request = UNNotificationRequest(identifier: UUID().uuidString, content: content, trigger: nil)
        UNUserNotificationCenter.current().add(request)
    }

    nonisolated func userNotificationCenter(_ center: UNUserNotificationCenter, didReceive response: UNNotificationResponse,
                                            withCompletionHandler completionHandler: @escaping () -> Void) {
        let turnBackOn = response.actionIdentifier == Self.turnBackOn
        Task { @MainActor in
            if turnBackOn { self.onTurnBackOn?() }
            completionHandler()
        }
    }

    /// Show notifications even while Breeze is in front.
    nonisolated func userNotificationCenter(_ center: UNUserNotificationCenter, willPresent notification: UNNotification,
                                            withCompletionHandler completionHandler: @escaping (UNNotificationPresentationOptions) -> Void) {
        completionHandler([.banner, .sound])
    }
}
