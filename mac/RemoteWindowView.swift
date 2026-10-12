import AppKit
import SwiftUI

/// Colours for the window remote, modelled on the Midea hand remote.
private enum Hand {
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

/// The Breeze window: the air conditioner's own remote.
struct RemoteWindowView: View {
    @ObservedObject var client: ACClient
    @State private var loginItem = LoginItem.isEnabled

    static let size = CGSize(width: 244, height: 700)

    var body: some View {
        VStack(spacing: 16) {
            HandRemote(client: client)
            Text(client.toast ?? status)
                .font(.system(size: 12))
                .foregroundStyle(.secondary)
                .multilineTextAlignment(.center)
                .frame(height: 30)
                .animation(.easeInOut(duration: 0.2), value: client.toast)
            Toggle("Open at login", isOn: $loginItem)
                .toggleStyle(.checkbox)
                .font(.system(size: 12))
                .onChange(of: loginItem) {
                    do { try LoginItem.set(enabled: loginItem) } catch { loginItem = LoginItem.isEnabled }
                }
        }
        .padding(.top, 34)
        .padding(.bottom, 18)
        .padding(.horizontal, 50)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(Hand.backdrop)
        .environment(\.colorScheme, .light)
        .onAppear { client.refreshAC() }
    }

    private var status: String {
        switch client.ac?.status {
        case .online?: client.ac?.cleaning == true ? "Self-cleaning. Press power to stop it." : client.ac?.power == true ? "Running" : "Off"
        case .offline?: "Can't reach the air conditioner. Is it on your Wi-Fi?"
        case .unlinked?: "Link your air conditioner first: open the menu bar panel for the steps."
        default: "Looking for the air conditioner…"
        }
    }
}

/// The hand remote. Every key does what the same key on the Midea remote does.
private struct HandRemote: View {
    @ObservedObject var client: ACClient
    /// The screen lights up for a moment after each press, like the real remote's backlight.
    @State private var lit = false
    @State private var unlit: Task<Void, Never>?
    /// Child lock: the keys do nothing until it is undone.
    @State private var locked = false

    private var ac: ACState? { client.ac }
    private var ready: Bool { ac?.isOnline == true }

    var body: some View {
        VStack(spacing: 0) {
            LCD(ac: ac, lit: lit, locked: locked)
                .padding(.top, 34)
            HStack(spacing: 24) {
                Key(kind: .power, help: "On and off") {
                    Image(systemName: "power").font(.system(size: 16, weight: .bold)).foregroundStyle(.white)
                } action: { press { if let ac { client.setAC(["power": !ac.power]) } } }
                Key(help: "Mode: auto, cool, dry, fan") {
                    Text("Mode").font(.system(size: 10.5, weight: .semibold)).foregroundStyle(Hand.ink)
                } action: { press { cycle("mode", from: ac?.mode, in: ac?.modes) } }
                Key(help: "AI saving (Eco)") {
                    AIGlyph()
                } action: { press { if let ac, ac.hasEco { client.setAC(["eco": !ac.eco]) } } }
            }
            .padding(.top, 26)
            Ring(client: client, press: press)
                .padding(.top, 22)
            HStack(spacing: 24) {
                Key(help: "Fan speed") {
                    Image(systemName: "fan").font(.system(size: 16)).foregroundStyle(Hand.ink)
                } action: { press { cycle("fan", from: ac?.fan, in: ac?.fans) } }
                Key(help: "Swing: the louvers move") {
                    Text("Swing").font(.system(size: 10.5, weight: .semibold)).foregroundStyle(Hand.ink)
                } action: { press { cycle("swing", from: ac?.swing, in: ac?.swings) } }
                Key(help: "Sleep") {
                    Image(systemName: "moon.zzz").font(.system(size: 16)).foregroundStyle(Hand.ink)
                } action: { press { if let ac { client.setAC(["sleep": !ac.sleep]) } } }
            }
            .padding(.top, 22)
            BarKeys(flash: ac?.hasFlash == true, led: ac?.hasDisplay == true, locked: locked,
                    onFlash: { press { if let ac { client.setAC(["flash": !ac.flash]) } } },
                    onLED: { press { client.toggleACDisplay() } },
                    onFresh: { press { client.show("Fresh air needs a fresh air unit, and this air conditioner has none.") } },
                    onLock: { lightUp(); locked.toggle() })
                .padding(.top, 20)
            Spacer(minLength: 0)
            Text("Breeze")
                .font(.system(size: 17, weight: .semibold, design: .rounded))
                .tracking(0.6)
                .foregroundStyle(Hand.soft.opacity(0.8))
                .padding(.bottom, 40)
        }
        .disabled(!ready)
        .frame(width: RemoteWindowView.size.width, height: RemoteWindowView.size.height)
        .background(RoundedRectangle(cornerRadius: 30, style: .continuous)
            .fill(LinearGradient(colors: [Hand.shellTop, Hand.shellBottom], startPoint: .top, endPoint: .bottom)))
        // The raised front plate the keys sit on.
        .background(RoundedRectangle(cornerRadius: 24, style: .continuous)
            .strokeBorder(Color.black.opacity(0.05), lineWidth: 1).padding(7))
        .overlay(RoundedRectangle(cornerRadius: 30, style: .continuous).strokeBorder(Hand.shellEdge))
        .overlay(RoundedRectangle(cornerRadius: 29, style: .continuous).strokeBorder(.white, lineWidth: 1.5).padding(1.5))
        .shadow(color: .black.opacity(0.16), radius: 28, y: 16)
    }

