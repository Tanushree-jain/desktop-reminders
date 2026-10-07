"""
Buddy - a tiny always-on-screen desktop cat reminder.

  * Tiny cat sits at the bottom of your screen. DRAG it anywhere (position is remembered).
  * LEFT-CLICK  -> add a meeting.     RIGHT-CLICK -> menu (list meetings, test, quit)
  * Water / break reminders + meeting reminder 10 min before (meetings stored in MySQL)
  * Use your own cute/realistic cat picture or GIF (local file OR online URL), see CAT_IMAGE.

Install:  pip install PySide6 mysql-connector-python
Run:      python buddy_reminder.py
"""
import hashlib
import json
import math
import os
import signal
import sys
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse

import mysql.connector
from PySide6.QtCore import QDateTime, QPointF, QRectF, Qt, QTimer, QPoint
from PySide6.QtGui import (QAction, QColor, QFont, QIcon, QMovie, QPainter, QPainterPath,
                           QPen, QPixmap, QPolygonF)
from PySide6.QtWidgets import (QApplication, QDateTimeEdit, QDialog, QDialogButtonBox,
                               QFormLayout, QLineEdit, QMenu, QMessageBox, QSystemTrayIcon,
                               QWidget)

# ---------------- settings ----------------
WATER_EVERY_MIN = 45
BREAK_EVERY_MIN = 60
MEETING_WARN_MIN = 10
SHOW_SECONDS = 12
# Cat picture: a local path or an http(s) URL to a PNG/GIF/WEBP with TRANSPARENT background.
# Leave empty to use the built-in drawn cat. (Or just drop cat.gif / cat.png next to this file.)
CAT_IMAGE = ""
DB = dict(host=os.getenv("DB_HOST", "localhost"), user=os.getenv("DB_USER", "root"),
          password=os.getenv("DB_PASS", ""))
DB_NAME = "buddy_reminder"
POS_FILE = Path.home() / ".buddy_pos.json"


# ---------------- database ----------------
class Store:
    def __init__(self):
        con = mysql.connector.connect(**DB)
        con.cursor().execute(f"CREATE DATABASE IF NOT EXISTS {DB_NAME}")
        con.close()
        self.con = mysql.connector.connect(database=DB_NAME, autocommit=True, **DB)
        self.con.cursor().execute(
            """CREATE TABLE IF NOT EXISTS meetings (
                 id INT AUTO_INCREMENT PRIMARY KEY,
                 title VARCHAR(200) NOT NULL,
                 start_time DATETIME NOT NULL,
                 notified TINYINT NOT NULL DEFAULT 0)""")

    def add(self, title, when):
        self.con.cursor().execute(
            "INSERT INTO meetings (title, start_time) VALUES (%s, %s)", (title, when))

    def due(self):
        now = datetime.now()
        cur = self.con.cursor(dictionary=True)
        cur.execute("""SELECT * FROM meetings WHERE notified=0
                       AND start_time > %s AND start_time <= %s ORDER BY start_time""",
                    (now, now + timedelta(minutes=MEETING_WARN_MIN)))
        rows = cur.fetchall()
        for r in rows:
            self.con.cursor().execute("UPDATE meetings SET notified=1 WHERE id=%s", (r["id"],))
        return rows

    def upcoming(self, limit=15):
        cur = self.con.cursor(dictionary=True)
        cur.execute("SELECT * FROM meetings WHERE start_time > %s ORDER BY start_time LIMIT %s",
                    (datetime.now(), limit))
        return cur.fetchall()


# ---------------- image loading ----------------
def resolve_image():
    src = os.getenv("BUDDY_IMAGE", CAT_IMAGE).strip()
    if not src:
        for name in ("cat.gif", "cat.png", "cat.webp"):
            f = Path(__file__).with_name(name)
            if f.exists():
                return str(f)
        return None
    if src.startswith("http"):
        ext = Path(urlparse(src).path).suffix or ".png"
        f = Path.home() / f".buddy_cat_{hashlib.md5(src.encode()).hexdigest()[:8]}{ext}"
        if not f.exists():
            try:
                req = urllib.request.Request(src, headers={"User-Agent": "Mozilla/5.0"})
                f.write_bytes(urllib.request.urlopen(req, timeout=10).read())
            except Exception as ex:
                print("Could not download cat image, using drawn cat:", ex)
                return None
        return str(f)
    return src if Path(src).exists() else None


