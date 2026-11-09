# Local transcription

OpenWorld Moments can turn the speech in a session into timed text: your voice chat,
commentary, or the game's dialogue. Transcription is **optional** and runs **only on
your computer**:

- **Nothing is downloaded automatically.** You install the speech engine and a model
  yourself.
- **Nothing is uploaded.** Audio and text stay in your library.
- **Transcripts can contain private conversations.** Delete one at any time; your
  videos are never affected.

## Set up

1. **Install whisper.cpp.** whisper.cpp is a free, open-source (MIT) speech
   recognizer. Install it from its official project page,
   [github.com/ggml-org/whisper.cpp](https://github.com/ggml-org/whisper.cpp), for
   example with a package manager (on macOS, `brew install whisper-cpp`). The app
   looks for `whisper-cli` (or `whisper-cpp`) on your PATH. To point it at a
   specific file, set the `OWM_WHISPER` environment variable.
2. **Download a model yourself.** Models are on the
   [whisper.cpp model page](https://huggingface.co/ggerganov/whisper.cpp), MIT
   licensed. `base.en` (about 148 MB) is a good start for English.
   - `tiny.en` is faster but less accurate.
   - Models without `.en` handle other languages.
3. **Install the model into your library** from a terminal in the repository:

   ```bash
   uv run --directory services/media-worker owm models install --library "/path/to/your/library" base.en "/path/to/ggml-base.en.bin" --license MIT
   ```

   The file is copied and fingerprinted, and your download is left as is.
   - Check the engine with `owm speech doctor`.
   - List or remove models with `owm models list` and `owm models remove`.

## Install models from Settings

The Windows alpha candidate also offers **Settings → Optional speech models**.
Choose **Install tiny.en** or **Install base.en** after reviewing the size, source,
MIT license, pinned revision and checksum. This is the only action that starts a
download. Audio and transcripts are never sent to the model host.

The app checks space, verifies the signed catalog and checks the completed file's
SHA-256 before showing **Verified installed**. Cancelled/interrupted bytes can be
resumed by selecting **Resume install**. Offline, low-space or checksum failures
leave existing verified models usable. **Verify models again** checks local
contents; **Remove** asks before deleting that model and its saved versions.
Media and transcripts stay in the library. Previously verified versions can be
selected explicitly when available. See the [packaging guide](../architecture/windows-packaging.md).

The speech engine in step 1 is still a separate optional installation. Installing
a model does not install the engine. The CLI flow above remains available for
other models and development installations.

## Transcribe a session

1. **Open the session:** go to **Sessions** and open one.
2. **Start:** under **Transcript**, choose a model and a language (or leave
   **Detect automatically**), then select **Transcribe speech**.
3. **Wait or cancel:** progress shows in the panel and in **Background jobs**.
   Cancelling keeps the clips that already finished; transcribe again to continue.
4. **Use the lines:** each line shows where it starts. Select the time to play from
   that moment. Lines the engine was unsure about are marked **Low confidence**.

Repeated footage that the session hides is not transcribed twice.

## Rebuild or delete

- **Rebuild transcript:** runs the transcription again, for example with another
  model or language, or after you reorder clips.
- **Delete transcript…:** asks for confirmation, then removes only the transcript
  text. Your video files, playback copies and other results are untouched.

## Troubleshooting

| Message | What to do |
|---|---|
| Install whisper.cpp (whisper-cli) to enable optional local transcription | whisper.cpp is not on your PATH; install it or set `OWM_WHISPER` |
| This whisper.cpp build does not support full JSON output | Update whisper.cpp |
| No speech model is installed | Choose Install in Settings, or use `owm models install` |
| The installed model file changed | The model file was modified; install it again |
| This clip has no audio | Nothing to transcribe in that clip; the others still are |

Accuracy depends on the model, the language and how clear the audio is. Game music
and effects over speech reduce it.
