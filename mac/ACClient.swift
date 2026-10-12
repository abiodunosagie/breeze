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
    var filterWashDue = false
    var autoClean = false
    /// Electricity: power now, kWh today and this month, and kWh for each of the last 24 hours.
    var powerW: Int?
    var todayKWh: Double = 0
    var monthKWh: Double = 0
    var hourlyKWh: [Double] = []
    /// Naira per kWh, 0 when not set.
    var pricePerKWh: Double = 0
    var restoreAfterOutage = false
    /// Something to tell the user once, like the power coming back: kind and text.
    var eventKind: String?
    var eventText: String?
    var eventId = 0
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
        case filterWashDue = "filter_wash_due"
        case powerW = "power_w"
        case todayKWh = "today_kwh"
        case monthKWh = "month_kwh"
        case hourlyKWh = "hourly_kwh"
        case dryingMinutesLeft = "drying_minutes_left"
        case settings
        case event
        case eventId = "event_id"
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
        filterWashDue = value(.filterWashDue, false)
        dryingMinutesLeft = try? c.decode(Int.self, forKey: .dryingMinutesLeft)
        let settings = (try? c.decode(Settings.self, forKey: .settings)) ?? Settings()
        dryCoil = settings.dryCoil
        pricePerKWh = settings.price
        restoreAfterOutage = settings.restore
        autoClean = settings.autoClean
        let event = try? c.decode([String: String].self, forKey: .event)
        eventKind = event?["kind"]
        eventText = event?["text"]
        eventId = value(.eventId, 0)
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
        enum CodingKeys: String, CodingKey {
            case dryCoil = "dry_coil"
            case price = "price_per_kwh"
            case restore = "restore_after_outage"
            case autoClean = "auto_clean"
        }
        init() {}
        init(from decoder: Decoder) throws {
            let c = try decoder.container(keyedBy: CodingKeys.self)
            dryCoil = (try? c.decode(Bool.self, forKey: .dryCoil)) ?? false
            price = (try? c.decode(Double.self, forKey: .price)) ?? 0
            restore = (try? c.decode(Bool.self, forKey: .restore)) ?? false
            autoClean = (try? c.decode(Bool.self, forKey: .autoClean)) ?? false
        }
    }
}

private struct Envelope: Decodable {
    let type: String
    let message: String?
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
                if let old = ac, next.eventId != old.eventId, let kind = next.eventKind, let text = next.eventText {
                    onEvent?(kind, text)
                }
                ac = next
            }
        case "error":
            if let text = envelope.message { show(text) }
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
