import CoreImage.CIFilterBuiltins
import SwiftUI

/// Phone Remote: turn it on and show the QR code that pairs a phone. The code holds the
/// pairing token, so it is drawn here only, never saved or sent anywhere.
struct PhoneView: View {
    @ObservedObject var client: ACClient
    @State private var confirmForget = false

    private static let port = 8768  // PHONE_PORT in phone.py

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            Text("Phone Remote").font(.headline)
            Toggle("Use Breeze from my phone", isOn: Binding(
                get: { client.phone?.enabled ?? false },
                set: { client.setPhone(enabled: $0) }))
                .toggleStyle(.switch)

            if let phone = client.phone, phone.enabled {
                if let url = phone.url {
                    if let image = Self.qrCode(for: url) {
                    HStack(alignment: .top, spacing: 16) {
                        Image(nsImage: image)
                            .interpolation(.none)
                            .resizable()
                            .frame(width: 150, height: 150)
                            .padding(8)
                            .background(RoundedRectangle(cornerRadius: 12).fill(.white))
                            .accessibilityLabel("QR code that pairs a phone")
                        VStack(alignment: .leading, spacing: 8) {
                            step(1, "Point the phone camera at the code and open the link.")
                            step(2, "Tap Share, then Add to Home Screen.")
                            step(3, "Open Breeze from the home screen any time.")
                        }
                        .font(.callout)
                    }
                    } else {
                        Text("Breeze could not draw the code. Turn the phone remote off and on again.")
                            .font(.callout).foregroundStyle(.orange)
                    }
                    Text("The phone must be on the same Wi-Fi, and this Mac awake with Breeze running. If macOS asks whether to accept incoming connections, choose Allow.")
                        .font(.caption).foregroundStyle(.secondary)
                        .fixedSize(horizontal: false, vertical: true)
                } else if !phone.running {
                    Text("The phone remote could not start. Another app may be using port \(Self.port).")
                        .font(.callout).foregroundStyle(.orange)
                } else {
                    Text("This Mac has no Wi-Fi address right now.").font(.callout).foregroundStyle(.orange)
                }
                // Asked twice, in place: no dialog over the panel.
                if confirmForget {
                    HStack {
                        Text("Phones will need a new scan.").font(.callout)
                        Spacer()
                        Button("Keep") { confirmForget = false }
                        Button("Forget Phones") {
                            client.resetPhone()
                            confirmForget = false
                        }
                    }
                } else {
                    Button("Forget Paired Phones") { confirmForget = true }
                }
            } else {
                Text("Turn this on for the everyday controls on your phone: power, temperature, mode, fan, Eco, Turbo, Sleep and the timer.")
                    .font(.callout).foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
        .padding(14)
        .frame(width: 400)
        .onAppear { client.refreshPhone() }
    }

    private func step(_ number: Int, _ text: String) -> some View {
        HStack(alignment: .firstTextBaseline, spacing: 8) {
            Text("\(number)").font(.callout.weight(.bold)).foregroundStyle(.secondary).monospacedDigit()
            Text(text).fixedSize(horizontal: false, vertical: true)
        }
    }

    private static func qrCode(for text: String) -> NSImage? {
        let filter = CIFilter.qrCodeGenerator()
        filter.message = Data(text.utf8)
        filter.correctionLevel = "M"
        guard let output = filter.outputImage else { return nil }
        let rep = NSCIImageRep(ciImage: output)
        let image = NSImage(size: rep.size)
        image.addRepresentation(rep)
        return image
    }
}
