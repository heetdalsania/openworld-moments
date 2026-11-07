# SPDX-License-Identifier: AGPL-3.0-or-later
"""A stand-in for whisper.cpp's CLI, used only by tests. Behaviour comes from the JSON
control file named by OWM_FAKE_WHISPER: write a fixture output, fail, hang (writing a
heartbeat so tests can prove the process was killed), or print garbage."""

from __future__ import annotations

import json
import os
import sys
import time
import wave
from pathlib import Path

args = sys.argv[1:]
if "--help" in args:
    print("usage: whisper-cli [options] file0.wav")
    print("  -ojf,      --output-json-full  [false  ] include more information in the JSON file")
    print("whisper.cpp version 1.7.6 (test double)")
    sys.exit(0)


def option(flag: str) -> str:
    return args[args.index(flag) + 1]


control = json.loads(Path(os.environ["OWM_FAKE_WHISPER"]).read_text("utf-8"))
calls = Path(control["calls"])
with calls.open("a", encoding="utf-8") as log:
    log.write(json.dumps({"language": option("-l"), "threads": option("-t")}) + "\n")
call = len(calls.read_text("utf-8").splitlines())

with wave.open(option("-f"), "rb") as audio:
    if (audio.getframerate(), audio.getnchannels(), audio.getsampwidth()) != (16000, 1, 2):
        sys.exit(3)
    if not Path(option("-m")).is_file():
        sys.exit(4)

mode = control.get("modes", {}).get(str(call), control.get("mode", "ok"))
if mode == "fail":
    sys.stderr.write("engine exploded while reading: MEET AT THE BRIDGE\n")
    sys.exit(2)
if mode == "hang":
    beat = Path(control["heartbeat"])
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        beat.write_text(str(time.monotonic()), "utf-8")
        time.sleep(0.02)
    sys.exit(0)
target = Path(option("-of") + ".json")
if mode == "garbage":
    target.write_text("{not json", "utf-8")
else:
    target.write_text(Path(control["output"]).read_text("utf-8"), "utf-8")
