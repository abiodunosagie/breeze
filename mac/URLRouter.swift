import Foundation

/// A breeze:// link waiting for the user to confirm it in the panel.
struct LinkRequest: Equatable {
    let changes: [String: AnyHashable]
    let summary: String
    let arrived: Date
}

/// Handles breeze:// links from Shortcuts, scripts, bookmarks and Couch scenes:
///   breeze://on                      switch on
///   breeze://off                     switch off
///   breeze://set?target=24&mode=cool switch on, to that temperature and mode (either may be left out)
///
/// Any web page can open a breeze:// link, so nothing reaches the air conditioner until the
/// user confirms it in the panel. Only power, a temperature and a mode are allowed.
@MainActor
enum URLRouter {
    /// A request older than this is dropped instead of applied, so a forgotten one never fires later.
    static let staleSeconds: TimeInterval = 60
    private static let modes = ["auto", "cool", "dry", "fan", "heat"]

    /// The request this link asks for, or the reason it cannot be followed.
    static func request(for url: URL, now: Date = Date()) -> Result<LinkRequest, LinkError> {
        guard url.scheme == "breeze" else { return .failure(.unknown) }
        let query = URLComponents(url: url, resolvingAgainstBaseURL: false)?.queryItems ?? []
        let value = { (name: String) in query.first { $0.name == name }?.value }
        switch url.host {
        case "on":
            return .success(LinkRequest(changes: ["power": true], summary: "Switch the air conditioner on", arrived: now))
        case "off":
            return .success(LinkRequest(changes: ["power": false], summary: "Switch the air conditioner off", arrived: now))
        case "set":
            var changes: [String: AnyHashable] = ["power": true]
            var parts: [String] = []
            if let text = value("target") {
                // Whole degrees in a sane range; the helper checks the unit's own range too.
                guard let degrees = Int(text), (10...35).contains(degrees) else { return .failure(.badTarget) }
                changes["target"] = Double(degrees)
                parts.append("\(degrees)°C")
            }
            if let mode = value("mode") {
                guard modes.contains(mode) else { return .failure(.badMode) }
                changes["mode"] = mode
                parts.append(ACNames.modes[mode]?.0 ?? mode)
            }
            guard !parts.isEmpty else { return .failure(.nothing) }
            return .success(LinkRequest(changes: changes, summary: "Switch on, " + parts.joined(separator: ", "), arrived: now))
        default:
            return .failure(.unknown)
        }
    }

    enum LinkError: Error {
        case unknown, badTarget, badMode, nothing

        var message: String {
            switch self {
            case .unknown: "Breeze did not understand that link."
            case .badTarget: "That breeze:// link has a temperature Breeze cannot set."
            case .badMode: "That breeze:// link has a mode Breeze does not know."
            case .nothing: "That breeze:// link asks for nothing."
            }
        }
    }
}
