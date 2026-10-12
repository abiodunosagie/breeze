import Foundation

/// The air conditioner as the helper reports it. Lists hold only what this unit supports.
struct ACState: Decodable, Equatable {
    enum Status: String, Decodable {
        case unlinked, connecting, online, offline
    }
    var status: Status
    var power = false
    var mode: String?
    var target: Double?
    var indoor: Double?
    var outdoor: Double?
    var fan: String?
    var swing: String?
    var eco = false
    var turbo = false
    var sleep = false
    var flash = false
    var display = false
    /// Self clean is running (the unit is off meanwhile).
    var cleaning = false
    var cleaningMinutes: Int?
    /// How hard the AC really works, 0 to 1 (compressor, or fan in fan mode).
    var effort: Double = 0
    /// off, fan, working or holding (room reached, compressor resting).
    var phase = "off"
    var compressorHz: Int?
    var coil: Double?
    /// The unit's own error code, when it reports one.
    var fault: Int?
    var filterDue = false
    var purifier = false
    var breezeAway = false
    /// Louver positions "1" to "5", or nil while they swing or are not set.
    var louverV: String?
    var louverH: String?
    /// An exact fan speed, 1 to 100, when one is set instead of a named speed.
    var fanPercent: Int?
    var hasPurifier = false
    var hasBreezeAway = false
    var hasLouverV = false
    var hasLouverH = false
    var hasFanPercent = false
    var hasSelfClean = false
    /// Wet running hours since the last self clean and the last filter wash, and when each is due.
    var cleanHours: Double = 0
    var filterHours: Double = 0
    var cleanAfterHours: Double = 40
    var filterAfterHours: Double = 150
    var autoClean = false
    /// The user's schedules, and Breeze's sleep curve while it runs.
    /// nil when the list could not be read: the editor then refuses to save over it.
    var schedules: [ACSchedule]?
    var sleepCurve: SleepCurveInfo?
    var sleepCurveChoices: [Int] = []
    var sleepCurveEnd = "restore"
    /// How well it cools over weeks: the room-to-coil gap today, lately and usually.
    var health: HealthInfo?
    /// Electricity: power now, kWh today and this month, and kWh for each of the last 24 hours.
    var powerW: Int?
    var todayKWh: Double = 0
    var monthKWh: Double = 0
    var hourlyKWh: [Double] = []
    /// Naira per kWh, 0 when not set.
    var pricePerKWh: Double = 0
    var restoreAfterOutage = false
    /// Something to tell the user once, like the power coming back: kind and text.
    /// The latest few, oldest first; each new id gets one notification.
    var events: [ACEvent] = []
    /// Minutes left while the coil dries before switching off, or nil.
    var dryingMinutesLeft: Int?
    /// The user's choices kept by the helper.
    var dryCoil = false
    var min: Double = 16
    var max: Double = 30
    var modes: [String] = []
    var fans: [String] = []
    var swings: [String] = []
    var hasEco = false
    var hasTurbo = false
    var hasDisplay = false
    var hasFlash = false
    var timerChoices: [Int] = []
    /// Minutes until the off timer turns the AC off, or nil.
    var offIn: Int?
    /// A message from the helper, shown once per id.
    var notice = ""
    var noticeId = 0

    enum CodingKeys: String, CodingKey {
        case status, power, mode, target, indoor, outdoor, fan, swing, eco, turbo, sleep, flash, display, cleaning
        case cleaningMinutes = "cleaning_minutes"
        case effort, phase, coil, fault
        case compressorHz = "compressor_hz"
        case filterDue = "filter_due"
        case purifier
        case breezeAway = "breeze_away"
        case louverV = "louver_v"
        case louverH = "louver_h"
        case fanPercent = "fan_percent"
        case hasPurifier = "has_purifier"
        case hasBreezeAway = "has_breeze_away"
        case hasLouverV = "has_louver_v"
        case hasLouverH = "has_louver_h"
        case hasFanPercent = "has_fan_percent"
        case hasSelfClean = "has_self_clean"
        case cleanHours = "clean_hours"
        case filterHours = "filter_hours"
        case cleanAfterHours = "clean_after_hours"
        case filterAfterHours = "filter_after_hours"
        case schedules
        case sleepCurve = "sleep_curve"
        case sleepCurveChoices = "sleep_curve_choices"
        case health
        case powerW = "power_w"
        case todayKWh = "today_kwh"
        case monthKWh = "month_kwh"
        case hourlyKWh = "hourly_kwh"
        case dryingMinutesLeft = "drying_minutes_left"
        case settings
        case events
        case min, max, modes, fans, swings
        case hasEco = "has_eco"
        case hasTurbo = "has_turbo"
        case hasDisplay = "has_display"
        case hasFlash = "has_flash"
        case timerChoices = "timer_choices"
        case offIn = "off_in"
        case notice
        case noticeId = "notice_id"
    }

