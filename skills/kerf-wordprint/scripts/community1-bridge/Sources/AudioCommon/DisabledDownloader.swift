import Foundation

// This bridge calls fromLocal; SDK download entry points are unavailable here.
public enum HuggingFaceDownloader {
    public static func getCacheDirectory(for modelId: String) throws -> URL {
        throw OfflineBridgeError.networkDisabled
    }
    public static func downloadWeights(modelId: String, to directory: URL,
                                       additionalFiles: [String] = [], offlineMode: Bool = false,
                                       progressHandler: ((Double) -> Void)? = nil) async throws {
        throw OfflineBridgeError.networkDisabled
    }
}

public enum OfflineBridgeError: Error { case networkDisabled }
