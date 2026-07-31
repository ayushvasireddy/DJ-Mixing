# Getting Started (no coding experience required)

This is a plain-language walkthrough for getting the AI DJ running on a Mac
for the first time, plus fixes for the specific snags people hit along the
way. For the technical overview of what this project does, see
[`README.md`](README.md).

## 1. Download the code

1. Go to the project's branch page in your browser:
   `https://github.com/ayushvasireddy/DJ-Mixing/tree/claude/ai-live-mixing-model-ibhw8t`
2. Click the green **`<> Code`** button, then **Download ZIP**
3. Find the zip in **Downloads**, double-click it to unzip
4. Drag the unzipped folder to your **Desktop** and rename it `DJ-Mixing`

## 2. Launch it

Double-click **`run_app.command`** inside that folder.

- First run installs everything automatically (a few minutes, don't close
  the window) and then opens your browser to the app.
- Every run after that is just a normal double-click.

If that works and your browser opens to a page titled "AI DJ," skip to
[Using the app](#using-the-app) below. If something blocks you, find it here:

## Troubleshooting

### "run_app.command Not Opened" / "Apple could not verify..."

macOS blocks scripts downloaded from the internet by default. Two ways
around it:

**Fastest -- run it from Terminal instead of double-clicking:**
1. Open the **Terminal** app
2. Type `cd ~/Desktop/DJ-Mixing` and press Enter
3. Type `bash run_app.command` and press Enter

**Or -- approve it once in System Settings:**
1. Click **Done** on the warning (not "Move to Trash")
2. Apple menu → **System Settings** → **Privacy & Security**
3. Scroll down to the blocked-app message, click **Open Anyway**
4. Confirm with your password/Touch ID if asked
5. Double-click `run_app.command` again -- it'll now offer a real **Open** button

### A terminal `sudo`/install command is asking for a "Password:" and won't let me type

This is normal, not broken. macOS Terminal **never shows anything** while
you type a password -- no dots, no cursor movement, nothing. Just type your
regular Mac login password (the one that unlocks your computer) in one go
and press Enter. It's not your Apple ID/iCloud password if those differ.

### VS Code popped up "Select an environment manager" / "Creating environment..."

That's VS Code's own Python tooling offering to set up a *separate*
environment for the editor's autocomplete -- it's unrelated to running the
app. Press `Escape` to close it, dismiss the notification if it lingers, and
keep using the terminal environment you already have (look for `(.venv)` at
the start of the terminal prompt -- if it's there, you're set).

### Homebrew (`brew`) says "command not found"

You don't have Homebrew installed yet. Go to `https://brew.sh`, copy the
install command shown on that page into your terminal, press Enter, and
follow the prompts (it's normal for it to ask for your password, invisibly,
as above).

## Using the app

Once the browser page opens:

1. **Add tracks**: leave the library folder as `tracks`, then drag your audio
   files (mp3/wav/flac/m4a/aiff/ogg) into the upload box.
2. **Pick devices**: choose your microphone and speakers/output from the
   dropdowns. No mic, or don't want crowd sensing yet? Uncheck "Use
   microphone."
3. Click **Start the set**. The first run analyzes each track's BPM/key/
   energy, which takes a little while; after that it's cached and instant.
4. Watch the crowd energy meter and now-playing card, or use **Hype / Chill
   / Skip / Hold** to steer it yourself.
5. Click **Stop the set** when you're done, and keep the Terminal window
   open the whole time -- closing it shuts the app down.

Still stuck on something not listed here? Copy the exact error text you're
seeing and ask -- don't try to guess-fix it by deleting or force-reinstalling
things.
