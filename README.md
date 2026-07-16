# The Great Ace Attorney 2 — English 3DS patch

An unofficial English patch for the Japanese Nintendo 3DS release of *Dai
Gyakuten Saiban 2: Naruhodou Ryuunosuke no Kakugo* (*The Great Ace Attorney 2:
Resolve*).

This continuation builds on the work of [Scarlet
Study](https://github.com/ScarletStudy/DGS2-3DS-Release). The five main-game
episodes use the official English localization from a user-supplied PC copy of
*The Great Ace Attorney Chronicles*. The two 3DS-exclusive DLC mini-episodes
were translated directly from Japanese for this project.

## Status

Version 1.0.0 is the first stable release and has been verified on real 3DS
hardware.

- all five main episodes are in English;
- both DLC mini-episodes are in English;
- the DLC menu and offline installed-content checks are enabled;
- the original Capcom startup is retained;
- 2,012 DLC text replacements are included;
- all 42 rebuilt DLC GMD containers pass semantic round-trip checks;
- DLC line wrapping uses the final 3DS glyph advances and the same 365-pixel
  limit as the main patch.

Please report text, layout, menu, or crash problems in
[Issues](https://github.com/senyarom/tgaa2-en-patch/issues).

## Installation

Requirements:

- the Japanese 3DS base game, Title ID `00040000001AE200`;
- a 3DS with current custom firmware;
- FBI or another CIA installer.

Download both CIA files from the
[latest release](https://github.com/senyarom/tgaa2-en-patch/releases/latest),
then install them in this order:

1. the English update, Title ID `0004000E001AE200`;
2. the English DLC, Title ID `0004008C001AE200`.

Launch the Japanese base-game icon normally. Do not delete the base game. The
English update replaces the installed Japanese update, and the English DLC
replaces the installed Japanese DLC because they use the corresponding
official Title IDs.

## Repository contents

- `dgs2tool/` — clean-room GMD, ARC, BPS, IPS, manifest, and porting tools;
- `scripts/` — official-layout, DLC translation, wrapping, and offline-DLC
  helpers;
- `translation/dlc-direct-en.jsonl` — direct Japanese-to-English DLC
  translation ledger;
- `reference/` — non-game-data format/build references;
- `tests/` — unit and format regression tests.

The repository does not contain Japanese CIAs, Steam depots, title keys,
seeds, or extracted game assets. Development inputs belong under ignored
`private/` or `game-data/` directories.

Run the tooling tests with Python 3.10 or newer:

```sh
python3 -m unittest discover -s tests -v
```

## Credits

- Scarlet Study and Fan Translators International — original 3DS English
  patch, font/rendering work, and reverse engineering;
- Capcom — the original games and official *Chronicles* localization;
- Kuriimu2 contributors — documented MT Framework formats;
- TGAA/DGS community contributors and testers.

This is an unofficial fan project and is not affiliated with or endorsed by
Capcom, Nintendo, or Scarlet Study.
