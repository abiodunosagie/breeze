import SwiftUI

/// Electricity the AC uses: power now, today and this month, the last 24 hours, and the cost
/// in naira once the user has set a price per kWh.
struct EnergyCard: View {
    @ObservedObject var client: ACClient
    let ac: ACState
    @State private var editingPrice = false
    @State private var priceText = ""

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(alignment: .firstTextBaseline) {
                Label(ac.powerW.map { "\($0) W now" } ?? "Power", systemImage: "bolt.fill")
                    .font(.system(size: 12, weight: .semibold))
                    .foregroundStyle(Color(red: 1, green: 0.82, blue: 0.4))
                    .contentTransition(.numericText())
                Spacer()
                priceButton
            }
            HStack(alignment: .bottom, spacing: 16) {
                figure("Today", ac.todayKWh)
                figure("This month", ac.monthKWh)
                Spacer()
                HourBars(values: ac.hourlyKWh)
                    .frame(width: 120, height: 34)
                    .help("Electricity used each hour, the last 24 hours")
            }
        }
        .padding(12)
        .background(RoundedRectangle(cornerRadius: 16, style: .continuous).fill(ACTheme.tile))
        .overlay(RoundedRectangle(cornerRadius: 16, style: .continuous).strokeBorder(ACTheme.tileEdge))
    }

    private func figure(_ title: String, _ kwh: Double) -> some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(title).font(.system(size: 11)).foregroundStyle(ACTheme.dim)
            Text(String(format: "%.1f kWh", kwh)).font(.system(size: 13, weight: .semibold)).fixedSize()
            if ac.pricePerKWh > 0 {
                Text(Self.naira(kwh * ac.pricePerKWh)).font(.system(size: 11, weight: .medium)).foregroundStyle(ACTheme.eco)
            }
        }
    }

    private var priceButton: some View {
        Button {
            priceText = ac.pricePerKWh > 0 ? String(format: "%g", ac.pricePerKWh) : ""
            editingPrice = true
        } label: {
            Text(ac.pricePerKWh > 0 ? "\(Self.naira(ac.pricePerKWh)) per kWh" : "Set price")
                .font(.system(size: 11, weight: .medium)).foregroundStyle(ACTheme.dim)
        }
        .buttonStyle(.borderless)
        .help("Your electricity price, to show the cost in naira")
        .popover(isPresented: $editingPrice, arrowEdge: .bottom) {
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
    }

    private func savePrice() {
        let value = Double(priceText.replacingOccurrences(of: ",", with: "").trimmingCharacters(in: .whitespaces)) ?? -1
        guard value >= 0 else {
            client.show("Type the price as a number, like 209.5.")
            return
        }
        client.setSetting("price_per_kwh", value)
        editingPrice = false
    }

    static func naira(_ amount: Double) -> String {
        "₦" + amount.formatted(.number.precision(.fractionLength(amount < 100 ? 2 : 0)))
    }
}

/// Small bars, one for each hour, oldest on the left.
private struct HourBars: View {
    let values: [Double]

    var body: some View {
        let top = max(values.max() ?? 0, 0.01)
        HStack(alignment: .bottom, spacing: 2) {
            ForEach(Array(values.enumerated()), id: \.offset) { _, value in
                RoundedRectangle(cornerRadius: 1.5)
                    .fill(value > 0 ? ACTheme.accent.opacity(0.85) : ACTheme.faint.opacity(0.4))
                    .frame(height: max(2, CGFloat(value / top) * 34))
            }
        }
        .animation(.easeInOut(duration: 0.4), value: values)
    }
}
