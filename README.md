# The Great Ace Attorney 1 & 2 — English 3DS patches

N.B.: I use Codex to build the tooling around the patch.
Testing is done using the Azahar Emulator and a real New 3DS XL.
I have yet to finish both games with the patches so expect issues.

Unofficial English patches for the Japanese Nintendo 3DS releases of *Dai
Gyakuten Saiban* (*The Great Ace Attorney: Adventures*) and *Dai Gyakuten
Saiban 2* (*The Great Ace Attorney 2: Resolve*).

This project builds on the work of [Scarlet
Study](https://github.com/ScarletStudy/DGS2-3DS-Release). The main-game
episodes use the official English localization from a user-supplied PC copy of
*The Great Ace Attorney Chronicles*. TGAA1's eight Escapades also use the
official English localization. Its 3DS-only Special Issue and the two
3DS-exclusive TGAA2 DLC mini-episodes were translated directly from Japanese
for this project.

## Status

Version 1.2.0 includes hardware-tested builds for both games.

- all ten main episodes are in English;
- installed DLC is available offline from the leftmost title-menu card;
- TGAA1 extra content and both TGAA2 DLC mini-episodes are in English;
- New Game/Continue and Select Episode remain in English;
- the original Capcom startup is retained;
- FBI title metadata and Add-On Content labels are in English while retaining
  the original Capcom icon artwork;
- TGAA2 contains 2,012 direct DLC text replacements, and all 42 rebuilt DLC
  GMD containers pass semantic round-trip checks;
- line wrapping uses the final 3DS glyph advances and hardware-checked layout;
- TGAA1 DLC dialogue is paginated for the two-line 3DS text box, and every
  main-game and DLC location caption fits the final font metrics.

The leftmost DLC card intentionally has no text label in this release. This
avoids corrupting the shared animated title-menu atlas; the card itself is
visible, selectable, and functional.

Please report text, layout, menu, or crash problems in
[Issues](https://github.com/senyarom/tgaa2-en-patch/issues).

## Installation

Requirements:

- either or both Japanese 3DS base games;
- a 3DS with current custom firmware;
- FBI or another CIA installer.

Download the files for the game you own from the
[latest release](https://github.com/senyarom/tgaa2-en-patch/releases/latest),
then install its update before its DLC.

### The Great Ace Attorney: Adventures

Base game: `000400000014AD00`

1. `TGAA1-Official-English-v2.8.6.cia` — update
   (`0004000E0014AD00`);
2. `TGAA1-English-DLC-v1.0.5.cia` — DLC
   (`0004008C0014AD00`).

### The Great Ace Attorney 2: Resolve

Base game: `00040000001AE200`

1. `DGS2-Official-English-v2.3.3.cia` — update
   (`0004000E001AE200`);
2. `DGS2-English-DLC-v1.0.1.cia` — DLC
   (`0004008C001AE200`).

Launch the corresponding Japanese base-game icon normally. Do not delete the
base game. Each English update and DLC replaces the installed Japanese package
with the corresponding official Title ID.

## Repository contents

- `dgs2tool/` — clean-room GMD, ARC, BPS, IPS, manifest, and porting tools;
- `scripts/` — TGAA1/TGAA2 localization, layout, title-menu, metadata, and
  offline-DLC helpers;
- `translation/tgaa1-special-en.json` — direct Japanese-to-English TGAA1
  Special Issue translation (6 sections, 179 segments);
- `translation/dlc-direct-en.jsonl` — direct Japanese-to-English TGAA2 DLC
  translation ledger (2,012 replacements);
- `reference/` — non-game-data format/build references;
- `tests/` — unit and format regression tests.

Local extracted game inputs belong under the ignored `game-data/tgaa1/` and
`game-data/tgaa2/` directories. Build products are written to the ignored
`build/tgaa1/` and `build/tgaa2/` directories. Run a complete update build
with the mandatory native hook using:

```sh
./run.sh tgaa1 --build-only
./run.sh tgaa2 --build-only
```

To recreate those inputs from upstream releases, run
`scripts/import_game_data.py`. It accepts the supported Japanese base CIAs,
Scarlet Study TGAA1 v2.4.1 and TGAA2 v2.1.0 update CIAs, the extracted Steam
`nativeDX11x64` directory, `ctrtool`, and a local `seeddb.bin`. The importer
checks all four CIA SHA-256 hashes before extracting anything, ports the Steam
localization again, rebuilds the 3DS fonts and message archives, and reapplies
the named code, title-menu, metadata, and layout transformations. For example:

```sh
python3 scripts/import_game_data.py \
  --tgaa1-base-cia /path/to/tgaa1-base.cia \
  --tgaa1-scarlet-cia /path/to/tgaa1-scarlet-v2.4.1.cia \
  --tgaa2-base-cia /path/to/tgaa2-base.cia \
  --tgaa2-scarlet-cia /path/to/tgaa2-scarlet-v2.1.0.cia \
  --seeddb /path/to/seeddb.bin \
  --steam-root /path/to/nativeDX11x64 \
  --ctrtool /path/to/ctrtool \
  --output game-data-recreated
```

The generated `tgaa1/` and `tgaa2/` directories are sufficient for
`--build-only`. `base.cxi` is intentionally not recreated because it is only
used to launch an emulator, not to build either update CIA.

Each game-data directory contains the current `code.bin`, `exheader.bin`,
`icon.bin`, `update.rsf`, `romfs/`, and `base.cxi`. TGAA1 additionally needs
`tutorial.gmd`; both games need `font.gfd`. Put `makerom` at
`game-data/tools/makerom` or set `MAKEROM`; set `DEVKITARM` if devkitARM is not
installed at its standard path. Running without `--build-only` installs the
newly built CIA into an isolated Azahar profile under `build/` and launches
the selected base game.

The repository does not contain Japanese or Scarlet CIAs, Steam depots, title
keys, seeds, or extracted game assets. Development inputs belong under ignored
`private/` or `game-data/` directories.

Run the tooling tests with Python 3.10 or newer:

```sh
python3 -m unittest discover -s tests -v
```

## Credits

- Scarlet Study and Fan Translators International — original 3DS English
  patches, font/rendering work, and reverse engineering;
- Capcom — the original games and official *Chronicles* localization;
- Kuriimu2 contributors — documented MT Framework formats;
- TGAA/DGS community contributors and testers.

This is an unofficial fan project and is not affiliated with or endorsed by
Capcom, Nintendo, or Scarlet Study.