    /// Every field but the status is optional: an offline or unlinked AC sends only that.
    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        func value<T: Decodable>(_ key: CodingKeys, _ fallback: T) -> T { (try? c.decode(T.self, forKey: key)) ?? fallback }
        status = value(.status, Status.offline)
        power = value(.power, false)
        mode = try? c.decode(String.self, forKey: .mode)
        target = try? c.decode(Double.self, forKey: .target)
        indoor = try? c.decode(Double.self, forKey: .indoor)
        outdoor = try? c.decode(Double.self, forKey: .outdoor)
        fan = try? c.decode(String.self, forKey: .fan)
        swing = try? c.decode(String.self, forKey: .swing)
        eco = value(.eco, false)
        turbo = value(.turbo, false)
        sleep = value(.sleep, false)
        flash = value(.flash, false)
        display = value(.display, false)
        cleaning = value(.cleaning, false)
        cleaningMinutes = try? c.decode(Int.self, forKey: .cleaningMinutes)
        effort = value(.effort, 0.0)
        phase = value(.phase, "off")
        compressorHz = try? c.decode(Int.self, forKey: .compressorHz)
        coil = try? c.decode(Double.self, forKey: .coil)
        fault = try? c.decode(Int.self, forKey: .fault)
        filterDue = value(.filterDue, false)
        purifier = value(.purifier, false)
        breezeAway = value(.breezeAway, false)
        louverV = try? c.decode(String.self, forKey: .louverV)
        louverH = try? c.decode(String.self, forKey: .louverH)
        fanPercent = try? c.decode(Int.self, forKey: .fanPercent)
        hasPurifier = value(.hasPurifier, false)
        hasBreezeAway = value(.hasBreezeAway, false)
        hasLouverV = value(.hasLouverV, false)
        hasLouverH = value(.hasLouverH, false)
        hasFanPercent = value(.hasFanPercent, false)
        hasSelfClean = value(.hasSelfClean, false)
        cleanHours = value(.cleanHours, 0.0)
        filterHours = value(.filterHours, 0.0)
        cleanAfterHours = value(.cleanAfterHours, 40.0)
        filterAfterHours = value(.filterAfterHours, 150.0)
        schedules = c.contains(.schedules) ? try? c.decode([ACSchedule].self, forKey: .schedules) : []
        sleepCurve = try? c.decode(SleepCurveInfo.self, forKey: .sleepCurve)
        sleepCurveChoices = value(.sleepCurveChoices, [Int]())
        health = try? c.decode(HealthInfo.self, forKey: .health)
        dryingMinutesLeft = try? c.decode(Int.self, forKey: .dryingMinutesLeft)
        let settings = (try? c.decode(Settings.self, forKey: .settings)) ?? Settings()
        dryCoil = settings.dryCoil
        pricePerKWh = settings.price
        restoreAfterOutage = settings.restore
        autoClean = settings.autoClean
        sleepCurveEnd = settings.sleepCurveEnd
        events = value(.events, [ACEvent]())
        powerW = try? c.decode(Int.self, forKey: .powerW)
        todayKWh = value(.todayKWh, 0.0)
        monthKWh = value(.monthKWh, 0.0)
        hourlyKWh = value(.hourlyKWh, [Double]())
        min = value(.min, 16.0)
        max = value(.max, 30.0)
        modes = value(.modes, [String]())
        fans = value(.fans, [String]())
        swings = value(.swings, [String]())
        hasEco = value(.hasEco, false)
        hasTurbo = value(.hasTurbo, false)
        hasDisplay = value(.hasDisplay, false)
        hasFlash = value(.hasFlash, false)
        timerChoices = value(.timerChoices, [Int]())
        offIn = try? c.decode(Int.self, forKey: .offIn)
        notice = value(.notice, "")
        noticeId = value(.noticeId, 0)
    }

    var isOnline: Bool { status == .online }

    /// The user's choices, as the helper keeps them.
    private struct Settings: Decodable {
        var dryCoil = false
        var price = 0.0
        var restore = false
        var autoClean = false
        var sleepCurveEnd = "restore"
        enum CodingKeys: String, CodingKey {
            case dryCoil = "dry_coil"
            case price = "price_per_kwh"
            case restore = "restore_after_outage"
            case autoClean = "auto_clean"
            case sleepCurveEnd = "sleep_curve_end"
        }
        init() {}
        init(from decoder: Decoder) throws {
            let c = try decoder.container(keyedBy: CodingKeys.self)
            dryCoil = (try? c.decode(Bool.self, forKey: .dryCoil)) ?? false
            price = (try? c.decode(Double.self, forKey: .price)) ?? 0
            restore = (try? c.decode(Bool.self, forKey: .restore)) ?? false
            autoClean = (try? c.decode(Bool.self, forKey: .autoClean)) ?? false
            sleepCurveEnd = (try? c.decode(String.self, forKey: .sleepCurveEnd)) ?? "restore"
        }
    }
}