    /// Every key: light the screen, then act, unless the child lock is on.
    private func press(_ action: () -> Void) {
        lightUp()
        guard !locked else {
            client.show("The keys are locked. Press the lock under LED and Fresh to unlock.")
            return
        }
        action()
    }

    private func lightUp() {
        NSHapticFeedbackManager.defaultPerformer.perform(.generic, performanceTime: .now)
        withAnimation(.easeOut(duration: 0.12)) { lit = true }
        unlit?.cancel()
        unlit = Task {
            try? await Task.sleep(nanoseconds: 2_500_000_000)
            if !Task.isCancelled { withAnimation(.easeIn(duration: 0.6)) { lit = false } }
        }
    }

    /// The next value after the current one, round and round, like pressing the key again.
    private func cycle(_ name: String, from current: String?, in options: [String]?) {
        guard let options, !options.isEmpty else { return }
        let index = current.flatMap(options.firstIndex(of:)) ?? -1
        client.setAC([name: options[(index + 1) % options.count]])
    }
}

private enum KeyKind { case plain, power }

/// A round key that sinks in when pressed.
private struct Key<Label: View>: View {
    var kind = KeyKind.plain
    let help: String
    @ViewBuilder let label: () -> Label
    let action: () -> Void

    var body: some View {
        Button(action: action) { label() }
            .buttonStyle(KeyStyle(kind: kind))
            .help(help)
    }
}

private struct KeyStyle: ButtonStyle {
    let kind: KeyKind
    @Environment(\.isEnabled) private var enabled

    func makeBody(configuration: Configuration) -> some View {
        let down = configuration.isPressed
        let power = kind == .power
        let fill: AnyShapeStyle = power
            ? AnyShapeStyle(down ? Hand.powerDown : Hand.power)
            : AnyShapeStyle(LinearGradient(colors: down ? [Hand.keyDown, Hand.keyDown] : [Hand.keyTop, Hand.keyBottom],
                                           startPoint: .top, endPoint: .bottom))
        return configuration.label
            .frame(width: 44, height: 44)
            .background(Circle().fill(fill))
            .overlay(Circle().strokeBorder(power ? Color.black.opacity(0.08) : Hand.keyEdge, lineWidth: 1))
            .shadow(color: .black.opacity(down ? 0.04 : 0.14), radius: down ? 1 : 3, y: down ? 0 : 2)
            .scaleEffect(down ? 0.93 : 1)
            .opacity(enabled ? 1 : 0.55)
            .animation(.spring(response: 0.18, dampingFraction: 0.7), value: down)
    }
}

/// The green "AI" printed on the Midea key.
private struct AIGlyph: View {
    var body: some View {
        HStack(spacing: 1) {
            Text("A").font(.system(size: 15, weight: .black, design: .rounded))
            Rectangle().frame(width: 2.6, height: 11).offset(y: 0.5)
        }
        .foregroundStyle(Hand.ai)
    }
}

/// Up and down for the temperature, SET for mode, fan and Turbo, the clock for the timer, OK to read the AC again.
private struct Ring: View {
    @ObservedObject var client: ACClient
    let press: (() -> Void) -> Void
    private static let size: CGFloat = 168

    private var ac: ACState? { client.ac }

