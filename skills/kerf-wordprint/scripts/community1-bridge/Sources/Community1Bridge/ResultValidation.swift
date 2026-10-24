import Foundation

struct BridgeSegment: Encodable {
    let start: Double
    let end: Double
    let duration: Double
    let speaker: Int
}

/// Accept only source-domain times. The pipeline stores times as Float, so the
/// exact PCM endpoint can round either way. Recognize that one representation
/// and restore the original Double sample clock; no millisecond grace period.
func validatedSegment(start: Float, end: Float, speaker: Int,
                      sourceDuration: Double) throws -> BridgeSegment {
    let representedEnd = Float(sourceDuration)
    let exactEnd = end == representedEnd ? sourceDuration : Double(end)
    guard sourceDuration.isFinite, sourceDuration > 0, representedEnd.isFinite,
          start.isFinite, end.isFinite, start >= 0, end > start,
          Double(start) < sourceDuration, exactEnd > Double(start),
          exactEnd <= sourceDuration, speaker >= 0 else {
        throw NSError(domain: "Bridge", code: 5,
                      userInfo: [NSLocalizedDescriptionKey: "Invalid diarization result bounds"])
    }
    return BridgeSegment(start: Double(start), end: exactEnd,
                         duration: exactEnd - Double(start), speaker: speaker)
}
