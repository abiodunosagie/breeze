import SwiftUI

/// One quiet line under the controls: power now, today and this month (in naira once a price
/// is set), the last 24 hours as small bars, and a More menu for the less used things.
struct EnergyLine: View {
    @ObservedObject var client: ACClient
    let ac: ACState
    @State private var editingPrice = false
    @State private var priceText = ""

    private static let maxPrice = 100_000.0  // MAX_PRICE in store.py
    private static let barsSize = CGSize(width: 72, height: 24)

    var body: some View {
        HStack(alignment: .center, spacing: 10) {
            Image(systemName: "bolt.fill").foregroundStyle(ACTheme.caution).font(.system(size: 11))
            // Two short lines, so nothing is ever cut off: now and today, then the month.
            VStack(alignment: .leading, spacing: 2) {
                Text(nowAndToday)
                    .font(.system(size: 12, weight: .medium))
                    .foregroundStyle(ACTheme.dim)
                Text(thisMonth)
                    .font(.system(size: 11))
                    .foregroundStyle(ACTheme.dim.opacity(0.75))
            }
            .lineLimit(1)
            .minimumScaleFactor(0.8)
            .contentTransition(.numericText())
            Spacer(minLength: 4)
            HourBars(values: ac.hourlyKWh, height: Self.barsSize.height)
                .frame(width: Self.barsSize.width, height: Self.barsSize.height)
                .help("Electricity used each hour, the last 24 hours")
            more
        }
        .popover(isPresented: $editingPrice, arrowEdge: .bottom) { priceForm }
    }

    private var nowAndToday: String {
        let today = Self.kWh(ac.todayKWh) + " today" + cost(ac.todayKWh)
        guard let watts = ac.powerW else { return today }
        return "\(watts) W  ·  " + today
    }

    private var thisMonth: String { Self.kWh(ac.monthKWh) + " this month" + cost(ac.monthKWh) }

    /// One decimal while small, so 0.3 kWh never reads as 0.
    static func kWh(_ value: Double) -> String {
        String(format: value < 10 ? "%.1f kWh" : "%.0f kWh", value)
    }

    private func cost(_ kwh: Double) -> String {
        ac.pricePerKWh > 0 ? ", \(Self.naira(kwh * ac.pricePerKWh))" : ""
    }

    /// The less used things, out of the way of the everyday controls.
    private var more: some View {
        Menu {
            if ac.hasDisplay {
                Button(ac.display ? "Turn the Unit's Light Off" : "Turn the Unit's Light On") { client.toggleACDisplay() }
            }
            if ac.hasBreezeAway {
                Toggle("Breeze Away (air not on you)", isOn: Binding(get: { ac.breezeAway },
                                                                    set: { client.setAC(["breeze_away": $0]) }))
            }
            Divider()
            Toggle("Dry the Coil After Cooling", isOn: Binding(get: { ac.dryCoil }, set: { client.setSetting("dry_coil", $0) }))
            Toggle("Switch Back On After a Power Cut", isOn: Binding(get: { ac.restoreAfterOutage },
                                                                    set: { client.setSetting("restore_after_outage", $0) }))
            Divider()
            Button(ac.pricePerKWh > 0 ? "Electricity Price: \(Self.naira(ac.pricePerKWh)) per kWh…" : "Set Electricity Price…") {
                priceText = ac.pricePerKWh > 0 ? String(format: "%g", ac.pricePerKWh) : ""
                editingPrice = true
            }
        } label: {
            Image(systemName: "ellipsis.circle")
                .font(.system(size: 15))
                .foregroundStyle(ACTheme.dim)
                .frame(width: 26, height: 26)
                .contentShape(Rectangle())
        }
        .menuStyle(.button)
        .buttonStyle(PressScale())
        .menuIndicator(.hidden)
        .fixedSize()
        .help("More: the unit's light, Breeze Away, drying the coil, power cuts, electricity price")
    }

    private var priceForm: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("Price per kWh").font(.headline)
            Text("From your electricity bill or prepaid meter receipt.").font(.caption).foregroundStyle(.secondary)
            HStack {
                Text("₦")
                TextField("e.g. 209.5", text: $priceText).frame(width: 110).onSubmit(savePrice)
                Button("Save", action: savePrice).keyboardShortcut(.defaultAction)
            }
        }
        .padding(14)
    }

    private func savePrice() {
        guard let value = Self.parsePrice(priceText), value <= Self.maxPrice else {
            client.show("Type the price as a number, like 209.5.")
            return
        }
        client.setSetting("price_per_kwh", value)
        editingPrice = false
    }

    /// "209.5", "209,5" (comma decimal) and "1,209.5" (comma thousands) all read right; nothing infinite.
    static func parsePrice(_ text: String) -> Double? {
        var cleaned = text.trimmingCharacters(in: .whitespaces).replacingOccurrences(of: "₦", with: "")
        if cleaned.contains(".") {
            cleaned = cleaned.replacingOccurrences(of: ",", with: "")
        } else if let comma = cleaned.lastIndex(of: ","), cleaned.distance(from: comma, to: cleaned.endIndex) <= 3 {
            cleaned.replaceSubrange(comma...comma, with: ".")
            cleaned = cleaned.replacingOccurrences(of: ",", with: "")
        } else {
            cleaned = cleaned.replacingOccurrences(of: ",", with: "")
        }
        guard let value = Double(cleaned), value.isFinite, value >= 0 else { return nil }
        return value
    }

    static func naira(_ amount: Double) -> String {
        "₦" + amount.formatted(.number.precision(.fractionLength(amount < 100 ? 2 : 0)))
    }
}

/// Small bars, one for each hour, oldest on the left.
private struct HourBars: View {
    let values: [Double]
    let height: CGFloat

    var body: some View {
        let top = max(values.max() ?? 0, 0.01)
        HStack(alignment: .bottom, spacing: 1) {
            ForEach(Array(values.enumerated()), id: \.offset) { _, value in
                RoundedRectangle(cornerRadius: 1)
                    .fill(value > 0 ? ACTheme.accent.opacity(0.8) : ACTheme.faint.opacity(0.6))
                    .frame(height: max(1.5, CGFloat(value / top) * height))
            }
        }
        .animation(.easeInOut(duration: 0.4), value: values)
    }
}