/// One schedule: on (optionally to a temperature and mode) or off, at a time on chosen days.
struct ACSchedule: Codable, Equatable, Identifiable {
    var id: String
    var enabled = true
    /// 0 is Monday, as the helper counts.
    var days: [Int]
    /// "HH:MM", the Mac's local time.
    var time: String
    var power: Bool
    var target: Double?
    var mode: String?
    var fan: String?
}

struct PhoneInfo: Decodable, Equatable {
    var enabled: Bool
    var running: Bool
    var url: String?
}

struct ACEvent: Decodable, Equatable {
    var id: Int
    var kind: String
    var text: String
}

struct HealthInfo: Decodable, Equatable {
    var gap: Double?
    var recent: Double?
    var usual: Double?
    /// learning, good or low.
    var state: String
    /// What to tell the user while low, from the helper.
    var message: String?
}

struct SleepCurveInfo: Decodable, Equatable {
    /// Degrees above the starting setting right now.
    var offset: Double
    /// "HH:MM" the curve ends.
    var endsAt: String
    var minutesLeft: Int
    enum CodingKeys: String, CodingKey {
        case offset
        case endsAt = "ends_at"
        case minutesLeft = "minutes_left"
    }
}

private struct Envelope: Decodable {
    let type: String
    let message: String?
    /// The request an error answers, like "ac_schedules".
    let `for`: String?
}

/// WebSocket link to the helper. Publishes the AC state and short messages for the user.
@MainActor
final class ACClient: ObservableObject {
    static let toastSeconds: UInt64 = 4
    private static let firstRetry: UInt64 = 500_000_000
    private static let maxRetry: UInt64 = 8_000_000_000

    /// Nil until the helper reports.
    @Published private(set) var ac: ACState?
    /// Called once for each new event from the helper (kind, text), for a notification.
    var onEvent: ((String, String) -> Void)?
    @Published private(set) var linkUp = false
    @Published var toast: String?
    /// Counts the helper refusing a list of schedules, so an open editor keeps the edits.
    @Published private(set) var schedulesRefused = 0
    /// The phone remote, as the helper reports it to the Mac (never to phones: the url holds the token).
    @Published private(set) var phone: PhoneInfo?
    /// A breeze:// link waiting for the user's yes in the panel.
    @Published var linkRequest: LinkRequest? {
        didSet {
            // Gone from the panel once too old to be applied.
            linkExpiry?.cancel()
            guard let request = linkRequest else { return }
            linkExpiry = Task { [weak self] in
                try? await Task.sleep(for: .seconds(URLRouter.staleSeconds))
                if !Task.isCancelled, self?.linkRequest == request { self?.linkRequest = nil }
            }
        }
    }
    private var linkExpiry: Task<Void, Never>?

    /// Called when the link drops, before reconnecting. Lets the app restart the helper.
    var onLinkLost: (() async -> Void)?

    private let token: String
    private var task: URLSessionWebSocketTask?
    private var toastClear: Task<Void, Never>?
    private var retryDelay = ACClient.firstRetry

    init(token: String) {
        self.token = token
    }

    func connect() {
        var request = URLRequest(url: URL(string: "ws://127.0.0.1:\(Helper.port)/ws")!)
        // The helper refuses other origins (web pages) and requests without our launch token.
        request.setValue(Helper.baseURL.absoluteString, forHTTPHeaderField: "Origin")
        request.setValue(token, forHTTPHeaderField: Helper.tokenHeader)
        let task = URLSession.shared.webSocketTask(with: request)
        self.task = task
        task.resume()
        Task { await receive(on: task) }
    }

