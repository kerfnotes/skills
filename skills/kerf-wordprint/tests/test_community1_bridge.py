"""Offline native timeline/serialization checks; no model loading or downloads."""
from pathlib import Path
import platform
import shutil
import subprocess
import tempfile
import unittest

BRIDGE = Path(__file__).parents[1] / "scripts/community1-bridge"

HARNESS = r'''import Foundation
import AudioCommon

@main
struct TimelineChecks {
    static func main() throws {
        let name = CommandLine.arguments[1]
        let duration = 58894.0 / 16000.0
        func timeline(_ binary: [[Float]], _ duration: Float) throws -> [DiarizedSegment] {
            try Community1DiarizationPipeline.toSegments(binary, sourceDuration: duration)
        }
        func rejected(_ start: Float, _ end: Float, _ duration: Double = 1,
                      _ speaker: Int = 0) {
            do {
                _ = try validatedSegment(start: start, end: end, speaker: speaker,
                                         sourceDuration: duration)
                fatalError("accepted invalid interval: \(start), \(end), \(duration)")
            } catch { }
        }
        switch name {
        case "crossing":
            // Original short fixture: speech at frames 0...219, transition 220.
            let binary = (0..<594).map { [Float($0 < 220 ? 1 : 0)] }
            let result = try timeline(binary, Float(duration))
            precondition(result.count == 1 && result[0].speakerId == 0)
            precondition(result[0].startTime == Community1Config.frameDuration / 2)
            guard result[0].endTime == Float(duration) else {
                FileHandle.standardError.write(Data("Crossing turn exceeds original PCM duration\n".utf8))
                exit(1)
            }
            let segment = try validatedSegment(start: result[0].startTime,
                end: result[0].endTime, speaker: result[0].speakerId, sourceDuration: duration)
            precondition(segment.end == duration && segment.duration > 0)
        case "padded_support":
            let binary = (0..<594).map { [Float($0 < 220 ? 1 : 0), Float($0 > 400 ? 1 : 0)] }
            let result = try timeline(binary, Float(duration))
            precondition(result.count == 1 && result[0].speakerId == 0)
            precondition(result[0].endTime == Float(duration))
        case "interior_unchanged":
            let binary = (0..<594).map { [Float((20..<60).contains($0) ? 1 : 0)] }
            let short = try timeline(binary, Float(duration))
            let long = try timeline(binary, 10)
            precondition(short.count == 1 && long.count == 1)
            precondition(short[0].startTime == long[0].startTime)
            precondition(short[0].endTime == long[0].endTime)
        case "overlap":
            let binary = (0..<594).map { [Float($0 < 220 ? 1 : 0), Float((100..<230).contains($0) ? 1 : 0)] }
            let result = try timeline(binary, Float(duration))
            precondition(result.count == 2 && Set(result.map(\.speakerId)) == Set([0, 1]))
            precondition(result.allSatisfy { $0.endTime == Float(duration) && $0.endTime > $0.startTime })
        case "boundaries":
            let binary = Array(repeating: [Float(1)], count: 594)
            for d: Float in [0.0000625, Community1Config.frameDuration / 2,
                              Community1Config.frameDuration / 2 + Community1Config.frameStep,
                              3.680875, 9.999, 10] {
                let segments = try timeline(binary, d)
                precondition(segments.allSatisfy { $0.startTime >= 0 && $0.startTime < $0.endTime && $0.endTime <= d })
            }
            let empty = try timeline([], 1)
            precondition(empty.isEmpty)
        case "float_endpoint":
            // Test both Float rounding directions and a 20-minute sample count.
            for d in [duration, 1.0000625, 1199.9999375] {
                let end = Float(d)
                let result = try validatedSegment(start: 0, end: end, speaker: 0, sourceDuration: d)
                precondition(result.end == d && result.duration == d)
                rejected(0, end.nextUp, d)
            }
        case "nonfinite":
            for bad: Float in [.nan, .infinity, -.infinity] {
                rejected(bad, 1); rejected(0, bad)
            }
            for bad: Double in [.nan, .infinity, -.infinity, 0, -1] { rejected(0, 1, bad) }
        case "invalid_intervals":
            rejected(-0.001, 1); rejected(0.5, 0.5); rejected(0.6, 0.5)
            rejected(1, 1.001); rejected(1.001, 1.002); rejected(0, 1.001)
            rejected(0, 1, 1, -1); rejected(0, 3.743468761, duration)
            let valid = try validatedSegment(start: 0.25, end: 0.75, speaker: 2, sourceDuration: 1)
            precondition(valid.start == 0.25 && valid.end == 0.75 && valid.duration == 0.5 && valid.speaker == 2)
        case "invalid_duration":
            for bad: Float in [.nan, .infinity, -.infinity, 0, -1] {
                do { _ = try timeline([[1], [0]], bad); fatalError("accepted bad source duration") }
                catch { }
            }
        default: fatalError("unknown check")
        }
        print("PASS " + name)
    }
}
'''

@unittest.skipUnless(platform.system() == "Darwin" and shutil.which("xcrun"), "requires macOS Swift")
class Community1TimelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="wordprint-timeline-")
        cls.addClassCleanup(cls.temp.cleanup)
        root = Path(cls.temp.name)
        (root / "checks.swift").write_text(HARNESS)
        # Compile the production timeline and boundary validator, not a Python reimplementation.
        common = ["xcrun", "swiftc", "-module-name", "AudioCommon", "-emit-library",
                  "-static", "-emit-module", "-emit-module-path", str(root / "AudioCommon.swiftmodule"),
                  "-o", str(root / "libAudioCommon.a")]
        common += [str(p) for p in sorted((BRIDGE / "Sources/AudioCommon").glob("*.swift"))]
        compiled = subprocess.run(common, capture_output=True, text=True)
        if compiled.returncode:
            raise AssertionError(compiled.stdout + compiled.stderr)
        command = ["xcrun", "swiftc", "-parse-as-library", "-I", str(root),
                   "-L", str(root), "-lAudioCommon"]
        command += [str(p) for p in sorted((BRIDGE / "Sources/SpeechVAD").glob("*.swift"))]
        command += [str(BRIDGE / "Sources/Community1Bridge/ResultValidation.swift"),
                    str(root / "checks.swift"), "-o", str(root / "checks")]
        compiled = subprocess.run(command, capture_output=True, text=True)
        if compiled.returncode:
            raise AssertionError(compiled.stdout + compiled.stderr)
        cls.executable = root / "checks"

    def check(self, name):
        result = subprocess.run([str(self.executable), name], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stdout.strip(), "PASS " + name)

    def test_crossing_turn_preserves_source_speech(self): self.check("crossing")
    def test_model_padding_cannot_create_source_turns(self): self.check("padded_support")
    def test_interior_success_is_unchanged(self): self.check("interior_unchanged")
    def test_overlapping_speakers_both_survive_clipping(self): self.check("overlap")
    def test_exact_frame_and_subframe_boundaries(self): self.check("boundaries")
    def test_only_same_float_endpoint_is_restored(self): self.check("float_endpoint")
    def test_nonfinite_times_are_rejected(self): self.check("nonfinite")
    def test_invalid_intervals_are_rejected(self): self.check("invalid_intervals")
    def test_invalid_timeline_duration_is_rejected(self): self.check("invalid_duration")

if __name__ == "__main__":
    unittest.main()
