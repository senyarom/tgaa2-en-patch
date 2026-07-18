#!/usr/bin/env bash

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROJECT_ROOT="$(cd "$REPO_ROOT/../.." && pwd)"
GAME="${1:-tgaa2}"
HOOK_SOURCE="$REPO_ROOT/native/hooks/court_record_hook.c"
HOOK_LINKER_SCRIPT="$REPO_ROOT/native/hooks/court_record_hook.ld"

case "$GAME" in
    tgaa1)
        SOURCE_BUILD="${SOURCE_BUILD:-$PROJECT_ROOT/work/private/tgaa1-dialogue-pagination/build-v286}"
        OUTPUT_DIR="${2:-$PROJECT_ROOT/work/private/tgaa1-hook-build}"
        CALL_SITE=0x00256E08
        # The final 0xC88 bytes of TGAA1's executable text segment are empty.
        # Do not use the tempting padding at 0x0056EA70: it belongs to the
        # read-only segment and causes a Permission Page prefetch abort on 3DS.
        HOOK_ADDRESS=0x0052D378
        CODE_CAVE_END=0x0052E000
        ORIGINAL_SET_COURT_RECORD_DETAIL=0x00258F48
        EXPECTED_CALL="4e 08 00 eb"
        HOOK_ISA=arm
        CIA_NAME="TGAA1-Official-English-v2.8.6-hook.cia"
        ;;
    tgaa2)
        SOURCE_BUILD="${SOURCE_BUILD:-$PROJECT_ROOT/work/private/tgaa2-court-record-fix/build-v233}"
        OUTPUT_DIR="${2:-$PROJECT_ROOT/work/private/tgaa2-hook-build}"
        CALL_SITE=0x0026FC84
        # TGAA2 only has 0x5C4 empty bytes at the executable text tail. The
        # compact Thumb payload fits there; the old 0x005BDA90 cave is RO.
        HOOK_ADDRESS=0x00569A3C
        CODE_CAVE_END=0x0056A000
        ORIGINAL_SET_COURT_RECORD_DETAIL=0x00271EF0
        EXPECTED_CALL="99 08 00 eb"
        HOOK_ISA=thumb
        CIA_NAME="DGS2-Official-English-v2.3.3-hook.cia"
        ;;
    *)
        echo "Usage: $0 [tgaa1|tgaa2] [output-dir]" >&2
        exit 2
        ;;
esac

IMAGE_BASE=0x00100000

TOOLCHAIN="/opt/devkitpro/devkitARM/bin"
CC="$TOOLCHAIN/arm-none-eabi-gcc"
OBJCOPY="$TOOLCHAIN/arm-none-eabi-objcopy"
OBJDUMP="$TOOLCHAIN/arm-none-eabi-objdump"
NM="$TOOLCHAIN/arm-none-eabi-nm"
MAKEROM="$PROJECT_ROOT/work/Project_CTR/makerom/bin/makerom"

for tool in "$CC" "$OBJCOPY" "$OBJDUMP" "$NM" "$MAKEROM"; do
    if [[ ! -x "$tool" ]]; then
        echo "Required tool was not found: $tool" >&2
        exit 1
    fi
done

for path in \
    "$SOURCE_BUILD/code.bin" \
    "$SOURCE_BUILD/exheader.bin" \
    "$SOURCE_BUILD/icon.bin" \
    "$SOURCE_BUILD/update.rsf" \
    "$SOURCE_BUILD/romfs"; do
    if [[ ! -e "$path" ]]; then
        echo "Required build input was not found: $path" >&2
        exit 1
    fi
done

mkdir -p "$OUTPUT_DIR"

HOOK_OBJECT="$OUTPUT_DIR/court-record-hook.o"
HOOK_ELF="$OUTPUT_DIR/court-record-hook.elf"
HOOK_BIN="$OUTPUT_DIR/court-record-hook.bin"
HOOK_MAP="$OUTPUT_DIR/court-record-hook.map"
PATCHED_CODE="$OUTPUT_DIR/code.bin"
PATCHED_EXHEADER="$OUTPUT_DIR/exheader.bin"
GENERATED_RSF="$OUTPUT_DIR/update.rsf"
CONTENT="$OUTPUT_DIR/content.cxi"
CIA="$OUTPUT_DIR/$CIA_NAME"

# Azahar historically allowed execution from non-executable CodeSet pages, while
# real hardware does not. Refuse to build outside the text mapping and extend the
# text byte count over its already-allocated final page so the hardware loader
# copies the injected tail bytes as executable code.
python3 - \
    "$SOURCE_BUILD/exheader.bin" \
    "$PATCHED_EXHEADER" \
    "$HOOK_ADDRESS" \
    "$CODE_CAVE_END" <<'PY'
from pathlib import Path
import struct
import sys

