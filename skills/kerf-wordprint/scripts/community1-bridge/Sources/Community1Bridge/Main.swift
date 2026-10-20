import AudioCommon
import AVFoundation
import CoreML
import Foundation
import SpeechVAD

struct BridgeSegment: Encodable {
    let start: Double
    let end: Double
    let duration: Double
    let speaker: Int
}
struct BridgeResult: Encodable {
    let segments: [BridgeSegment]
    let num_speakers: Int
    let sample_count: Int
    let sample_rate: Int
    let model = "aufklarer/Pyannote-Community-1-CoreML"
    let backend = "speech-swift v0.0.27 fromLocal CoreML CPU"
}

@main
struct Community1Bridge {
    static func main() async {
        do {
            let args = Array(CommandLine.arguments.dropFirst())
            if args == ["--help"] {
                print("Usage: community1-bridge --audio canonical-mono-16k.wav --cache-dir existing-community1-bundle\n       community1-bridge --self-test")
                return
            }
            if args == ["--self-test"] {
                do {
                    try await HuggingFaceDownloader.downloadWeights(modelId: "test", to: URL(fileURLWithPath: "/tmp"))
                    throw NSError(domain: "Bridge", code: 1, userInfo: [NSLocalizedDescriptionKey: "Downloader unexpectedly returned"])
                } catch OfflineBridgeError.networkDisabled { }
                do {
                    _ = try HuggingFaceDownloader.getCacheDirectory(for: "test")
                    throw NSError(domain: "Bridge", code: 1, userInfo: [NSLocalizedDescriptionKey: "Downloader unexpectedly returned"])
                } catch OfflineBridgeError.networkDisabled { }
                print("Offline downloader guards passed; no models loaded.")
                return
            }
            guard args.count == 4, args[0] == "--audio", args[2] == "--cache-dir" else {
                throw NSError(domain: "Bridge", code: 2, userInfo: [NSLocalizedDescriptionKey: "Invalid arguments; use --help"])
            }
            let audioURL = URL(fileURLWithPath: args[1])
            let format = try AVAudioFile(forReading: audioURL).processingFormat
            guard format.channelCount == 1, format.sampleRate == 16_000 else {
                throw NSError(domain: "Bridge", code: 3, userInfo: [NSLocalizedDescriptionKey: "Expected canonical mono 16 kHz PCM WAV"])
            }
            let (samples, sampleRate) = try AudioFileLoader.loadWAV(url: audioURL)
            guard sampleRate == 16000, !samples.isEmpty, samples.allSatisfy(\.isFinite) else {
                throw NSError(domain: "Bridge", code: 4, userInfo: [NSLocalizedDescriptionKey: "Invalid PCM samples"])
            }
            setenv(CoreMLComputeUnitsResolver.envKey, "cpuOnly", 1)
            let pipeline = try Community1DiarizationPipeline.fromLocal(
                directory: URL(fileURLWithPath: args[3], isDirectory: true), computeUnits: .cpuOnly)
            let result = try pipeline.diarize(audio: samples, sampleRate: sampleRate,
                                              speakerBounds: .init(minimum: 1, maximum: 8))
            let duration = Double(samples.count) / Double(sampleRate)
            let segments = try result.segments.map { item -> BridgeSegment in
                let start = Double(item.startTime), end = Double(item.endTime)
                guard start.isFinite, end.isFinite, start >= 0, end > start,
                      end <= duration + 0.02, item.speakerId >= 0 else {
                    throw NSError(domain: "Bridge", code: 5, userInfo: [NSLocalizedDescriptionKey: "Invalid diarization result bounds"])
                }
                return BridgeSegment(start: start, end: min(end, duration),
                                     duration: min(end, duration) - start, speaker: item.speakerId)
            }
            let data = try JSONEncoder().encode(BridgeResult(segments: segments, num_speakers: result.numSpeakers,
                                                            sample_count: samples.count, sample_rate: sampleRate))
            FileHandle.standardOutput.write(data)
            FileHandle.standardOutput.write(Data([10]))
        } catch {
            FileHandle.standardError.write(Data(("\(error.localizedDescription)\n").utf8))
            exit(1)
        }
    }
}
