import SwiftUI

/// Colours for the window remote, modelled on the Midea hand remote.
enum Hand {
    static let shellTop = Color(white: 0.995)
    static let shellBottom = Color(white: 0.955)
    static let shellEdge = Color(white: 0.84)
    static let keyTop = Color.white
    static let keyBottom = Color(white: 0.93)
    static let keyEdge = Color(white: 0.78)
    static let keyDown = Color(white: 0.86)
    static let ink = Color(white: 0.25)
    static let soft = Color(white: 0.55)
    static let power = Color(red: 0.97, green: 0.52, blue: 0.31)
    static let powerDown = Color(red: 0.88, green: 0.42, blue: 0.22)
    static let ai = Color(red: 0.10, green: 0.62, blue: 0.30)
    static let lcd = Color(red: 0.79, green: 0.87, blue: 0.88)
    static let lcdLit = Color(red: 0.70, green: 0.90, blue: 0.95)
    static let lcdInk = Color(red: 0.12, green: 0.19, blue: 0.23)
    static let bezel = Color(white: 0.52)
    static let backdrop = LinearGradient(colors: [Color(red: 0.91, green: 0.94, blue: 0.97), Color(red: 0.80, green: 0.85, blue: 0.91)],
                                         startPoint: .top, endPoint: .bottom)
}
