import AppKit
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
    static let swings = ["off": "Fixed", "vertical": "Up/down", "horizontal": "Sideways", "both": "Both"]
    /// How fast the air lines move for each fan speed.
    static let speed = ["silent": 0.5, "low": 0.8, "medium": 1.1, "high": 1.5, "max": 1.9, "auto": 1.2]

    static func duration(_ minutes: Int) -> String {
        minutes < 60 ? "\(minutes) min" : minutes % 60 == 0 ? "\(minutes / 60) h" : "\(minutes / 60) h \(minutes % 60) min"
    }
}

/// The air conditioner panel that drops from the menu bar.
struct ACPanelView: View {
    @ObservedObject var client: ACClient

    static let width: CGFloat = 340
    /// The Terminal step that links an air conditioner; the password is typed there, never in Couch.
    static let linkCommand = "cd \(Bundle.main.object(forInfoDictionaryKey: "BreezeProjectPath") as? String ?? "breeze") && uv run python tools/ac_link.py"

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            if let ac = client.ac, ac.isOnline {
                ACControls(client: client, ac: ac)
            } else {
                placeholder(client.ac)
            }
            if let toast = client.toast {
                Text(toast).font(.system(size: 12)).foregroundStyle(ACTheme.dim)
                    .padding(.top, 12).transition(.opacity)
            }
        }
        .padding(22)
        .frame(width: Self.width)
        .background(LinearGradient(colors: [ACTheme.top, ACTheme.bottom], startPoint: .top, endPoint: .bottom))
        .clipShape(RoundedRectangle(cornerRadius: 28, style: .continuous))
        .overlay(RoundedRectangle(cornerRadius: 28, style: .continuous).strokeBorder(ACTheme.tileEdge))
        .foregroundStyle(ACTheme.text)
        .environment(\.colorScheme, .dark)
        .onAppear { client.refreshAC() }
    }

    @ViewBuilder private func placeholder(_ ac: ACState?) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            Label("Air conditioner", systemImage: "air.conditioner.horizontal")
                .font(.system(size: 15, weight: .semibold))
            switch ac?.status {
            case .unlinked:
                Text("Link your Midea air conditioner once. In Terminal, run this and sign in with your MSmartHome account:")
                    .font(.callout).foregroundStyle(ACTheme.dim).fixedSize(horizontal: false, vertical: true)
                Text(Self.linkCommand)
                    .font(.system(size: 11, design: .monospaced)).textSelection(.enabled)
                    .padding(10).frame(maxWidth: .infinity, alignment: .leading)
                    .background(RoundedRectangle(cornerRadius: 10).fill(ACTheme.track))
                Button("Copy Command") {
                    NSPasteboard.general.clearContents()
                    NSPasteboard.general.setString(Self.linkCommand, forType: .string)
                }
            case .offline:
                Text("Can't reach the air conditioner. Is it switched on at the wall and on your Wi-Fi?")
                    .font(.callout).foregroundStyle(ACTheme.dim).fixedSize(horizontal: false, vertical: true)
                Button("Try Again") { client.refreshAC() }
            default:
                HStack(spacing: 10) {
                    ProgressView().controlSize(.small)
                    Text("Looking for the air conditioner…").font(.callout).foregroundStyle(ACTheme.dim)
                }
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}

private struct ACControls: View {
    @ObservedObject var client: ACClient
    let ac: ACState
    /// The slider's value while dragging, so the poll does not pull the thumb back.
    @State private var draft: Double?

