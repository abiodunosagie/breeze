import SwiftUI

/// The remote's screen: set temperature in LCD digits, fan bars, mode, and the small signs.
struct LCD: View {
    let ac: ACState?
    let lit: Bool
    let locked: Bool

    private var on: Bool { ac?.isOnline == true && ac?.power == true }
    /// Ten thin bars, like the remote's fan scale.
    private static let fanBars = ["silent": 2, "low": 4, "medium": 6, "high": 8, "max": 10, "auto": 10]

    var body: some View {
        VStack(alignment: .leading, spacing: 5) {
            HStack(spacing: 5) {
                Text(ac?.cleaning == true ? "CLEAN" : ac?.phase == "holding" ? "SET TEMP.  REST" : "SET TEMP.")
                    .font(.system(size: 9.5, weight: .heavy)).tracking(0.6)
                Spacer()
                if let fault = ac?.fault { Text("E\(fault)").font(.system(size: 9.5, weight: .black)) }
                if ac?.filterDue == true { Image(systemName: "aqi.medium").font(.system(size: 9)) }
                if locked { Image(systemName: "lock.fill").font(.system(size: 9)) }
                if ac?.sleep == true { Image(systemName: "moon.fill").font(.system(size: 9)) }
                if let minutes = ac?.offIn {
                    Text("\(Image(systemName: "clock")) \(ACNames.duration(minutes))").font(.system(size: 9, weight: .bold))
                }
                // Where the Midea remote shows its battery, this shows the link to the AC.
                Image(systemName: ac?.isOnline == true ? "wifi" : "wifi.slash").font(.system(size: 9.5, weight: .bold))
            }
            HStack(alignment: .top, spacing: 4) {
                Spacer()
                SegmentDigits(value: ac?.target.map { Int($0) }, ink: Hand.lcdInk.opacity(on ? 1 : 0.55))
                    .frame(width: 74, height: 54)
                Text("°C").font(.system(size: 13, weight: .heavy)).padding(.top, 2)
                Spacer()
            }
            .padding(.top, 2)
            HStack(spacing: 3) {
                Image(systemName: "fan").font(.system(size: 9.5))
                let bars = Self.fanBars[ac?.fan ?? ""] ?? 0
                ForEach(0..<10, id: \.self) { index in
                    Rectangle().fill(index < bars ? Hand.lcdInk : Hand.lcdInk.opacity(0.10))
                        .frame(width: 2, height: CGFloat(5 + index))
                        .frame(height: 15, alignment: .bottom)
                }
                if ac?.fan == "auto" {
                    Text("AUTO").font(.system(size: 8.5, weight: .heavy)).underline().padding(.leading, 2)
                }
                Spacer()
                if ac?.eco == true { Text("AI").font(.system(size: 9, weight: .black)) }
                if ac?.turbo == true { Image(systemName: "bolt.fill").font(.system(size: 8.5)) }
                if ac?.flash == true { Image(systemName: "snowflake").font(.system(size: 8.5)) }
                if let swing = ac?.swing, swing != "off" { Image(systemName: "wind").font(.system(size: 9)) }
            }
            .animation(.easeInOut(duration: 0.2), value: ac?.fan)
            Rectangle().fill(Hand.lcdInk.opacity(0.35)).frame(height: 1)
            HStack(alignment: .bottom, spacing: 5) {
                let mode = ACNames.modes[ac?.mode ?? ""]
                VStack(spacing: 1) {
                    Image(systemName: mode?.1 ?? "questionmark")
                        .font(.system(size: 10, weight: .bold))
                        .frame(width: 20, height: 17)
                        .overlay(RoundedRectangle(cornerRadius: 4).strokeBorder(Hand.lcdInk, lineWidth: 1.3))
                        .contentTransition(.symbolEffect(.replace))
                    Text((mode?.0 ?? "").uppercased().replacingOccurrences(of: " ONLY", with: ""))
                        .font(.system(size: 7.5, weight: .heavy))
                }
                Spacer()
            }
        }
        .foregroundStyle(Hand.lcdInk.opacity(on ? 1 : 0.55))
        .animation(.easeInOut(duration: 0.3), value: on)
        .padding(.horizontal, 13).padding(.vertical, 11)
        .frame(width: 192, height: 170)
        .background(RoundedRectangle(cornerRadius: 6, style: .continuous).fill(LinearGradient(
            colors: lit ? [Hand.lcdLit, Hand.lcdLit.opacity(0.85)] : [Hand.lcd, Hand.lcd.opacity(0.9)],
            startPoint: .top, endPoint: .bottom)))
        .overlay(RoundedRectangle(cornerRadius: 6, style: .continuous).strokeBorder(Color.black.opacity(0.12), lineWidth: 1).padding(1))
        .padding(4)
        .background(RoundedRectangle(cornerRadius: 9, style: .continuous).fill(LinearGradient(
            colors: [Hand.bezel, Hand.bezel.opacity(0.75)], startPoint: .top, endPoint: .bottom)))
        .shadow(color: lit ? Hand.lcdLit.opacity(0.7) : .clear, radius: 10)
    }
}

