# Buddy – Desktop Cat Reminder 🐱

A tiny, draggable cat that lives on your desktop and reminds you to **drink water**, **take breaks**, and **join meetings** (10 minutes before they start). Meetings are stored in a local MySQL database.

## Features

- Tiny always-on-top cat that breathes, blinks, and bounces when it has a reminder
- Drag it anywhere on screen – the position is remembered between runs
- Click the cat to schedule a meeting (any date and time)
- Water reminder (default every 45 min) and break reminder (default every 60 min)
- Meeting reminder 10 minutes before start, shown in a speech bubble
- Hover tooltip shows your next meeting
- Use your own cat picture or animated GIF (local file or online URL)
- System tray icon with menu

## Requirements

- Python 3.9+
- MySQL server running locally
- Python packages:

```
pip install PySide6 mysql-connector-python
```

## Setup

1. Make sure MySQL is running.
2. Save the script as `main.py` (or `buddy_reminder.py`).
3. If your MySQL login is not `root` with an empty password, set environment variables.

   **PowerShell**
   ```
   $env:DB_USER="root"
   $env:DB_PASS="your_password"
   $env:DB_HOST="localhost"
   ```
   **macOS / Linux**
   ```
   export DB_USER=root DB_PASS=your_password DB_HOST=localhost
   ```
4. Run:

```
python main.py
```

The database `buddy_reminder` and table `meetings` are created automatically on first run.

## Controls

| Action | What happens |
|---|---|
| Left-click the cat | Add a meeting |
| Drag the cat | Move it anywhere (position is saved) |
| Right-click the cat | Menu: Add meeting, Upcoming meetings, Test reminder, Quit |
| Click a speech bubble | Dismiss it |
| Hover over the cat | See your next meeting |
| Ctrl+C in the terminal | Quit cleanly |

The tray icon has the same menu. On Windows it may be hidden under the `^` arrow in the taskbar.

## Settings

Edit the constants at the top of the script:

| Setting | Default | Meaning |
|---|---|---|
| `WATER_EVERY_MIN` | 45 | Minutes between water reminders |
| `BREAK_EVERY_MIN` | 60 | Minutes between break reminders |
| `MEETING_WARN_MIN` | 10 | Minutes before a meeting to remind you |
| `SHOW_SECONDS` | 12 | How long a speech bubble stays visible |
| `CAT_IMAGE` | `""` | Path or URL of your cat image (see below) |

## Using your own cat image

The built-in cat is drawn with code. For a cuter or more realistic look, use a picture or GIF with a **transparent background** (otherwise a white box appears around the cat). Pick one of:

1. Set `CAT_IMAGE = "https://example.com/cat.png"` – downloaded once and cached in your home folder.
2. Set `CAT_IMAGE = "C:/path/to/cat.gif"` – a local file.
3. Put `cat.gif`, `cat.png`, or `cat.webp` in the same folder as the script – detected automatically.

You can also use the `BUDDY_IMAGE` environment variable. Animated GIFs play automatically. Check the licence of any image you download. If the image fails to load, the drawn cat is used instead.

## Where data is stored

| What | Where |
|---|---|
| Meetings | MySQL database `buddy_reminder`, table `meetings` |
| Cat position | `~/.buddy_pos.json` (delete it to reset to the bottom-right) |
| Downloaded cat image | `~/.buddy_cat_*.png/gif` in your home folder |

## Troubleshooting

- **"Could not connect to MySQL"** – start the MySQL service and check `DB_USER`, `DB_PASS`, and `DB_HOST`.
- **Cat not visible** – delete `~/.buddy_pos.json` and restart.
- **White box around the cat image** – use an image with a transparent background.
- **Can't stop the app** – right-click the cat and choose Quit, or press Ctrl+C. Last resort: `taskkill /F /IM python.exe`.
- **No reminder for a meeting** – reminders only fire for meetings starting within the next 10 minutes, and only once per meeting.