    var body: some View {
        ZStack {
            Circle()
                .fill(LinearGradient(colors: [Hand.keyTop, Hand.keyBottom], startPoint: .top, endPoint: .bottom))
                .overlay(Circle().strokeBorder(Hand.keyEdge))
                .shadow(color: .black.opacity(0.12), radius: 4, y: 2)
            VStack {
                RingButton(help: "Warmer") {
                    Image(systemName: "chevron.up").font(.system(size: 17, weight: .medium))
                } action: { press { step(1) } }
                Spacer()
                RingButton(help: "Cooler") {
                    Image(systemName: "chevron.down").font(.system(size: 17, weight: .medium))
                } action: { press { step(-1) } }
            }
            .padding(.vertical, 8)
            HStack {
                setMenu
                Spacer()
                timerMenu
            }
            .padding(.horizontal, 6)
            Button { press { client.refreshAC() } } label: {
                Text("OK").font(.system(size: 15, weight: .semibold)).foregroundStyle(Hand.ink)
            }
            .buttonStyle(OKStyle())
            .help("Read the air conditioner again")
        }
        .frame(width: Self.size, height: Self.size)
    }

    private func step(_ delta: Double) {
        guard let ac, let target = ac.target else { return }
        let next = min(max(target + delta, ac.min), ac.max)
        if next != target { client.setAC(["target": next]) }
    }

    private var setMenu: some View {
        Menu {
            Section("Mode") {
                ForEach(ac?.modes ?? [], id: \.self) { mode in
                    Button(ACNames.modes[mode]?.0 ?? mode) { press { client.setAC(["mode": mode]) } }
                }
            }
            Section("Fan") {
                ForEach(ac?.fans ?? [], id: \.self) { fan in
                    Button(ACNames.fans[fan] ?? fan) { press { client.setAC(["fan": fan]) } }
                }
            }
            if ac?.hasTurbo == true {
                Button(ac?.turbo == true ? "Turbo Off" : "Turbo On") { press { client.setAC(["turbo": !(ac?.turbo ?? false)]) } }
            }
        } label: {
            Text("SET").font(.system(size: 12, weight: .bold)).foregroundStyle(Hand.ink)
                .frame(width: 44, height: 44).contentShape(Rectangle())
        }
        .menuStyle(.button)
        .buttonStyle(RingPress())
        .menuIndicator(.hidden)
        .fixedSize()
        .help("Choose a mode, fan speed or Turbo")
    }

    private var timerMenu: some View {
        Menu {
            ForEach(ac?.timerChoices ?? [], id: \.self) { minutes in
                Button("Off in \(ACNames.duration(minutes))") { press { client.setOffTimer(minutes) } }
            }
            if ac?.offIn != nil {
                Divider()
                Button("Cancel Timer") { press { client.setOffTimer(nil) } }
            }
        } label: {
            Image(systemName: "clock").font(.system(size: 15, weight: .medium)).foregroundStyle(Hand.ink)
                .frame(width: 44, height: 44).contentShape(Rectangle())
        }
        .menuStyle(.button)
        .buttonStyle(RingPress())
        .menuIndicator(.hidden)
        .fixedSize()
        .help("Timer: turn the air conditioner off later")
    }
}

/// The parts of the ring: no outline of their own, they darken and sink when pressed.
private struct RingButton<Label: View>: View {
    let help: String
    @ViewBuilder let label: () -> Label
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            label().foregroundStyle(Hand.ink).frame(width: 54, height: 40).contentShape(Rectangle())
        }
        .buttonStyle(RingPress())
        .help(help)
    }
}

private struct RingPress: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .background(Capsule().fill(Color.black.opacity(configuration.isPressed ? 0.07 : 0)))
            .scaleEffect(configuration.isPressed ? 0.9 : 1)
            .animation(.spring(response: 0.18, dampingFraction: 0.7), value: configuration.isPressed)
    }
}

private struct OKStyle: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        let down = configuration.isPressed
        return configuration.label
            .frame(width: 78, height: 78)
            .background(Circle().fill(LinearGradient(colors: down ? [Hand.keyDown, Hand.keyDown] : [Hand.keyTop, Hand.shellBottom],
                                                     startPoint: .top, endPoint: .bottom)))
            .overlay(Circle().strokeBorder(Hand.keyEdge))
            .shadow(color: .black.opacity(down ? 0.03 : 0.10), radius: down ? 1 : 3, y: down ? 0 : 1)
            .scaleEffect(down ? 0.95 : 1)
            .animation(.spring(response: 0.18, dampingFraction: 0.7), value: down)
    }
}

