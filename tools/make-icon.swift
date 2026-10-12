// Draws the Breeze app icon (an air conditioner blowing cool air on a night blue tile).
// Usage: swift make-icon.swift <output.iconset>
import AppKit

let out = URL(fileURLWithPath: CommandLine.arguments[1])
try FileManager.default.createDirectory(at: out, withIntermediateDirectories: true)

func draw(size: CGFloat) -> Data {
    let rep = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: Int(size), pixelsHigh: Int(size),
                               bitsPerSample: 8, samplesPerPixel: 4, hasAlpha: true, isPlanar: false,
                               colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0)!
    NSGraphicsContext.saveGraphicsState()
    NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep: rep)
    let s = size / 1024

    // Tile, inset like system icons.
    let tile = NSBezierPath(roundedRect: NSRect(x: 100 * s, y: 100 * s, width: 824 * s, height: 824 * s),
                            xRadius: 185 * s, yRadius: 185 * s)
    NSGradient(colors: [NSColor(red: 0.18, green: 0.30, blue: 0.56, alpha: 1),
                        NSColor(red: 0.05, green: 0.09, blue: 0.21, alpha: 1)])!.draw(in: tile, angle: -90)

    // Indoor unit.
    let shadow = NSShadow()
    shadow.shadowColor = NSColor.black.withAlphaComponent(0.35)
    shadow.shadowBlurRadius = 30 * s
    shadow.shadowOffset = NSSize(width: 0, height: -14 * s)
    shadow.set()
    let unit = NSRect(x: 230 * s, y: 560 * s, width: 564 * s, height: 180 * s)
    NSGradient(colors: [.white, NSColor(white: 0.86, alpha: 1)])!.draw(
        in: NSBezierPath(roundedRect: unit, xRadius: 44 * s, yRadius: 44 * s), angle: -90)
    NSShadow().set()
    NSColor(white: 0.55, alpha: 1).setFill()
    NSBezierPath(roundedRect: NSRect(x: 280 * s, y: 588 * s, width: 464 * s, height: 16 * s), xRadius: 8 * s, yRadius: 8 * s).fill()
    NSColor(red: 0.35, green: 0.58, blue: 1, alpha: 1).setFill()
    NSBezierPath(ovalIn: NSRect(x: 718 * s, y: 690 * s, width: 22 * s, height: 22 * s)).fill()

    // Cool air.
    for index in 0..<5 {
        let offset = CGFloat(index - 2)
        let path = NSBezierPath()
        path.move(to: NSPoint(x: 512 * s + offset * 70 * s, y: 540 * s))
        path.curve(to: NSPoint(x: 512 * s + offset * 120 * s, y: 250 * s),
                   controlPoint1: NSPoint(x: 512 * s + offset * 80 * s, y: 430 * s),
                   controlPoint2: NSPoint(x: 512 * s + offset * 110 * s, y: 330 * s))
        path.lineWidth = 26 * s
        path.lineCapStyle = .round
        NSColor(red: 0.55, green: 0.75, blue: 1, alpha: 0.85 - 0.1 * abs(Double(offset))).setStroke()
        path.stroke()
    }

    NSGraphicsContext.restoreGraphicsState()
    return rep.representation(using: .png, properties: [:])!
}

for (name, px) in [("16x16", 16), ("16x16@2x", 32), ("32x32", 32), ("32x32@2x", 64), ("128x128", 128),
                   ("128x128@2x", 256), ("256x256", 256), ("256x256@2x", 512), ("512x512", 512), ("512x512@2x", 1024)] {
    try draw(size: CGFloat(px)).write(to: out.appendingPathComponent("icon_\(name).png"))
}