    private var shown: Double { draft ?? ac.target ?? ac.min }

    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            header
            ACUnit(target: shown, ac: ac)
                .frame(height: 150)
                .overlay(alignment: .bottom) {
                    if ac.cleaning {
                        Label("Self-cleaning. Press power to stop it.", systemImage: "sparkles")
                            .font(.system(size: 12, weight: .semibold))
                            .padding(.horizontal, 12).padding(.vertical, 7)
                            .background(Capsule().fill(ACTheme.eco.opacity(0.22)))
                            .foregroundStyle(ACTheme.eco)
                            .transition(.opacity)
                    }
                }
            VStack(alignment: .leading, spacing: 18) {
                HStack(alignment: .center) {
                    HStack(alignment: .firstTextBaseline, spacing: 2) {
                        Text("\(Int(shown))")
                            .font(.system(size: 66, weight: .thin, design: .rounded))
                            .contentTransition(.numericText(value: shown))
                        Text("°C").font(.system(size: 20, weight: .medium)).foregroundStyle(ACTheme.accent)
                    }
                    .animation(.snappy(duration: 0.25), value: shown)
                    Spacer()
                    if ac.hasEco { ecoToggle }
                }
                TemperatureSlider(value: shown, range: ac.min...ac.max,
                                  onDrag: { draft = $0 },
                                  onCommit: { value in
                                      draft = nil
                                      if value != ac.target { client.setAC(["target": value]) }
                                  })
                tiles
                extras
            }
            .opacity(ac.power ? 1 : 0.45)
            .animation(.easeInOut(duration: 0.3), value: ac.power)
        }
    }

    private var header: some View {
        HStack {
            Image(systemName: "thermometer.medium").foregroundStyle(ACTheme.accent)
            Text("Room").foregroundStyle(ACTheme.dim)
            Text(ac.indoor.map { "\(Int($0.rounded()))°C" } ?? "--").fontWeight(.semibold)
            if let outdoor = ac.outdoor {
                Text("Outside \(Int(outdoor.rounded()))°").foregroundStyle(ACTheme.faint).padding(.leading, 6)
            }
            Spacer()
            Button { client.setAC(["power": !ac.power]) } label: {
                Image(systemName: "power")
                    .font(.system(size: 20, weight: .semibold))
                    .frame(width: 52, height: 52)
                    .background(Circle().fill(ac.power ? ACTheme.accent : ACTheme.tile))
                    .overlay(Circle().strokeBorder(ac.power ? Color.clear : ACTheme.tileEdge))
                    .shadow(color: ac.power ? ACTheme.accent.opacity(0.55) : .clear, radius: 14)
            }
            .buttonStyle(PressScale())
            .help(ac.power ? "Turn the air conditioner off" : "Turn the air conditioner on")
            .animation(.easeInOut(duration: 0.25), value: ac.power)
        }
        .font(.system(size: 14))
    }

    private var ecoToggle: some View {
        Button { client.setAC(["eco": !ac.eco]) } label: {
            HStack(spacing: 8) {
                Image(systemName: "leaf.fill").foregroundStyle(ACTheme.eco)
                Text("Eco").font(.system(size: 13, weight: .semibold))
                Capsule().fill(ac.eco ? ACTheme.accent : ACTheme.track)
                    .frame(width: 40, height: 24)
                    .overlay(alignment: ac.eco ? .trailing : .leading) {
                        Circle().fill(.white).padding(3)
                    }
            }
            .padding(.leading, 12).padding(.trailing, 6).padding(.vertical, 6)
            .background(RoundedRectangle(cornerRadius: 14, style: .continuous).fill(ACTheme.tile))
            .overlay(RoundedRectangle(cornerRadius: 14, style: .continuous).strokeBorder(ACTheme.tileEdge))
            .animation(.spring(duration: 0.3), value: ac.eco)
        }
        .buttonStyle(PressScale())
        .help("Saves energy while cooling")
    }

    private var tiles: some View {
        HStack(spacing: 8) {
            let mode = ACNames.modes[ac.mode ?? ""]
            pickTile(title: "Mode", value: mode?.0 ?? "--", symbol: mode?.1 ?? "snowflake",
                     options: ac.modes.map { ($0, ACNames.modes[$0]?.0 ?? $0) }, current: ac.mode) {
                client.setAC(["mode": $0])
            }
            pickTile(title: "Fan", value: ACNames.fans[ac.fan ?? ""] ?? "--", symbol: "fan",
                     options: ac.fans.map { ($0, ACNames.fans[$0] ?? $0) }, current: ac.fan) {
                client.setAC(["fan": $0])
            }
            Button { client.setAC(["sleep": !ac.sleep]) } label: {
                ACTile(title: "Sleep", value: ac.sleep ? "On" : "Off", symbol: ac.sleep ? "moon.fill" : "moon",
                       active: ac.sleep, chevron: false)
            }
            .buttonStyle(PressScale())
            .help("Sleep mode raises the temperature slowly through the night")
            pickTile(title: "Airflow", value: ACNames.swings[ac.swing ?? ""] ?? "--", symbol: "wind",
                     options: ac.swings.map { ($0, ACNames.swings[$0] ?? $0) }, current: ac.swing) {
                client.setAC(["swing": $0])
            }
        }
    }

    private func pickTile(title: String, value: String, symbol: String, options: [(String, String)],
                          current: String?, pick: @escaping (String) -> Void) -> some View {
        Menu {
            ForEach(options, id: \.0) { option in
                Button { pick(option.0) } label: {
                    if option.0 == current { Label(option.1, systemImage: "checkmark") } else { Text(option.1) }
                }
            }
        } label: {
            ACTile(title: title, value: value, symbol: symbol, active: false, chevron: true)
        }
        .menuStyle(.button)
        .buttonStyle(PressScale())
        .menuIndicator(.hidden)
    }

    private var extras: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(spacing: 8) {
                if ac.hasFlash {
                    chip("Flash", symbol: "snowflake.circle", on: ac.flash) { client.setAC(["flash": !ac.flash]) }
                        .help("Cool or Heat Flash: the fastest change for a few minutes")
                }
                if ac.hasTurbo {
                    chip("Turbo", symbol: "bolt.fill", on: ac.turbo) { client.setAC(["turbo": !ac.turbo]) }
                        .help("Cools as fast as it can for a while")
                }
                if ac.hasDisplay {
                    chip("Light", symbol: ac.display ? "lightbulb.fill" : "lightbulb", on: ac.display) {
                        client.toggleACDisplay()
                    }
                    .help("The light on the indoor unit, like the LED button")
                }
                Spacer(minLength: 0)
            }
            timer
        }
    }

    private var timer: some View {
        Menu {
            ForEach(ac.timerChoices, id: \.self) { minutes in
                Button(ACNames.duration(minutes)) { client.setOffTimer(minutes) }
            }
            if ac.offIn != nil {
                Divider()
                Button("Cancel Timer") { client.setOffTimer(nil) }
            }
        } label: {
            Label(ac.offIn.map { "Off in \(ACNames.duration($0))" } ?? "Timer", systemImage: "timer")
                .font(.system(size: 12, weight: .semibold))
                .padding(.horizontal, 12).padding(.vertical, 7)
                .background(Capsule().fill(ac.offIn != nil ? ACTheme.accent.opacity(0.9) : ACTheme.tile))
                .overlay(Capsule().strokeBorder(ac.offIn != nil ? Color.clear : ACTheme.tileEdge))
        }
        .menuStyle(.button)
        .buttonStyle(PressScale())
        .menuIndicator(.hidden)
        .fixedSize()
        .help("Turn the air conditioner off later")
    }

    private func chip(_ title: String, symbol: String, on: Bool, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            Label(title, systemImage: symbol)
                .font(.system(size: 12, weight: .semibold))
                .padding(.horizontal, 12).padding(.vertical, 7)
                .background(Capsule().fill(on ? ACTheme.accent.opacity(0.9) : ACTheme.tile))
                .overlay(Capsule().strokeBorder(on ? Color.clear : ACTheme.tileEdge))
                .animation(.easeInOut(duration: 0.2), value: on)
        }
        .buttonStyle(PressScale())
    }
}