# ---------------- the drawn cat (fallback) ----------------
def draw_cat(p, t, bounce):
    cx = 150
    fur, dark, pink = QColor("#FFB86B"), QColor("#4A3426"), QColor("#FF9EB5")
    cream = QColor("#FFE7C7")
    pen = QPen(dark, 3.5)
    # tail
    wag = math.sin(t * 0.2) * 12
    path = QPainterPath(QPointF(cx + 40, 295 - bounce))
    path.cubicTo(cx + 90, 300 - bounce, cx + 90 + wag, 250 - bounce, cx + 70 + wag, 235 - bounce)
    p.setBrush(Qt.NoBrush)
    p.setPen(QPen(fur.darker(110), 14, Qt.SolidLine, Qt.RoundCap))
    p.drawPath(path)
    # body, belly, feet
    p.setPen(pen)
    p.setBrush(fur)
    p.drawRoundedRect(QRectF(cx - 42, 245 - bounce, 84, 65), 30, 30)
    p.setBrush(cream)
    p.drawEllipse(QRectF(cx - 24, 262 - bounce, 48, 42))
    p.setBrush(fur)
    p.drawEllipse(QRectF(cx - 44, 290 - bounce, 30, 20))
    p.drawEllipse(QRectF(cx + 14, 290 - bounce, 30, 20))
    # ears
    for s in (-1, 1):
        p.setPen(pen)
        p.setBrush(fur)
        p.drawPolygon(QPolygonF([QPointF(cx + s * 52, 190 - bounce), QPointF(cx + s * 56, 140 - bounce),
                                 QPointF(cx + s * 18, 165 - bounce)]))
        p.setPen(Qt.NoPen)
        p.setBrush(pink)
        p.drawPolygon(QPolygonF([QPointF(cx + s * 45, 180 - bounce), QPointF(cx + s * 49, 154 - bounce),
                                 QPointF(cx + s * 28, 168 - bounce)]))
    # head
    p.setPen(pen)
    p.setBrush(fur)
    p.drawEllipse(QRectF(cx - 68, 160 - bounce, 136, 112))
    p.setBrush(cream)
    p.setPen(Qt.NoPen)
    p.drawEllipse(QRectF(cx - 30, 215 - bounce, 60, 42))
    p.setPen(pen)
    for dx in (-12, 0, 12):
        p.drawLine(cx + dx, 163 - bounce, cx + dx, 175 - bounce)
    # eyes
    blinking = (t % 120) < 5
    for s in (-1, 1):
        ex = cx + s * 30
        if blinking:
            p.drawArc(QRectF(ex - 9, 205 - bounce, 18, 12), 0, -180 * 16)
        else:
            p.setPen(Qt.NoPen)
            p.setBrush(QColor("#4A3426"))
            p.drawEllipse(QRectF(ex - 10, 195 - bounce, 20, 26))
            p.setBrush(QColor("white"))
            p.drawEllipse(QRectF(ex - 5, 198 - bounce, 8, 8))
            p.drawEllipse(QRectF(ex + 1, 211 - bounce, 4, 4))
            p.setPen(pen)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(255, 120, 150, 110))
    for s in (-1, 1):
        p.drawEllipse(QRectF(cx + s * 48 - 12, 222 - bounce, 24, 14))
    p.setBrush(pink)
    p.drawEllipse(QRectF(cx - 5, 224 - bounce, 10, 7))
    p.setPen(QPen(dark, 2.5))
    p.setBrush(Qt.NoBrush)
    p.drawArc(QRectF(cx - 12, 228 - bounce, 12, 12), 0, -180 * 16)
    p.drawArc(QRectF(cx, 228 - bounce, 12, 12), 0, -180 * 16)
    p.setPen(QPen(dark, 1.8))
    for s in (-1, 1):
        p.drawLine(cx + s * 40, 230 - bounce, cx + s * 66, 224 - bounce)
        p.drawLine(cx + s * 40, 236 - bounce, cx + s * 66, 238 - bounce)


FLAGS = Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool


# ---------------- speech bubble ----------------
class Bubble(QWidget):
    W, H = 270, 118

    def __init__(self, pet):
        super().__init__(None, FLAGS)
        self.pet, self.text, self.tail_x = pet, "", 135
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.resize(self.W, self.H)

    def show_text(self, text):
        self.text = text
        self.follow()
        self.show()
        self.raise_()

    def follow(self):
        geo = QApplication.primaryScreen().availableGeometry()
        cx = self.pet.x() + self.pet.width() // 2
        x = min(max(cx - self.W // 2, geo.left() + 4), geo.right() - self.W - 4)
        y = max(self.pet.y() - self.H + 14, geo.top() + 4)
        self.move(x, y)
        self.tail_x = min(max(cx - x, 30), self.W - 30)
        self.update()

    def mousePressEvent(self, _):
        self.pet.dismiss()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        dark = QColor("#4A3426")
        path = QPainterPath()
        path.addRoundedRect(QRectF(3, 3, self.W - 6, self.H - 24), 18, 18)
        tail = QPainterPath()
        tx = self.tail_x
        tail.addPolygon(QPolygonF([QPointF(tx - 12, self.H - 22), QPointF(tx, self.H - 4),
                                   QPointF(tx + 12, self.H - 22), QPointF(tx - 12, self.H - 22)]))
        path = path.united(tail)
        p.setPen(QPen(dark, 2.5))
        p.setBrush(QColor("white"))
        p.drawPath(path)
        p.setPen(dark)
        p.setFont(QFont("Segoe UI", 11, QFont.DemiBold))
        p.drawText(QRectF(16, 10, self.W - 32, self.H - 44), Qt.AlignCenter | Qt.TextWordWrap, self.text)


# ---------------- the tiny draggable cat ----------------
class Pet(QWidget):
    W, H = 120, 120

    def __init__(self, image):
        super().__init__(None, FLAGS)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.resize(self.W, self.H)
        self.t, self.alert, self.queue = 0, False, []
        self.drag, self.moved = None, False
        self.on_click, self.menu = (lambda: None), None
        self.movie = self.pix = None
        if image:
            if image.lower().endswith((".gif", ".webp")):
                m = QMovie(image)
                if m.isValid():
                    self.movie = m
                    m.frameChanged.connect(self.update)
                    m.start()
            if not self.movie:
                pm = QPixmap(image)
                self.pix = None if pm.isNull() else pm
        self.bubble = Bubble(self)
        self.hide_timer = QTimer(self, singleShot=True, timeout=self.dismiss)
        QTimer(self, interval=33, timeout=self._frame).start()
        self._place()

    def _place(self):
        geo = QApplication.primaryScreen().availableGeometry()
        x, y = geo.right() - self.W - 20, geo.bottom() - self.H + 4
        try:
            d = json.loads(POS_FILE.read_text())
            x, y = int(d["x"]), int(d["y"])
        except Exception:
            pass
        self.move(min(max(x, geo.left()), geo.right() - self.W),
                  min(max(y, geo.top()), geo.bottom() - self.H))

    def _frame(self):
        self.t += 1
        self.update()

    # reminders
    def say(self, text):
        self.queue.append(text)
        if not self.alert:
            self._next()

    def _next(self):
        if self.alert or not self.queue:
            return
        self.alert = True
        self.bubble.show_text(self.queue.pop(0))
        self.hide_timer.start(SHOW_SECONDS * 1000)

    def dismiss(self):
        self.hide_timer.stop()
        self.bubble.hide()
        self.alert = False
        QTimer.singleShot(400, self._next)

    # drawing
    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        amp, speed = (9, 0.22) if self.alert else (2, 0.06)
        bounce = abs(math.sin(self.t * speed)) * amp
        src = self.movie.currentPixmap() if self.movie else self.pix
        if src is not None and not src.isNull():
            pm = src.scaled(100, 100, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            p.drawPixmap((self.W - pm.width()) // 2, int(self.H - pm.height() - 4 - bounce), pm)
        else:
            p.translate(self.W / 2, self.H - 6)
            p.scale(0.55, 0.55)
            p.translate(-150, -310)
            draw_cat(p, self.t, bounce * 1.8)

    # drag + click
    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.drag = e.globalPosition().toPoint() - self.frameGeometry().topLeft()
            self.moved = False

    def mouseMoveEvent(self, e):
        if self.drag is not None and e.buttons() & Qt.LeftButton:
            target = e.globalPosition().toPoint() - self.drag
            if (target - self.pos()).manhattanLength() > 4:
                self.moved = True
            if self.moved:
                self.move(target)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton and self.drag is not None:
            self.drag = None
            if self.moved:
                POS_FILE.write_text(json.dumps({"x": self.x(), "y": self.y()}))
            elif self.alert:
                self.dismiss()
            else:
                self.on_click()

    def moveEvent(self, e):
        if self.alert:
            self.bubble.follow()

    def contextMenuEvent(self, e):
        if self.menu:
            self.menu.exec(e.globalPos())


# ---------------- add-meeting dialog ----------------
class AddMeeting(QDialog):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Add meeting")
        self.setWindowFlag(Qt.WindowStaysOnTopHint)
        form = QFormLayout(self)
        self.title = QLineEdit()
        self.when = QDateTimeEdit(QDateTime.currentDateTime().addSecs(3600))
        self.when.setCalendarPopup(True)
        self.when.setDisplayFormat("ddd dd MMM yyyy  hh:mm")
        form.addRow("Title", self.title)
        form.addRow("When", self.when)
        bb = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        form.addRow(bb)


# ---------------- app ----------------
def main():
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    # Ctrl+C in the terminal quits cleanly (a tiny timer lets Python notice the signal)
    signal.signal(signal.SIGINT, lambda *a: app.quit())
    QTimer(app, interval=200, timeout=lambda: None).start()
    try:
        store = Store()
    except mysql.connector.Error as err:
        QMessageBox.critical(None, "MySQL error",
                             f"Could not connect to MySQL:\n{err}\n\n"
                             "Set DB_HOST / DB_USER / DB_PASS environment variables if needed.")
        return 1

    pet = Pet(resolve_image())
    menu = QMenu()

    def refresh_tip():
        try:
            nxt = store.upcoming(1)
            pet.setToolTip(f"Next: {nxt[0]['title']} at {nxt[0]['start_time']:%a %H:%M}\n"
                           "Click = add meeting | Drag = move" if nxt
                           else "Click = add meeting | Drag = move | Right-click = menu")
        except mysql.connector.Error:
            pass

    def add_meeting():
        d = AddMeeting()
        if d.exec() and d.title.text().strip():
            store.add(d.title.text().strip(), d.when.dateTime().toPython())
            pet.say("Saved! I'll remind you 10 min before 📅")
            refresh_tip()

    def show_list():
        rows = store.upcoming()
        txt = "\n".join(f"{r['start_time']:%a %d %b %H:%M}  -  {r['title']}" for r in rows)
        QMessageBox.information(None, "Upcoming meetings", txt or "No upcoming meetings.")

    for label, fn in [("Add meeting…", add_meeting), ("Upcoming meetings", show_list),
                      ("Test reminder", lambda: pet.say("Meow! Stay hydrated 💧")),
                      ("Quit", app.quit)]:
        act = QAction(label, menu)
        act.triggered.connect(fn)
        menu.addAction(act)
    pet.on_click, pet.menu = add_meeting, menu

    pm = QPixmap(32, 32)
    pm.fill(Qt.transparent)
    pp = QPainter(pm)
    pp.setBrush(QColor("#FFB86B"))
    pp.drawEllipse(2, 2, 28, 28)
    pp.end()
    tray = QSystemTrayIcon(QIcon(pm))
    tray.setContextMenu(menu)
    tray.show()

    water_msgs = ["Time to drink some water! 💧", "Sip sip! Grab a glass of water 🥤",
                  "Hydration check! 💧"]
    break_msgs = ["Take a break! Stretch & look away from the screen 👀",
                  "Stand up and walk around for 5 minutes 🚶",
                  "Rest your eyes - look at something far away 🌳"]
    n = {"w": 0, "b": 0}

    def water():
        pet.say(water_msgs[n["w"] % 3]); n["w"] += 1

    def brk():
        pet.say(break_msgs[n["b"] % 3]); n["b"] += 1

    def check_meetings():
        try:
            for m in store.due():
                mins = max(1, round((m["start_time"] - datetime.now()).total_seconds() / 60))
                pet.say(f"📅 \"{m['title']}\" starts in {mins} min!")
            refresh_tip()
        except mysql.connector.Error:
            pass

    QTimer(app, interval=WATER_EVERY_MIN * 60_000, timeout=water).start()
    QTimer(app, interval=BREAK_EVERY_MIN * 60_000, timeout=brk).start()
    QTimer(app, interval=20_000, timeout=check_meetings).start()
    pet.show()
    check_meetings()
    pet.say("Hi! I'm Buddy 🐱 Click me to add a meeting!")
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())