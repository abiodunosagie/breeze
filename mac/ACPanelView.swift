import AppKit
import SwiftUI

/// The air conditioner panel that drops from the menu bar.
struct ACPanelView: View {
    @ObservedObject var client: ACClient
    let openWindow: () -> Void

    static let width: CGFloat = 340
    /// The Terminal step that links an air conditioner; the password is typed there, never in Breeze.
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
            footer
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

    private var footer: some View {
        HStack {
            Button("Open Remote", action: openWindow)
            Spacer()
            Button("Quit Breeze") { NSApp.terminate(nil) }
                .help("Quit Breeze")
        }
        .buttonStyle(.borderless)
        .font(.system(size: 12, weight: .medium))
        .foregroundStyle(ACTheme.dim)
        .padding(.top, 16)
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
                .overlay(alignment: .bottom) { banner }
                .animation(.easeInOut(duration: 0.3), value: banner.key)
            VStack(alignment: .leading, spacing: 18) {
                HStack(alignment: .center) {
                    VStack(alignment: .leading, spacing: 0) {
                        HStack(alignment: .firstTextBaseline, spacing: 2) {
                            Text("\(Int(shown))")
                                .font(.system(size: 66, weight: .thin, design: .rounded))
                                .contentTransition(.numericText(value: shown))
                            Text("°C").font(.system(size: 20, weight: .medium)).foregroundStyle(ACTheme.accent)
                        }
                        .animation(.snappy(duration: 0.25), value: shown)
                        Text(statusLine)
                            .font(.system(size: 12, weight: .medium))
                            .foregroundStyle(ACTheme.dim)
                            .contentTransition(.opacity)
                            .animation(.easeInOut(duration: 0.3), value: statusLine)
                    }
                    // Fan only: the AC does not cool, so the temperature has no say.
                    .opacity(fanOnly ? 0.4 : 1)
                    Spacer()
                    if ac.hasEco { ecoToggle }
                }
                TemperatureSlider(value: shown, range: ac.min...ac.max,
                                  onDrag: { draft = $0 },
                                  onCommit: { value in
                                      draft = nil
                                      if value != ac.target { client.setAC(["target": value]) }
                                  })
                    .disabled(fanOnly)
                    .opacity(fanOnly ? 0.4 : 1)
                tiles
                extras
                EnergyCard(client: client, ac: ac)
            }
            .opacity(ac.power ? 1 : 0.45)
            // Sleep mode: the panel dims for the night.
            .brightness(ac.sleep && ac.power ? -0.08 : 0)
            .animation(.easeInOut(duration: 0.5), value: ac.sleep)
            // A drag cut short by the panel closing must not pin the slider.
            .onDisappear { draft = nil }
            .animation(.easeInOut(duration: 0.3), value: ac.power)
        }
    }

    private var fanOnly: Bool { ac.mode == "fan" }

    /// What the AC is really doing, under the big number.
    private var statusLine: String {
        if ac.cleaning { return "Self-cleaning" + (ac.cleaningMinutes.map { ", \($0) min so far" } ?? "") }
        if ac.dryingMinutesLeft != nil { return "Drying the coil, then off" }
        switch ac.phase {
        case "working": return ac.turbo ? "Turbo, cooling fast" : ac.mode == "dry" ? "Drying the air" : "Cooling the room"
        case "holding": return "Room at temperature, resting"
        case "fan": return "Fan only, no cooling"
        default: return "Off"
        }
    }

    /// One message on the unit, the most important first: fault, clean, filter.
    private var banner: Banner {
        if let fault = ac.fault {
            return Banner(key: "fault", text: "The AC reports fault \(fault). Check the unit.", symbol: "exclamationmark.triangle.fill",
                          color: Color(red: 1, green: 0.45, blue: 0.4))
        }
        if let minutes = ac.dryingMinutesLeft {
            return Banner(key: "drying", text: "Drying the coil, up to \(minutes) min. Power stops it now.", symbol: "wind",
                          color: ACTheme.accent)
        }
        if ac.cleaning {
            return Banner(key: "clean", text: "Self-cleaning. Press power to stop it.", symbol: "sparkles", color: ACTheme.eco)
        }
        if ac.filterDue {
            return Banner(key: "filter", text: "Time to wash the filter.", symbol: "aqi.medium", color: Color(red: 1, green: 0.78, blue: 0.4))
        }
        if !ac.display && ac.power {
            return Banner(key: "light", text: "The unit's light is off.", symbol: "lightbulb.slash", color: ACTheme.dim)
        }
        return Banner(key: "none", text: "", symbol: "", color: .clear)
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
            pickTile(title: "Fan", value: ac.fanPercent.map { "\($0)%" } ?? ACNames.fans[ac.fan ?? ""] ?? "--", symbol: "fan",
                     options: ac.fans.map { ($0, ACNames.fans[$0] ?? $0) }, current: ac.fanPercent == nil ? ac.fan : nil) {
                client.setAC(["fan": $0])
            } more: {
                if ac.hasFanPercent {
                    Section("Exact speed") {
                        ForEach(Array(stride(from: 10, through: 100, by: 10)), id: \.self) { percent in
                            checkButton("\(percent)%", on: ac.fanPercent == percent) { client.setAC(["fan_percent": percent]) }
                        }
                    }
                }
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
            } more: {
                if ac.hasLouverV {
                    Section("Hold up and down at") {
                        ForEach(ACNames.louverPositions, id: \.0) { position in
                            checkButton(position.1, on: ac.louverV == position.0) { client.setAC(["louver_v": position.0]) }
                        }
                    }
                }
                if ac.hasLouverH {
                    Section("Hold side to side at") {
                        ForEach(ACNames.louverSides, id: \.0) { position in
                            checkButton(position.1, on: ac.louverH == position.0) { client.setAC(["louver_h": position.0]) }
                        }
                    }
                }
            }
        }
    }

    private func pickTile<More: View>(title: String, value: String, symbol: String, options: [(String, String)],
                                      current: String?, pick: @escaping (String) -> Void,
                                      @ViewBuilder more: () -> More = { EmptyView() }) -> some View {
        Menu {
            ForEach(options, id: \.0) { option in
                checkButton(option.1, on: option.0 == current) { pick(option.0) }
            }
            more()
        } label: {
            ACTile(title: title, value: value, symbol: symbol, active: false, chevron: true)
        }
        .menuStyle(.button)
        .buttonStyle(PressScale())
        .menuIndicator(.hidden)
    }

    private func checkButton(_ title: String, on: Bool, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            if on { Label(title, systemImage: "checkmark") } else { Text(title) }
        }
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
            if ac.hasPurifier || ac.hasBreezeAway {
                HStack(spacing: 8) {
                    if ac.hasPurifier {
                        chip("Purify", symbol: "aqi.low", on: ac.purifier) { client.setAC(["purifier": !ac.purifier]) }
                            .help("The unit's air purifier (ioniser)")
                    }
                    if ac.hasBreezeAway {
                        chip("Breeze Away", symbol: "wind.circle", on: ac.breezeAway) { client.setAC(["breeze_away": !ac.breezeAway]) }
                            .help("Steers the air away from you, so it does not blow straight on you")
                    }
                    Spacer(minLength: 0)
                }
            }
            HStack {
                timer
                Spacer()
                Toggle(isOn: Binding(get: { ac.dryCoil }, set: { client.setSetting("dry_coil", $0) })) {
                    Text("Dry coil after use").font(.system(size: 12, weight: .semibold))
                }
                .toggleStyle(.switch)
                .controlSize(.mini)
                .tint(ACTheme.accent)
                .help("When you switch off after cooling, the fan runs alone until the coil is dry (up to 20 min), so mould and smells have no damp to grow in")
            }
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

/// A short message shown on the drawn unit.
private struct Banner: View {
    let key: String
    let text: String
    let symbol: String
    let color: Color

    var body: some View {
        if !text.isEmpty {
            Label(text, systemImage: symbol)
                .font(.system(size: 12, weight: .semibold))
                .padding(.horizontal, 12).padding(.vertical, 7)
                .background(Capsule().fill(color.opacity(0.22)))
                .foregroundStyle(color)
                .transition(.opacity)
        }
    }
}
