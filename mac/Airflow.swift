import SwiftUI

/// How the air looks for each state of the AC: colours from the vent outwards, and how lively it is.
struct AirStyle: Hashable {
    let near: Color
    let far: Color
    let glow: Color
    /// Lines of air coming out of the vent.
    let lines: Int
    /// How fast the air travels.
    let speed: Double
    /// How far the air fans out sideways, 0...1.
    let spread: Double
    /// Side to side sway of the louvers, 0 when they hold still.
    let sway: Double
    /// Gentle waviness of each line.
    let wave: Double

    static func of(mode: String?, fan: String?, swing: String?, cleaning: Bool) -> AirStyle {
        let (near, far): (Color, Color)
        switch cleaning ? "clean" : mode ?? "cool" {
        case "heat": (near, far) = (Color(red: 1.0, green: 0.82, blue: 0.48), Color(red: 1.0, green: 0.42, blue: 0.28))
        case "dry": (near, far) = (Color(red: 0.62, green: 0.98, blue: 0.90), Color(red: 0.20, green: 0.72, blue: 0.78))
        case "fan": (near, far) = (Color(white: 0.98), Color(red: 0.70, green: 0.78, blue: 0.90))
        case "auto": (near, far) = (Color(red: 0.82, green: 0.76, blue: 1.0), Color(red: 0.52, green: 0.42, blue: 1.0))
        case "clean": (near, far) = (Color(red: 0.70, green: 1.0, blue: 0.78), Color(red: 0.25, green: 0.78, blue: 0.48))
        default: (near, far) = (Color(red: 0.62, green: 0.90, blue: 1.0), Color(red: 0.28, green: 0.52, blue: 1.0))
        }
        let level: Double = cleaning ? 0.35 : ["silent": 0.25, "low": 0.45, "medium": 0.65, "high": 0.85, "max": 1.0, "auto": 0.7][fan ?? ""] ?? 0.7
        let sideways = swing == "horizontal" || swing == "both"
        return AirStyle(near: near, far: far, glow: far,
                        lines: 7 + Int(level * 6),
                        speed: 0.35 + level * 0.9,
                        spread: sideways ? 0.95 : 0.75,
                        sway: sideways ? 0.18 : 0,
                        wave: swing == "vertical" || swing == "both" ? 1.0 : 0.55)
    }
}

/// The indoor unit with air flowing out of it while it runs.
struct ACUnit: View {
    let target: Double
    let ac: ACState

    private var flowing: Bool { ac.power || ac.cleaning }
    private var style: AirStyle { .of(mode: ac.mode, fan: ac.fan, swing: ac.swing, cleaning: ac.cleaning && !ac.power) }

    /// The air is wider than the panel, so it runs out at both walls, and tall enough to drift
    /// down behind the temperature before it fades away.
    static let airSize = CGSize(width: 400, height: 340)

    var body: some View {
        unit
            .frame(maxWidth: .infinity)
            .frame(maxHeight: .infinity, alignment: .top)
            .background(alignment: .top) {
                Airflow(style: style, running: flowing)
                    .id(style)  // a new mode fades in over the old one, colours and all
                    .transition(.opacity)
                    .frame(width: Self.airSize.width, height: Self.airSize.height)
                    // Soft at the top too, so the mist has no edge beside the unit.
                    .mask(LinearGradient(stops: [.init(color: .clear, location: 0), .init(color: .black, location: 0.07),
                                                 .init(color: .black, location: 0.55), .init(color: .clear, location: 1)],
                                         startPoint: .top, endPoint: .bottom))
                    .offset(y: 44)
                    .opacity(flowing ? 1 : 0)
                    .scaleEffect(x: 1, y: flowing ? 1 : 0.35, anchor: .top)
                    .animation(.easeInOut(duration: 0.9), value: flowing)
                    .animation(.easeInOut(duration: 0.7), value: style)
                    .allowsHitTesting(false)
            }
    }

