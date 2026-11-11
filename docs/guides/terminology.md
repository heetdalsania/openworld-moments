# Terminology

> **Applies to:** OpenWorld Moments 0.1.0 alpha for Windows 11 (x64).
> **Last checked:** 2026-11-11 (M31).

The words the app uses, in plain language. Where an older or technical word appears
somewhere in the app, it is listed too.

| Term | Meaning |
|---|---|
| **Clip** | One video file in your library. Also called an *asset* in technical documents. |
| **Library** | Everything the app knows about your clips, plus its own database, playback copies, renders and models. It lives in `%APPDATA%\org.openworldmoments.desktop\library`. |
| **Reference import** | The library points at the file where it already is. Uses no extra space; keep the file where it is. |
| **Managed import** | The file is copied into the library. Uses more space; safe if you later move or delete the original. |
| **Original** (source footage) | Your own video file. The app only reads it and never changes, moves or deletes it. |
| **Playback copy** (proxy) | A lighter copy the app makes when a clip's format can't be played directly. Can always be recreated. |
| **Watched folder** | A folder the app checks for new videos and imports them automatically. |
| **Session** | Clips recorded together, grouped into one timeline. |
| **Repeated footage** (overlap) | The same gameplay captured in two clips, for example by overlapping saved clips. A session plays it once; **R** shows it. |
| **Event** | A moment the app detected or you added, with the evidence behind it and a confidence score. Also called an *observation*. |
| **Evidence** | What a detected event is based on: a region of the screen, recognized text, an audio feature. |
| **Confidence** | How sure the detector is, from 0 to 100%. It is a hint for review, not a guarantee. |
| **Profile** | The settings that tell detectors where to look on screen for a particular game and layout. |
| **Calibration** | Adjusting a profile's screen regions to your captures. |
| **Story** (project) | An edit you make from a session: a list of cuts plus layout, captions and audio settings. Rendering it makes a video. |
| **Cut** | One piece of a story, taken from a clip between an in and an out point. |
| **Primary track** | The row of cuts in the story editor, in playback order. |
| **Render** | Turning a story into a finished video file (H.264/AAC MP4) inside the library. |
| **Preset** | Size, frame rate and quality settings for a render. |
| **Encoder** | What compresses the video: the CPU (`libx264`) or your graphics hardware. |
| **Manifest** | A file describing exactly what went into a render. |
| **Open-format export** | Project data saved for other tools (OTIO, FCPXML, captions, markers). |
| **Privacy review** | A checklist before sharing: blur or mute personal information and mark spoilers. |
| **Phone transfer** | A temporary upload page on your home network for sending clips from a phone. Off until you allow it. |
| **Optional model** | A speech-to-text model you can download for transcription. Off until you allow downloads. |
| **Media worker** (worker) | The part of the app that does the heavy work in the background. The bar at the top reports its state. |
| **Background job** | Work the worker does while you carry on: imports, playback copies, analysis, renders. |
| **Diagnostics report** | A file for support with versions, counts and error codes, and nothing personal. |
