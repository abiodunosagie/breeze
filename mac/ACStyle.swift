import SwiftUI

/// Colours for the air conditioner panel: a night blue card.
enum ACTheme {
    static let top = Color(red: 0.13, green: 0.21, blue: 0.40)
    static let bottom = Color(red: 0.04, green: 0.07, blue: 0.16)
    static let accent = Color(red: 0.35, green: 0.58, blue: 1.0)
    static let eco = Color(red: 0.38, green: 0.80, blue: 0.48)
    static let text = Color.white
    static let dim = Color.white.opacity(0.55)
    static let faint = Color.white.opacity(0.25)
    static let tile = Color.white.opacity(0.06)
    static let tileEdge = Color.white.opacity(0.09)
    static let track = Color.black.opacity(0.35)
}

/// Names and symbols for the values the helper sends.
enum ACNames {
    static let modes: [String: (String, String)] = [
        "auto": ("Auto", "arrow.triangle.2.circlepath"), "cool": ("Cool", "snowflake"),
        "dry": ("Dry", "drop"), "heat": ("Heat", "sun.max"), "fan": ("Fan only", "fan"),
    ]
    static let fans = ["auto": "Auto", "silent": "Silent", "low": "Low", "medium": "Medium", "high": "High", "max": "Max"]
    static let louverPositions = [("1", "Top"), ("2", "High"), ("3", "Middle"), ("4", "Low"), ("5", "Bottom")]
    static let louverSides = [("1", "Far left"), ("2", "Left"), ("3", "Centre"), ("4", "Right"), ("5", "Far right")]
    static let swings = ["off": "Fixed", "vertical": "Up/down", "horizontal": "Sideways", "both": "Both"]

    static func duration(_ minutes: Int) -> String {
        minutes < 60 ? "\(minutes) min" : minutes % 60 == 0 ? "\(minutes / 60) h" : "\(minutes / 60) h \(minutes % 60) min"
    }
}
