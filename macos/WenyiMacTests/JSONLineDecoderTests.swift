import Foundation
import Testing
@testable import WenyiMac

struct JSONLineDecoderTests {
    @Test func preservesPartialLinesAcrossPipeReads() {
        var decoder = JSONLineDecoder()
        #expect(decoder.append(Data("{\"type\":\"pro".utf8)).isEmpty)
        let lines = decoder.append(Data("gress\"}\n{\"type\":\"done\"}\n".utf8))
        #expect(lines.map { String(decoding: $0, as: UTF8.self) } == ["{\"type\":\"progress\"}", "{\"type\":\"done\"}"])
    }
}
