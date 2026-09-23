"""Let RT64 pick a GBI for microcode it cannot hash-identify. Idempotent.

RT64 identifies the graphics microcode by hashing the ucode text and data in
RDRAM (lib/RT64/src/gbi/rt64_gbi.cpp, getGBIForUCode). A clean image carries
no Nintendo microcode, so the hash misses and RT64 returns no GBI. This adds

    extern "C" void RT64_SetUCodeOverride(uint32_t textAddress, const char *instanceName);

and, only when the hash lookup fails, uses the instance registered for that
(physical, 8-byte aligned) text address. Behaviour with retail bytes is
unchanged: a hash match always wins.

    python patches/rt64_ucode_override.py [path/to/pilotwings-64-recomp]
"""
import sys
from pathlib import Path

MARK = "n64cleanrecomp ucode override"

DECL_ANCHOR = "    GBI *GBIManager::getGBIForUCode(uint8_t *RDRAM, uint32_t textAddress, uint32_t dataAddress) {"
DECL = f"""    // [{MARK}] microcode that cannot be hash-identified (clean images carry
    // none of Nintendo's) is mapped to a GBI instance by its text address.
    static std::unordered_map<uint32_t, std::string> ucodeOverrides;

    static const GBIInstance *findInstanceByName(const std::string &name) {{
        for (const GBISegment &segment : textSegments) {{
            for (const GBIInstance *instance : segment.instances) {{
                if (name == instance->name) {{
                    return instance;
                }}
            }}
        }}
        return nullptr;
    }}

"""

MISS_OLD = """        if (textSegmentIndex < 0 || dataSegmentIndex < 0) {
            fprintf(stderr, "Unable to find a matching GBI in the current database. This game is not supported in HLE.\\n");
            deduceGBIInformation(RDRAM, textAddress, dataAddress);
            return nullptr;
        }

        // Search for the first intersection available between both segments.
        const GBISegment &textSegment = textSegments[textSegmentIndex];
        const GBISegment &dataSegment = dataSegments[dataSegmentIndex];
        const GBIInstance *matchingInstance = nullptr;
        for (const GBIInstance *textInstance : textSegment.instances) {
            for (const GBIInstance *dataInstance : dataSegment.instances) {
                if (textInstance == dataInstance) {
                    matchingInstance = dataInstance;
                    break;
                }
            }
        }

        if (matchingInstance == nullptr) {
            fprintf(stderr, "Unable to find a GBI that is shared between the text and data segment. Is the GBI database configured incorrectly?\\n");
            return nullptr;
        }"""

MISS_NEW = f"""        const GBIInstance *matchingInstance = nullptr;
        if (textSegmentIndex >= 0 && dataSegmentIndex >= 0) {{
            // Search for the first intersection available between both segments.
            const GBISegment &textSegment = textSegments[textSegmentIndex];
            const GBISegment &dataSegment = dataSegments[dataSegmentIndex];
            for (const GBIInstance *textInstance : textSegment.instances) {{
                for (const GBIInstance *dataInstance : dataSegment.instances) {{
                    if (textInstance == dataInstance) {{
                        matchingInstance = dataInstance;
                        break;
                    }}
                }}
            }}
        }}

        // [{MARK}]
        if (matchingInstance == nullptr) {{
            auto it = ucodeOverrides.find(textAddress);
            if (it != ucodeOverrides.end()) {{
                matchingInstance = findInstanceByName(it->second);
                if (matchingInstance == nullptr) {{
                    fprintf(stderr, "ucode override names an unknown GBI instance: %s\\n", it->second.c_str());
                }}
            }}
        }}

        if (matchingInstance == nullptr) {{
            fprintf(stderr, "Unable to find a matching GBI in the current database. This game is not supported in HLE.\\n");
            deduceGBIInformation(RDRAM, textAddress, dataAddress);
            return nullptr;
        }}"""

TAIL = f"""
// [{MARK}]
extern "C" void RT64_SetUCodeOverride(uint32_t textAddress, const char *instanceName) {{
    RT64::ucodeOverrides[textAddress & 0xFFFFF8] = instanceName;
}}
"""


def main(argv):
    root = Path(argv[1]) if len(argv) > 1 else Path(__file__).resolve().parents[1] / "external" / "pilotwings-64-recomp"
    p = root / "lib" / "RT64" / "src" / "gbi" / "rt64_gbi.cpp"
    s = p.read_bytes().decode("utf-8")
    if MARK in s:
        print(f"{p}: already patched")
        return
    crlf = "\r\n" in s
    s = s.replace("\r\n", "\n")
    for old, new in ((DECL_ANCHOR, DECL + DECL_ANCHOR), (MISS_OLD, MISS_NEW)):
        if s.count(old) != 1:
            raise SystemExit(f"{p}: anchor not found exactly once:\n{old[:200]}")
        s = s.replace(old, new)
    if "#include <unordered_map>" not in s:
        s = "#include <unordered_map>\n#include <string>\n" + s
    s = s.rstrip("\n") + "\n" + TAIL
    if crlf:
        s = s.replace("\n", "\r\n")
    p.write_bytes(s.encode("utf-8"))
    print(f"{p}: patched")


if __name__ == "__main__":
    main(sys.argv)