/// Two seven segment digits, with the unlit segments faintly visible like a real LCD.
private struct SegmentDigits: View {
    let value: Int?
    let ink: Color

    /// Lit segments per character: 0 top, 1 top right, 2 bottom right, 3 bottom, 4 bottom left, 5 top left, 6 middle.
    private static let segments: [Character: Set<Int>] = [
        "0": [0, 1, 2, 3, 4, 5], "1": [1, 2], "2": [0, 1, 6, 4, 3], "3": [0, 1, 6, 2, 3], "4": [5, 6, 1, 2],
        "5": [0, 5, 6, 2, 3], "6": [0, 5, 6, 4, 3, 2], "7": [0, 1, 2], "8": [0, 1, 2, 3, 4, 5, 6],
        "9": [0, 1, 2, 3, 5, 6], "-": [6],
    ]

    var body: some View {
        let text = value.map { String(format: "%2d", $0) } ?? "--"
        HStack(spacing: 6) {
            ForEach(Array(text.enumerated()), id: \.offset) { _, character in
                Canvas { canvas, size in
                    let lit = Self.segments[character] ?? []
                    for segment in 0..<7 {
                        canvas.fill(Self.shape(segment, in: size), with: .color(lit.contains(segment) ? ink : Hand.lcdInk.opacity(0.045)))
                    }
                }
            }
        }
    }

    /// One bar of a digit, pointed at both ends and slanted like LCD digits.
    private static func shape(_ segment: Int, in size: CGSize) -> Path {
        let w = size.width, h = size.height, t = w * 0.17, gap = t * 0.18, slant = w * 0.08
        func skew(_ point: CGPoint) -> CGPoint { CGPoint(x: point.x + slant * (1 - point.y / h), y: point.y) }
        func bar(from a: CGPoint, to b: CGPoint, horizontal: Bool) -> Path {
            let half = t / 2
            let points: [CGPoint] = horizontal
                ? [CGPoint(x: a.x + gap, y: a.y), CGPoint(x: a.x + gap + half, y: a.y - half), CGPoint(x: b.x - gap - half, y: b.y - half),
                   CGPoint(x: b.x - gap, y: b.y), CGPoint(x: b.x - gap - half, y: b.y + half), CGPoint(x: a.x + gap + half, y: a.y + half)]
                : [CGPoint(x: a.x, y: a.y + gap), CGPoint(x: a.x + half, y: a.y + gap + half), CGPoint(x: b.x + half, y: b.y - gap - half),
                   CGPoint(x: b.x, y: b.y - gap), CGPoint(x: b.x - half, y: b.y - gap - half), CGPoint(x: a.x - half, y: a.y + gap + half)]
            var path = Path()
            path.addLines(points.map(skew))
            path.closeSubpath()
            return path
        }
        let left = t / 2 + 1, right = w - slant - t / 2 - 1, top = t / 2, mid = h / 2, bottom = h - t / 2
        switch segment {
        case 0: return bar(from: CGPoint(x: left, y: top), to: CGPoint(x: right, y: top), horizontal: true)
        case 1: return bar(from: CGPoint(x: right, y: top), to: CGPoint(x: right, y: mid), horizontal: false)
        case 2: return bar(from: CGPoint(x: right, y: mid), to: CGPoint(x: right, y: bottom), horizontal: false)
        case 3: return bar(from: CGPoint(x: left, y: bottom), to: CGPoint(x: right, y: bottom), horizontal: true)
        case 4: return bar(from: CGPoint(x: left, y: mid), to: CGPoint(x: left, y: bottom), horizontal: false)
        case 5: return bar(from: CGPoint(x: left, y: top), to: CGPoint(x: left, y: mid), horizontal: false)
        default: return bar(from: CGPoint(x: left, y: mid), to: CGPoint(x: right, y: mid), horizontal: true)
        }
    }
}