    private var unit: some View {
        RoundedRectangle(cornerRadius: 13, style: .continuous)
            .fill(LinearGradient(colors: [.white, Color(white: 0.88)], startPoint: .top, endPoint: .bottom))
            .frame(width: 210, height: 62)
            .overlay(alignment: .bottom) {
                // The vent, lit by the air coming out of it.
                Capsule()
                    .fill(flowing ? style.far.opacity(0.85) : Color(white: 0.58))
                    .frame(width: 176, height: 5)
                    .shadow(color: flowing ? style.glow.opacity(0.9) : .clear, radius: 6)
                    .padding(.bottom, 9)
                    .animation(.easeInOut(duration: 0.6), value: flowing)
                    .animation(.easeInOut(duration: 0.6), value: style)
            }
            .overlay(alignment: .topTrailing) {
                HStack(spacing: 4) {
                    Text(ac.power ? "\(Int(target))" : "")
                        .font(.system(size: 13, weight: .semibold, design: .rounded))
                        .contentTransition(.numericText(value: target))
                    Circle().fill(flowing ? style.far : Color(white: 0.75)).frame(width: 5, height: 5)
                }
                .foregroundStyle(style.far)
                .padding(.top, 10).padding(.trailing, 16)
                .animation(.snappy, value: target)
            }
            .shadow(color: .black.opacity(0.35), radius: 12, y: 6)
    }
}

/// Air pouring out of the vent: soft streams that wave and fan out, bright pulses travelling
/// along them, and fine particles drifting down. Drawn every frame from the clock alone.
struct Airflow: View {
    let style: AirStyle
    /// False while the AC is off: the hidden air stops drawing, so it costs nothing.
    let running: Bool
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    var body: some View {
        // With Reduce Motion on, one still frame of the air instead of a moving one.
        TimelineView(.animation(minimumInterval: nil, paused: !running || reduceMotion)) { context in
            AirflowCanvas(style: style, time: context.date.timeIntervalSinceReferenceDate)
        }
    }
}

/// One frame of the air, from the time alone, so a still frame can be drawn for any moment
/// (Reduce Motion, and checking the look of each mode).
struct AirflowCanvas: View {
    let style: AirStyle
    let time: Double
    private static let steps = 32
    private static let particlesPerLine = 3

    var body: some View {
        Canvas { canvas, size in
            // The air breathes: a slow swell in strength, like a real draught.
            let breath = 0.85 + 0.15 * sin(time * 0.9)
            let mid = size.width / 2

            // Mist pouring from the vent, wide and soft.
            canvas.drawLayer { layer in
                layer.addFilter(.blur(radius: 24))
                var plume = Path()
                plume.move(to: CGPoint(x: mid - 95, y: 0))
                plume.addLine(to: CGPoint(x: mid + 95, y: 0))
                plume.addQuadCurve(to: CGPoint(x: size.width + 40, y: size.height * 0.85),
                                   control: CGPoint(x: mid + 150, y: size.height * 0.35))
                plume.addLine(to: CGPoint(x: -40, y: size.height * 0.85))
                plume.addQuadCurve(to: CGPoint(x: mid - 95, y: 0), control: CGPoint(x: mid - 150, y: size.height * 0.35))
                layer.fill(plume, with: .linearGradient(
                    Gradient(colors: [style.glow.opacity(0.30 * breath), style.glow.opacity(0.08), style.glow.opacity(0)]),
                    startPoint: CGPoint(x: mid, y: 0), endPoint: CGPoint(x: mid, y: size.height * 0.85)))
            }

            // Each shading and each path is made once per frame and reused below.
            let faint = fade(size, strength: 0.22 * breath), soft = fade(size, strength: 0.35 * breath)
            let medium = fade(size, strength: 0.45 * breath), bright = fade(size, strength: breath)

            // Far streams: fainter, thinner and slower, for depth.
            let farDash: [CGFloat] = [18, 122]
            for index in 0..<style.lines {
                let path = smooth(stream(index, in: size, depth: 0.55, offset: 0.5))
                canvas.stroke(path, with: faint, style: StrokeStyle(lineWidth: 0.8, lineCap: .round))
                let phase = -CGFloat((time * style.speed * 55 + Double(index) * 37).truncatingRemainder(dividingBy: Double(farDash.reduce(0, +))))
                canvas.stroke(path, with: medium, style: StrokeStyle(lineWidth: 1.2, lineCap: .round, dash: farDash, dashPhase: phase))
            }

            // Near streams, soft and wide under a blur, then fine with pulses of air.
            let near = (0..<style.lines).map { stream($0, in: size, depth: 1, offset: 0) }
            let nearPaths = near.map(smooth)
            canvas.drawLayer { layer in
                layer.addFilter(.blur(radius: 6))
                for path in nearPaths {
                    layer.stroke(path, with: medium, style: StrokeStyle(lineWidth: 8, lineCap: .round))
                }
            }
            let nearDash: [CGFloat] = [28, 92]
            for (index, path) in nearPaths.enumerated() {
                canvas.stroke(path, with: soft, style: StrokeStyle(lineWidth: 1, lineCap: .round))
                let phase = -CGFloat((time * style.speed * 90 + Double(index) * 23).truncatingRemainder(dividingBy: Double(nearDash.reduce(0, +))))
                canvas.stroke(path, with: bright, style: StrokeStyle(lineWidth: 2.2, lineCap: .round, dash: nearDash, dashPhase: phase))
            }

            // Particles riding the air: a soft glow under each, a bright core on top.
            let dots = near.enumerated().flatMap { index, points in
                (0..<Self.particlesPerLine).map { particle -> (CGPoint, Double, Double) in
                    let seed = Double(index * 7 + particle * 13)
                    let progress = (time * style.speed * 0.32 + seed * 0.137).truncatingRemainder(dividingBy: 1)
                    return (sample(points, at: progress), 0.8 + progress * 1.8, sin(progress * .pi) * 0.9)
                }
            }
            canvas.drawLayer { layer in
                layer.addFilter(.blur(radius: 3))
                for (point, radius, alpha) in dots {
                    let r = radius * 2.6
                    layer.fill(Path(ellipseIn: CGRect(x: point.x - r, y: point.y - r, width: r * 2, height: r * 2)),
                               with: .color(style.far.opacity(alpha * 0.6)))
                }
            }
            for (point, radius, alpha) in dots {
                canvas.fill(Path(ellipseIn: CGRect(x: point.x - radius, y: point.y - radius, width: radius * 2, height: radius * 2)),
                            with: .color(style.near.opacity(alpha)))
            }
        }
    }

