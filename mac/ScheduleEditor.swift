import SwiftUI

/// The user's schedules, edited as a list and saved all at once. The helper checks every entry.
struct ScheduleEditor: View {
    @ObservedObject var client: ACClient
    let ac: ACState
    var done: () -> Void
    @State private var entries: [ACSchedule] = []
    /// Saved and waiting for the helper to send the list back; closes then. A refused list stays open.
    @State private var saving = false

    private static let maxEntries = 16  // MAX_SCHEDULES in timetable.py
    private static let graceMinutes = 15  // GRACE_SECONDS in timetable.py
    private static let dayLetters = ["M", "T", "W", "T", "F", "S", "S"]

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("Schedules").font(.headline)
            if ac.schedules == nil {
                Text("Breeze could not read the saved schedules.").foregroundStyle(.secondary)
            } else if entries.isEmpty {
                Text("No schedules yet.").foregroundStyle(.secondary)
            }
            ForEach($entries) { $entry in
                row($entry)
                Divider()
            }
            HStack {
                Button("Add Schedule", action: add).disabled(entries.count >= Self.maxEntries)
                Spacer()
                Button("Cancel", action: done)
                Button(saving ? "Saving…" : "Save") {
                    // As the helper keeps them, so the list it sends back compares equal.
                    entries = entries.map { entry in
                        var e = entry
                        if !e.power { e.target = nil; e.mode = nil; e.fan = nil }
                        return e
                    }
                    saving = true
                    client.saveSchedules(entries)
                }
                .keyboardShortcut(.defaultAction)
                .disabled(ac.schedules == nil || saving)
            }
            Text("Runs while Breeze is running and the air conditioner is reachable, up to \(Self.graceMinutes) minutes late.")
                .font(.caption).foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)
        }
        .padding(14)
        .frame(width: 360)
        .onAppear { entries = ac.schedules ?? [] }
        .onChange(of: ac.schedules) { _, saved in
            if saving && saved == entries { done() }
        }
        .onChange(of: client.toast) { _, toast in
            if saving && toast != nil { saving = false }  // refused: the reason shows, the edits stay
        }
    }

    private func row(_ entry: Binding<ACSchedule>) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(spacing: 10) {
                Toggle("", isOn: entry.enabled).toggleStyle(.switch).controlSize(.mini).labelsHidden()
                DatePicker("", selection: timeBinding(entry), displayedComponents: .hourAndMinute).labelsHidden()
                Picker("", selection: entry.power) {
                    Text("Switch On").tag(true)
                    Text("Switch Off").tag(false)
                }
                .labelsHidden()
                .frame(width: 104)
                Spacer()
                Button {
                    entries.removeAll { $0.id == entry.wrappedValue.id }
                } label: {
                    Image(systemName: "trash")
                }
                .buttonStyle(.borderless)
                .help("Remove this schedule")
            }
            HStack(spacing: 2) {
                ForEach(0..<7, id: \.self) { day in
                    let on = entry.wrappedValue.days.contains(day)
                    Button(Self.dayLetters[day]) { toggle(day, in: entry) }
                        .buttonStyle(.borderless)
                        .font(.system(size: 12, weight: on ? .bold : .regular))
                        .foregroundStyle(on ? ACTheme.accent : .secondary)
                        .frame(width: 22)
                }
                if entry.wrappedValue.power {
                    Spacer()
                    Stepper(value: targetBinding(entry), in: ac.min...ac.max, step: 1) {
                        Text("\(Int(targetBinding(entry).wrappedValue))°").monospacedDigit()
                    }
                }
            }
        }
    }

    private func add() {
        let id = "s-" + UUID().uuidString.prefix(8).lowercased()
        entries.append(ACSchedule(id: id, days: Array(0..<7), time: "07:00", power: true, target: ac.target ?? 24))
    }

    /// Never leaves a schedule with no days: the last one stays.
    private func toggle(_ day: Int, in entry: Binding<ACSchedule>) {
        var days = entry.wrappedValue.days
        if let index = days.firstIndex(of: day) {
            if days.count > 1 { days.remove(at: index) }
        } else {
            days.append(day)
        }
        entry.wrappedValue.days = days.sorted()
    }

    private func targetBinding(_ entry: Binding<ACSchedule>) -> Binding<Double> {
        Binding(get: { entry.wrappedValue.target ?? ac.target ?? 24 }, set: { entry.wrappedValue.target = $0 })
    }

    /// "HH:MM" to and from a Date today, in the Mac's local time.
    private func timeBinding(_ entry: Binding<ACSchedule>) -> Binding<Date> {
        Binding(get: {
            let parts = entry.wrappedValue.time.split(separator: ":").compactMap { Int($0) }
            return Calendar.current.date(bySettingHour: parts.first ?? 7, minute: parts.last ?? 0, second: 0, of: Date()) ?? Date()
        }, set: { date in
            let c = Calendar.current.dateComponents([.hour, .minute], from: date)
            entry.wrappedValue.time = String(format: "%02d:%02d", c.hour ?? 7, c.minute ?? 0)
        })
    }
}