source = Path(sys.argv[1])
output = Path(sys.argv[2])
hook_start = int(sys.argv[3], 0)
hook_end = int(sys.argv[4], 0)
exheader = bytearray(source.read_bytes())
if len(exheader) < 0x1C:
    raise SystemExit(f"invalid exheader: {source}")

text_address, text_pages, text_size = struct.unpack_from("<III", exheader, 0x10)
text_end = text_address + text_pages * 0x1000
if not text_address <= hook_start < hook_end <= text_end:
    raise SystemExit(
        "hook cave is not executable according to the exheader: "
        f"hook=0x{hook_start:08X}..0x{hook_end:08X}, "
        f"text=0x{text_address:08X}..0x{text_end:08X}"
    )

required_text_size = hook_end - text_address
if text_size < required_text_size:
    struct.pack_into("<I", exheader, 0x18, required_text_size)
output.write_bytes(exheader)
PY

"$CC" \
    -mcpu=mpcore \
    "-m$HOOK_ISA" \
    -mfloat-abi=soft \
    -Os \
    -ffreestanding \
    -fno-builtin \
    -fno-pic \
    -fno-stack-protector \
    -fno-unwind-tables \
    -fno-asynchronous-unwind-tables \
    -ffunction-sections \
    -fdata-sections \
    -DORIGINAL_SET_COURT_RECORD_DETAIL="$ORIGINAL_SET_COURT_RECORD_DETAIL" \
    -DCOURT_RECORD_GLYPH_PROBE="${GLYPH_PROBE:-0}" \
    -Wall -Wextra -Werror \
    -c "$HOOK_SOURCE" \
    -o "$HOOK_OBJECT"

"$CC" \
    -mcpu=mpcore \
    "-m$HOOK_ISA" \
    -mfloat-abi=soft \
    -nostdlib \
    -Wl,--gc-sections \
    -Wl,-Map,"$HOOK_MAP" \
    -Wl,--defsym,HOOK_ADDRESS="$HOOK_ADDRESS" \
    -Wl,--defsym,CODE_CAVE_END="$CODE_CAVE_END" \
    -Wl,-T,"$HOOK_LINKER_SCRIPT" \
    "$HOOK_OBJECT" \
    -o "$HOOK_ELF"

HOOK_SYMBOL="$($NM -n "$HOOK_ELF" | awk '$3 == "court_record_detail_hook" { print $1 }')"
EXPECTED_HOOK_SYMBOL="$(printf '%08x' "$((HOOK_ADDRESS))")"
if [[ "$HOOK_SYMBOL" != "$EXPECTED_HOOK_SYMBOL" ]]; then
    echo "Hook linked at an unexpected address: ${HOOK_SYMBOL:-missing}" >&2
    exit 1
fi

"$OBJCOPY" -O binary --only-section=.text "$HOOK_ELF" "$HOOK_BIN"
"$OBJDUMP" -d "$HOOK_ELF" >"$OUTPUT_DIR/court-record-hook.disasm.txt"

INJECT_ISA_ARGS=()
if [[ "$HOOK_ISA" == thumb ]]; then
    INJECT_ISA_ARGS+=(--thumb-hook)
fi

python3 "$REPO_ROOT/scripts/inject_court_record_hook.py" \
    --image-base "$IMAGE_BASE" \
    --call-site "$CALL_SITE" \
    --hook-address "$HOOK_ADDRESS" \
    --code-cave-end "$CODE_CAVE_END" \
    --expected-call "$EXPECTED_CALL" \
    ${INJECT_ISA_ARGS[@]+"${INJECT_ISA_ARGS[@]}"} \
    "$SOURCE_BUILD/code.bin" \
    "$HOOK_BIN" \
    "$PATCHED_CODE"

python3 - "$SOURCE_BUILD/update.rsf" "$GENERATED_RSF" "$SOURCE_BUILD/romfs" <<'PY'
from pathlib import Path
import sys

source, output, romfs = map(Path, sys.argv[1:])
lines = source.read_text().splitlines()
for index, line in enumerate(lines):
    if line.lstrip().startswith("RootPath:"):
        indent = line[: len(line) - len(line.lstrip())]
        lines[index] = f"{indent}RootPath: {romfs.resolve()}"
        break
else:
    raise SystemExit("RomFs.RootPath was not found in the RSF")
output.write_text("\n".join(lines) + "\n")
PY

rm -f "$CONTENT" "$CIA"
"$MAKEROM" \
    -f ncch \
    -o "$CONTENT" \
    -rsf "$GENERATED_RSF" \
    -code "$PATCHED_CODE" \
    -exheader "$PATCHED_EXHEADER" \
    -icon "$SOURCE_BUILD/icon.bin"

"$MAKEROM" \
    -f cia \
    -o "$CIA" \
    -content "$CONTENT:0:0" \
    -ver 2099

echo
echo "Hook build complete:"
echo "  Payload: $HOOK_BIN ($(stat -f '%z' "$HOOK_BIN") bytes)"
echo "  Code:    $PATCHED_CODE"
echo "  CIA:     $CIA"