    /// The points of one stream, from the vent outwards, bending with the louvers and waving.
    /// Outer streams fan past the edges of the panel, so the air reaches the walls.
    private func stream(_ index: Int, in size: CGSize, depth: Double, offset: Double) -> [CGPoint] {
        let mid = size.width / 2
        let count = Double(max(style.lines - 1, 1))
        let lane = min((Double(index) + offset) / count, 1) * 2 - 1  // -1...1
        let sway = sin(time * 0.55 + offset) * style.sway
        let reach = size.width * 0.62 * (0.85 + 0.15 * depth)
        return (0...Self.steps).map { step in
            let t = Double(step) / Double(Self.steps)
            let fan = (lane * style.spread + sway * t) * pow(t, 1.1) * reach
            let wave = sin(t * .pi * 2.2 - time * style.speed * 2.6 * depth + Double(index) * 0.9 + offset * 3) * 6 * style.wave * t
            return CGPoint(x: mid + lane * 84 + fan + wave, y: t * size.height * (0.9 + 0.1 * depth))
        }
    }

    private func smooth(_ points: [CGPoint]) -> Path {
        var path = Path()
        guard let first = points.first else { return path }
        path.move(to: first)
        for index in 1..<points.count {
            let previous = points[index - 1], point = points[index]
            path.addQuadCurve(to: CGPoint(x: (previous.x + point.x) / 2, y: (previous.y + point.y) / 2), control: previous)
        }
        path.addLine(to: points[points.count - 1])
        return path
    }

    private func sample(_ points: [CGPoint], at progress: Double) -> CGPoint {
        let position = progress * Double(points.count - 1)
        let index = min(Int(position), points.count - 2)
        let fraction = position - Double(index)
        let a = points[index], b = points[index + 1]
        return CGPoint(x: a.x + (b.x - a.x) * fraction, y: a.y + (b.y - a.y) * fraction)
    }

    /// Bright at the vent, gone by the bottom.
    private func fade(_ size: CGSize, strength: Double) -> GraphicsContext.Shading {
        .linearGradient(Gradient(stops: [
            .init(color: style.near.opacity(0.9 * strength), location: 0),
            .init(color: style.far.opacity(0.6 * strength), location: 0.5),
            .init(color: style.far.opacity(0), location: 1),
        ]), startPoint: CGPoint(x: size.width / 2, y: 0), endPoint: CGPoint(x: size.width / 2, y: size.height))
    }
}