/// The three small keys at the bottom: Cool/Heat Flash, LED and Fresh, with the child lock
/// mark under LED and Fresh, as printed on the Midea remote.
private struct BarKeys: View {
    let flash: Bool
    let led: Bool
    let locked: Bool
    let onFlash: () -> Void
    let onLED: () -> Void
    let onFresh: () -> Void
    let onLock: () -> Void

    var body: some View {
        VStack(spacing: 2) {
            HStack(spacing: 3) {
                box(enabled: flash, action: onFlash, help: "Cool or Heat Flash: the fastest change for a few minutes") {
                    VStack(spacing: 0) {
                        Text("Cool/Heat")
                        Text("Flash")
                    }
                    .font(.system(size: 7.5, weight: .semibold))
                    .lineLimit(1)
                    .fixedSize()
                }
                box(enabled: led, action: onLED, help: "The light on the indoor unit") {
                    Text("LED").font(.system(size: 11, weight: .semibold))
                }
                box(enabled: true, action: onFresh, help: "Fresh air") {
                    Text("Fresh").font(.system(size: 11, weight: .semibold))
                }
            }
            lockMark
        }
    }

    /// The bracket and padlock under LED and Fresh: hold both on the real remote to lock it.
    private var lockMark: some View {
        Button(action: onLock) {
            ZStack {
                Path { path in
                    path.move(to: CGPoint(x: 0, y: 0))
                    path.addLine(to: CGPoint(x: 0, y: 5))
                    path.addLine(to: CGPoint(x: 70, y: 5))
                    path.addLine(to: CGPoint(x: 70, y: 0))
                }
                .stroke(Hand.soft, lineWidth: 1)
                .frame(width: 70, height: 6)
                Image(systemName: locked ? "lock.fill" : "lock")
                    .font(.system(size: 8, weight: .semibold))
                    .foregroundStyle(locked ? Hand.power : Hand.soft)
                    .padding(.horizontal, 3)
                    .background(Hand.shellBottom)
                    .offset(y: 5)
            }
            .frame(width: 84, height: 16)
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .offset(x: 33)
        .help(locked ? "Unlock the keys" : "Child lock: lock the keys")
    }

    private func box<Label: View>(enabled: Bool, action: @escaping () -> Void, help: String,
                                  @ViewBuilder label: () -> Label) -> some View {
        Button(action: action) {
            label()
                .foregroundStyle(enabled ? Hand.ink : Hand.ink.opacity(0.32))
                .frame(width: 62, height: 30)
                .contentShape(Rectangle())
        }
        .buttonStyle(SegmentPress())
        .disabled(!enabled)
        .help(help)
    }
}

private struct SegmentPress: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        let down = configuration.isPressed
        return configuration.label
            .background(RoundedRectangle(cornerRadius: 7, style: .continuous).fill(LinearGradient(
                colors: down ? [Hand.keyDown, Hand.keyDown] : [Hand.keyTop, Hand.keyBottom], startPoint: .top, endPoint: .bottom)))
            .overlay(RoundedRectangle(cornerRadius: 7, style: .continuous).strokeBorder(Hand.keyEdge))
            .shadow(color: .black.opacity(down ? 0.03 : 0.10), radius: down ? 0.5 : 1.5, y: down ? 0 : 1)
            .scaleEffect(down ? 0.94 : 1)
            .animation(.spring(response: 0.16, dampingFraction: 0.7), value: configuration.isPressed)
    }
}

/// The remote's screen: set temperature in LCD digits, fan bars, mode, and the small signs.
private struct LCD: View {
    let ac: ACState?
    let lit: Bool
    let locked: Bool

    private var on: Bool { ac?.isOnline == true && ac?.power == true }
    /// Ten thin bars, like the remote's fan scale.
    private static let fanBars = ["silent": 2, "low": 4, "medium": 6, "high": 8, "max": 10, "auto": 10]

    var body: some View {
        VStack(alignment: .leading, spacing: 5) {
            HStack(spacing: 5) {
                Text(ac?.cleaning == true ? "CLEAN" : "SET TEMP.").font(.system(size: 9.5, weight: .heavy)).tracking(0.6)
                Spacer()
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
