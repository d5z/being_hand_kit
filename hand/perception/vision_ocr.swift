import Vision
import AppKit
import Foundation

extension FileHandle: @retroactive TextOutputStream {
    public func write(_ string: String) {
        guard let data = string.data(using: .utf8) else { return }
        self.write(data)
    }
}

guard CommandLine.arguments.count > 1 else {
    var stderr = FileHandle.standardError
    print("usage: vision_ocr_bin <image_path>", to: &stderr)
    exit(1)
}

let imagePath = CommandLine.arguments[1]
guard let image = NSImage(contentsOfFile: imagePath) else {
    var stderr = FileHandle.standardError
    print("failed to load image: \(imagePath)", to: &stderr)
    exit(1)
}

guard let cgImage = image.cgImage(forProposedRect: nil, context: nil, hints: nil) else {
    var stderr = FileHandle.standardError
    print("failed to get cgImage", to: &stderr)
    exit(1)
}

let request = VNRecognizeTextRequest()
request.recognitionLevel = .accurate
request.recognitionLanguages = ["zh-Hans", "zh-Hant", "en", "ja"]
request.usesLanguageCorrection = true

let handler = VNImageRequestHandler(cgImage: cgImage, options: [:])
do {
    try handler.perform([request])
    guard let observations = request.results else {
        exit(0)
    }
    let imageWidth = CGFloat(cgImage.width)
    let imageHeight = CGFloat(cgImage.height)
    for observation in observations {
        guard let top = observation.topCandidates(1).first else { continue }
        let confidence = top.confidence
        let text = top.string
        let box = observation.boundingBox
        let x = Int(box.origin.x * imageWidth)
        let y = Int((1 - box.origin.y - box.size.height) * imageHeight)
        let w = Int(box.size.width * imageWidth)
        let h = Int(box.size.height * imageHeight)
        print("\(confidence)\t\(x)\t\(y)\t\(w)\t\(h)\t\(text)")
    }
} catch {
    var stderr = FileHandle.standardError
    print("vision error: \(error)", to: &stderr)
    exit(1)
}
