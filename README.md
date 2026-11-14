# drumgame

A DTXMania-style rhythm game for electronic drums, in Python. Notes fall down
one lane per pad; you hit the pads in time. Input is MIDI (built around a
Roland TD-17), with the computer keyboard as a full fallback so it is playable
with no kit.

Status: early. There is one play screen, a built-in rock beat, a metronome,
judging and scoring, and a MIDI-file importer. Not built yet: learn mode,
latency calibration, backing audio, Guitar Pro and `.dtx` import, menus.

## Setup (Arch Linux)

```bash
sudo pacman -S base-devel pkgconf alsa-lib alsa-utils python
```

```bash
python -m venv .venv && source .venv/bin/activate
```

```bash
pip install -e ".[dev]"
```

`python-rtmidi` compiles against ALSA; if its build fails, `alsa-lib` or
`base-devel` is usually what is missing. The game still runs without it, on
the keyboard alone.

## Running

```bash
drumgame                      # built-in rock beat
drumgame songs/song.mid       # import a MIDI file and play its drum part
drumgame songs/chart.json     # play a chart in the internal format
drumgame --layout compact     # 6 lanes instead of 10
drumgame --fullscreen         # or press F11 while playing
drumgame --ui-scale 1.2       # bigger text and notes, for reading from the kit
drumgame --no-fail            # practice: the song never ends early
drumgame song.mid --save-chart songs/song.json   # convert, do not play
```

Default keys, left to right: `Q` left crash, `S` hi-hat, `Z` hi-hat pedal,
`D` snare, `F` high tom, `Space` kick, `J` mid tom, `K` floor tom, `L` right
crash, `;` ride. `Esc` or `Enter` pauses, `Esc` again quits, `Backspace`
restarts, `F11` switches fullscreen.

The window can be resized and the whole screen scales to fit it. The gauge
beside the highway fills on hits and drains on misses; when it empties the
song ends, unless you pass `--no-fail` or set `can_fail = false`.

On screen, left to right: a gauge of recent form, the highway, and an info
panel. Judgements appear in the lane you hit (with EARLY or LATE on a "good"),
the combo counter sits behind the notes, the song map shows where the busy
parts and section starts are, and the timing meter in the panel shows your recent hits on an early-to-late scale with their average, which is
the number to watch when calibrating.

Keyboard hits are timestamped once per frame, so they are less precise than
MIDI hits, which are stamped on arrival in the rtmidi callback thread. Do not
tune hit windows from keyboard play.

## MIDI

```bash
drumgame --list-ports         # the kit should be listed
drumgame --monitor            # print every hit: channel, note, lane, status
drumgame --port TD-17         # pick a port by name substring
```

TD-17 settings: USB driver mode **GENERIC**, MIDI Tx/Rx **ON**, connected
directly rather than through a hub. If the port does not show up, check those
first, then `amidi -l` and `aseqdump -l`.

**The built-in TD-17 note map is an unverified draft.** Run `--monitor`, hit
every pad and zone, and fix any line that says `unmapped` or shows the wrong
lane by overriding it in your config.

To exercise the MIDI path with no kit, run the game with a virtual port and
send it a beat:

```bash
drumgame --virtual-port
```

```bash
python tools/send_test_notes.py --port drumgame
```

## Configuration

Defaults live in [`drumgame/data/default.toml`](drumgame/data/default.toml),
which documents every setting. Put overrides in
`~/.config/drumgame/config.toml` (or pass `--config FILE`); only the keys you
set change. Example:

```toml
[input]
midi_port = "TD-17"
midi_channel = 10

[midi_map]
58 = ""          # ignore this note
60 = "tom_floor"

[judge]
perfect_ms = 40
```

## Charts

Charts and audio are user-supplied. `songs/` is git-ignored; do not commit
copyrighted tabs, charts or audio.

The internal format is JSON with musical time in ticks plus a tempo map:

```json
{
  "title": "Example",
  "artist": "Example",
  "resolution": 480,
  "tempos": [{"tick": 0, "bpm": 120.0}],
  "time_signatures": [{"tick": 0, "numerator": 4, "denominator": 4}],
  "notes": [{"tick": 0, "lane": "kick"}, {"tick": 480, "lane": "snare", "ghost": true}],
  "sections": [{"tick": 0, "name": "Intro"}]
}
```

Lanes: `crash_l, hihat, hh_pedal, snare, tom_hi, kick, tom_mid, tom_floor,
crash_r, ride`.

The MIDI importer reads channel 10 using the General MIDI drum map, keeps the
file's own tick resolution, and prints a warning for notes it cannot map or
for files with nothing on channel 10.

## Credits

The interface is set in Barlow Semi Condensed by Jeremy Tribby, bundled under
the SIL Open Font License (see `drumgame/data/fonts/OFL.txt`).

## Development

```bash
pytest
```

Game logic (`chart/`, `game/judge.py`, `game/clock.py`, `game/metronome.py`,
`input/mapping.py`, `input/midi_in.py`) has no pygame imports and is covered by
unit tests. Rendering lives in `game/highway.py` and `game/screens/`.