/// One square control: symbol, name and current value.
private struct ACTile: View {
    let title: String
    let value: String
    let symbol: String
    let active: Bool
    let chevron: Bool

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack(alignment: .top) {
                Image(systemName: symbol)
                    .font(.system(size: 20))
                    .foregroundStyle(active ? ACTheme.accent : ACTheme.accent.opacity(0.85))
                    .contentTransition(.symbolEffect(.replace))
                Spacer()
                if chevron {
                    Image(systemName: "chevron.down").font(.system(size: 10, weight: .bold)).foregroundStyle(ACTheme.dim)
                } else {
                    Circle().fill(active ? ACTheme.accent : ACTheme.faint).frame(width: 6, height: 6)
                }
            }
            Spacer(minLength: 6)
            Text(title).font(.system(size: 12)).foregroundStyle(ACTheme.dim)
            Text(value).font(.system(size: 12, weight: .semibold)).lineLimit(1).minimumScaleFactor(0.8)
                .contentTransition(.opacity)
        }
        .padding(10)
        .frame(width: 68, height: 82, alignment: .topLeading)
        .background(RoundedRectangle(cornerRadius: 16, style: .continuous).fill(active ? ACTheme.accent.opacity(0.18) : ACTheme.tile))
        .overlay(RoundedRectangle(cornerRadius: 16, style: .continuous).strokeBorder(ACTheme.tileEdge))
        .animation(.easeInOut(duration: 0.2), value: value)
    }
}