    private func receive(on task: URLSessionWebSocketTask) async {
        while true {
            let message: URLSessionWebSocketTask.Message
            do {
                message = try await task.receive()
            } catch {
                guard task === self.task else { return }
                await linkLost()
                return
            }
            guard case .string(let text) = message, let data = text.data(using: .utf8) else { continue }
            linkUp = true
            retryDelay = Self.firstRetry
            handle(data)
        }
    }

    private func handle(_ data: Data) {
        guard let envelope = try? JSONDecoder().decode(Envelope.self, from: data) else { return }
        switch envelope.type {
        case "ac":
            if let next = try? JSONDecoder().decode(ACState.self, from: data) {
                if !next.notice.isEmpty, next.noticeId != ac?.noticeId { show(next.notice) }
                // The first message after connecting carries the last event; only newer ones notify.
                if let old = ac {
                    let seen = old.events.last?.id ?? 0
                    for event in next.events where event.id > seen { onEvent?(event.kind, event.text) }
                }
                ac = next
            }
        case "phone":
            phone = try? JSONDecoder().decode(PhoneInfo.self, from: data)
        case "error":
            if let text = envelope.message { show(text) }
            if envelope.for == "ac_schedules" { schedulesRefused += 1 }
        default:
            break
        }
    }

    private func linkLost() async {
        linkUp = false
        ac = nil
        await onLinkLost?()
        try? await Task.sleep(nanoseconds: retryDelay)
        retryDelay = min(retryDelay * 2, Self.maxRetry)
        connect()
    }

    func show(_ text: String) {
        toast = text
        toastClear?.cancel()
        toastClear = Task { [weak self] in
            try? await Task.sleep(nanoseconds: Self.toastSeconds * 1_000_000_000)
            if !Task.isCancelled { self?.toast = nil }
        }
    }

    // MARK: commands

    func refreshAC() { send(["type": "ac_get"]) }
    /// Change one or more settings, like ["target": 22] or ["power": false]. The helper checks each.
    func setAC(_ changes: [String: Any]) { send(["type": "ac_set", "changes": changes]) }
    func toggleACDisplay() { send(["type": "ac_display"]) }
    /// On again with the settings it had when last seen running.
    func restoreAC() { send(["type": "ac_restore"]) }
    func filterWashed() { send(["type": "ac_filter_cleaned"]) }
    /// The user said yes to the waiting link. A stale one is dropped, never applied late.
    func confirmLink() {
        guard let request = linkRequest else { return }
        linkRequest = nil
        guard Date().timeIntervalSince(request.arrived) <= URLRouter.staleSeconds else {
            show("That link waited too long. Open it again.")
            return
        }
        setAC(request.changes)
    }
    func refreshPhone() { send(["type": "ac_phone"]) }
    func setPhone(enabled: Bool) { send(["type": "ac_phone_set", "enabled": enabled]) }
    func resetPhone() { send(["type": "ac_phone_reset"]) }
    /// Start Breeze's sleep curve for `minutes`, or stop it with nil.
    func setSleepCurve(_ minutes: Int?) { send(["type": "ac_sleep_curve", "minutes": minutes as Any? ?? NSNull()]) }
    /// Replace the whole list of schedules; the helper checks each.
    func saveSchedules(_ entries: [ACSchedule]) {
        guard let data = try? JSONEncoder().encode(entries), let list = try? JSONSerialization.jsonObject(with: data) else { return }
        send(["type": "ac_schedules", "entries": list])
    }
    /// One of the user's choices the helper keeps, like "dry_coil".
    func setSetting(_ name: String, _ value: Any) { send(["type": "ac_setting", "name": name, "value": value]) }
    /// Turn the AC off after `minutes`, or cancel the timer with nil.
    func setOffTimer(_ minutes: Int?) { send(["type": "ac_timer", "minutes": minutes as Any? ?? NSNull()]) }

    private func send(_ payload: [String: Any]) {
        guard let task, linkUp,
              let data = try? JSONSerialization.data(withJSONObject: payload),
              let text = String(data: data, encoding: .utf8) else {
            show("Breeze is still starting. Try again in a moment.")
            return
        }
        task.send(.string(text)) { [weak self] error in
            guard error != nil else { return }
            // A failed send means the socket is dead; cancelling makes receive() fail and reconnect.
            Task { @MainActor in
                guard let self, task === self.task else { return }
                task.cancel(with: .goingAway, reason: nil)
            }
        }
    }
}
