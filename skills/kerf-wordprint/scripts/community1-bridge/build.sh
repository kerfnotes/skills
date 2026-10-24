#!/bin/sh
set -eu
bridge_root=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
mkdir -p "$bridge_root/build"
cd "$bridge_root"
xcrun swiftc -target arm64-apple-macosx14.0 -O -module-name AudioCommon -emit-library -static -emit-module \
  -emit-module-path build/AudioCommon.swiftmodule -o build/libAudioCommon.a Sources/AudioCommon/*.swift
xcrun swiftc -target arm64-apple-macosx14.0 -O -module-name SpeechVAD -emit-library -static -emit-module \
  -I build -L build -lAudioCommon -emit-module-path build/SpeechVAD.swiftmodule \
  -o build/libSpeechVAD.a Sources/SpeechVAD/*.swift
xcrun swiftc -target arm64-apple-macosx14.0 -O -parse-as-library -I build -L build \
  -lSpeechVAD -lAudioCommon Sources/Community1Bridge/*.swift -o build/community1-bridge
build/community1-bridge --self-test