/// Whole degrees on a track, with minus and plus either side. Sends once, when let go.
private struct TemperatureSlider: View {
    let value: Double
    let range: ClosedRange<Double>
    let onDrag: (Double) -> Void
    let onCommit: (Double) -> Void
    private static let thumb: CGFloat = 40

    var body: some View {
        VStack(spacing: 6) {
            HStack(spacing: 10) {
                step("minus", by: -1)
                GeometryReader { proxy in
                    let width = proxy.size.width - Self.thumb
                    let fraction = (value - range.lowerBound) / max(range.upperBound - range.lowerBound, 1)
                    ZStack(alignment: .leading) {
                        Capsule().fill(ACTheme.track)
                        HStack(spacing: 0) {
                            ForEach(Int(range.lowerBound)...Int(range.upperBound), id: \.self) { degree in
                                Rectangle().fill(Double(degree) <= value ? ACTheme.accent.opacity(0.7) : ACTheme.faint)
                                    .frame(width: 1, height: degree % 5 == 0 ? 10 : 6)
                                if degree < Int(range.upperBound) { Spacer(minLength: 0) }
                            }
                        }
                        .padding(.horizontal, Self.thumb / 2)
                        RoundedRectangle(cornerRadius: 12, style: .continuous)
                            .fill(.white)
                            .overlay(RoundedRectangle(cornerRadius: 12, style: .continuous).strokeBorder(ACTheme.accent, lineWidth: 3))
                            .frame(width: Self.thumb, height: Self.thumb)
                            .shadow(color: ACTheme.accent.opacity(0.5), radius: 8)
                            .offset(x: width * fraction)
                            .animation(.snappy(duration: 0.2), value: value)
                    }
                    .contentShape(Rectangle())
                    .gesture(DragGesture(minimumDistance: 0)
                        .onChanged { onDrag(degrees(at: $0.location.x, width: width)) }
                        .onEnded { onCommit(degrees(at: $0.location.x, width: width)) })
                }
                .frame(height: 48)
                step("plus", by: 1)
            }
            HStack {
                Text("\(Int(range.lowerBound))°")
                Spacer()
                Text("\(Int(range.upperBound))°")
            }
            .font(.system(size: 11)).foregroundStyle(ACTheme.dim)
            .padding(.horizontal, 58)
        }
    }

    private func degrees(at x: CGFloat, width: CGFloat) -> Double {
        let fraction = Double(min(max((x - Self.thumb / 2) / max(width, 1), 0), 1))
        return (range.lowerBound + fraction * (range.upperBound - range.lowerBound)).rounded()
    }

    private func step(_ symbol: String, by delta: Double) -> some View {
        Button { onCommit(min(max(value + delta, range.lowerBound), range.upperBound)) } label: {
            Image(systemName: symbol)
                .font(.system(size: 14, weight: .semibold))
                .frame(width: 40, height: 40)
                .background(Circle().fill(ACTheme.tile))
                .overlay(Circle().strokeBorder(ACTheme.tileEdge))
        }
        .buttonStyle(PressScale())
        .disabled(delta < 0 ? value <= range.lowerBound : value >= range.upperBound)
    }
}

/// Buttons shrink a little while pressed.
struct PressScale: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .scaleEffect(configuration.isPressed ? 0.94 : 1)
            .animation(.spring(duration: 0.2), value: configuration.isPressed)
    }
}
