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

    var body: some View {
        ZStack(alignment: .top) {
            Airflow(style: style)
                .id(style)  // a new mode fades in over the old one, colours and all
                .transition(.opacity)
                .padding(.top, 50)
                .opacity(flowing ? 1 : 0)
                .scaleEffect(x: 1, y: flowing ? 1 : 0.4, anchor: .top)
                .animation(.easeInOut(duration: 0.9), value: flowing)
                .animation(.easeInOut(duration: 0.7), value: style)
            unit
        }
        .frame(maxWidth: .infinity)
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

    var body: some View {
        TimelineView(.animation) { context in
            AirflowCanvas(style: style, time: context.date.timeIntervalSinceReferenceDate)
        }
        .allowsHitTesting(false)
    }
}

/// One frame of the air. Separate from the clock so a still frame can be drawn for any moment.
struct AirflowCanvas: View {
    let style: AirStyle
    let time: Double
    private static let steps = 28
    private static let particlesPerLine = 3

    var body: some View {
        Canvas { canvas, size in
            let lines = (0..<style.lines).map { stream($0, in: size) }

            // Glow under the vent.
            // The gradient reaches nothing well inside the rectangle, so the glow has no edge.
            canvas.fill(Path(CGRect(x: 0, y: 0, width: size.width, height: 130)), with: .radialGradient(
                Gradient(colors: [style.glow.opacity(0.30), style.glow.opacity(0)]),
                center: CGPoint(x: size.width / 2, y: 0), startRadius: 0, endRadius: 120))

            // Soft, wide streams under a blur, for depth.
            canvas.drawLayer { layer in
                layer.addFilter(.blur(radius: 5))
                for points in lines {
                    layer.stroke(smooth(points), with: fade(size), style: StrokeStyle(lineWidth: 7, lineCap: .round))
                }
            }

            // Fine streams with pulses of air travelling down them.
            for (index, points) in lines.enumerated() {
                let path = smooth(points)
                canvas.stroke(path, with: fade(size, strength: 0.35), style: StrokeStyle(lineWidth: 1, lineCap: .round))
                let phase = -CGFloat((time * style.speed * 90 + Double(index) * 23).truncatingRemainder(dividingBy: 120))
                canvas.stroke(path, with: fade(size, strength: 1),
                              style: StrokeStyle(lineWidth: 2, lineCap: .round, dash: [26, 94], dashPhase: phase))
            }

            // Particles riding the air, fading as they travel.
            for (index, points) in lines.enumerated() {
                for particle in 0..<Self.particlesPerLine {
                    let seed = Double(index * 7 + particle * 13)
                    let progress = (time * style.speed * 0.32 + seed * 0.137).truncatingRemainder(dividingBy: 1)
                    let point = sample(points, at: progress)
                    let radius = 0.8 + progress * 1.6
                    let alpha = sin(progress * .pi) * 0.85
                    let dot = CGRect(x: point.x - radius, y: point.y - radius, width: radius * 2, height: radius * 2)
                    canvas.fill(Path(ellipseIn: dot), with: .color(style.near.opacity(alpha)))
                }
            }
        }
    }

    /// The points of one stream, from the vent outwards, bending with the louvers and waving.
    private func stream(_ index: Int, in size: CGSize) -> [CGPoint] {
        let mid = size.width / 2
        let lane = style.lines > 1 ? Double(index) / Double(style.lines - 1) * 2 - 1 : 0  // -1...1
        let sway = sin(time * 0.55) * style.sway
        return (0...Self.steps).map { step in
            let t = Double(step) / Double(Self.steps)
            let fan = (lane * style.spread + sway * t) * pow(t, 1.15) * size.width * 0.5
            let wave = sin(t * .pi * 2.2 - time * style.speed * 2.6 + Double(index) * 0.9) * 5 * style.wave * t
            return CGPoint(x: mid + lane * 80 + fan + wave, y: t * size.height)
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
    private func fade(_ size: CGSize, strength: Double = 0.5) -> GraphicsContext.Shading {
        .linearGradient(Gradient(stops: [
            .init(color: style.near.opacity(0.9 * strength), location: 0),
            .init(color: style.far.opacity(0.6 * strength), location: 0.55),
            .init(color: style.far.opacity(0), location: 1),
        ]), startPoint: CGPoint(x: size.width / 2, y: 0), endPoint: CGPoint(x: size.width / 2, y: size.height))
    }
}
