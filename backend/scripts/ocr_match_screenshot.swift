import Foundation
import ImageIO
import Vision

let path = CommandLine.arguments[1]
guard let source = CGImageSourceCreateWithURL(URL(fileURLWithPath: path) as CFURL, nil),
      let cgImage = CGImageSourceCreateImageAtIndex(source, 0, nil) else {
    fputs("Could not read image", stderr); exit(2)
}
let request = VNRecognizeTextRequest()
request.recognitionLevel = .accurate
request.usesLanguageCorrection = true
do {
    try VNImageRequestHandler(cgImage: cgImage).perform([request])
    for result in request.results ?? [] {
        if let text = result.topCandidates(1).first?.string { print(text) }
    }
} catch {
    fputs("OCR failed: \(error.localizedDescription)", stderr)
    exit(3)
}
