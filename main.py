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
                               QFormLayout, QHBoxLayout, QLineEdit, QListWidget,
                               QListWidgetItem, QMenu, QMessageBox, QPushButton,
                               QSystemTrayIcon, QVBoxLayout, QWidget)

# ---------------- settings ----------------
WATER_EVERY_MIN = 45
BREAK_EVERY_MIN = 60
MEETING_WARN_MIN = 10
SHOW_SECONDS = 12
MEETING_SHOW_SECONDS = 30   # meeting alerts stay longer (they have buttons)
SNOOZE_MIN = 5              # snooze length for meeting alerts
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

    def get(self, mid):
        cur = self.con.cursor(dictionary=True)
        cur.execute("SELECT * FROM meetings WHERE id=%s", (mid,))
        return cur.fetchone()

    def update(self, mid, title, when):
        # notified=0 so an edited meeting reminds you again at its new time
        self.con.cursor().execute(
            "UPDATE meetings SET title=%s, start_time=%s, notified=0 WHERE id=%s",
            (title, when, mid))

    def delete(self, mid):
        self.con.cursor().execute("DELETE FROM meetings WHERE id=%s", (mid,))

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
    W = 270

    def __init__(self, pet):
        super().__init__(None, FLAGS)
        self.pet, self.text, self.tail_x = pet, "", 135
        self.H, self.can_snooze = 118, False
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.resize(self.W, self.H)
        style = ("QPushButton{background:#FFB86B;border:2px solid #4A3426;border-radius:10px;"
                 "color:#4A3426;font-weight:600;padding:2px 6px}"
                 "QPushButton:hover{background:#FFD29E}")
        self.snooze_btn = QPushButton(f"⏰ Snooze {SNOOZE_MIN} min", self)
        self.ok_btn = QPushButton("Got it", self)
        for b in (self.snooze_btn, self.ok_btn):
            b.setCursor(Qt.PointingHandCursor)
            b.setStyleSheet(style)
            b.hide()
        self.snooze_btn.clicked.connect(lambda: self.pet.snooze())
        self.ok_btn.clicked.connect(lambda: self.pet.dismiss())

    def show_text(self, text, can_snooze=False):
        self.text, self.can_snooze = text, can_snooze
        self.H = 150 if can_snooze else 118
        self.resize(self.W, self.H)
        y = self.H - 58
        self.snooze_btn.setGeometry(16, y, 150, 28)
        self.ok_btn.setGeometry(174, y, 80, 28)
        self.snooze_btn.setVisible(can_snooze)
        self.ok_btn.setVisible(can_snooze)
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
        p.drawText(QRectF(16, 10, self.W - 32, self.H - 44 - (28 if self.can_snooze else 0)), Qt.AlignCenter | Qt.TextWordWrap, self.text)


# ---------------- the tiny draggable cat ----------------
class Pet(QWidget):
    W, H = 120, 120

    def __init__(self, image):
        super().__init__(None, FLAGS)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.resize(self.W, self.H)
        self.t, self.alert, self.queue = 0, False, []
        self.current, self.on_snooze = None, None
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
    def say(self, text, meeting=None):
        self.queue.append((text, meeting))
        if not self.alert:
            self._next()

    def _next(self):
        if self.alert or not self.queue:
            return
        text, meeting = self.queue.pop(0)
        self.alert, self.current = True, meeting
        self.bubble.show_text(text, can_snooze=meeting is not None)
        self.hide_timer.start((MEETING_SHOW_SECONDS if meeting else SHOW_SECONDS) * 1000)

    def snooze(self):
        m = self.current
        self.dismiss()
        if m and self.on_snooze:
            self.on_snooze(m)
            self.say(f"Okay, I'll remind you again in {SNOOZE_MIN} min 😴")

    def dismiss(self):
        self.current = None
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
    def __init__(self, title="", when=None):
        super().__init__()
        self.setWindowTitle("Edit meeting" if title else "Add meeting")
        self.setWindowFlag(Qt.WindowStaysOnTopHint)
        form = QFormLayout(self)
        self.title = QLineEdit(title)
        start = (QDateTime.fromString(when.strftime("%Y-%m-%d %H:%M:%S"), "yyyy-MM-dd HH:mm:ss")
                 if when else QDateTime.currentDateTime().addSecs(3600))
        self.when = QDateTimeEdit(start)
        self.when.setCalendarPopup(True)
        self.when.setDisplayFormat("ddd dd MMM yyyy  hh:mm")
        form.addRow("Title", self.title)
        form.addRow("When", self.when)
        bb = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        form.addRow(bb)


# ---------------- manage meetings dialog ----------------
class Manage(QDialog):
    def __init__(self, store, on_change):
        super().__init__()
        self.store, self.on_change = store, on_change
        self.setWindowTitle("Manage meetings")
        self.setWindowFlag(Qt.WindowStaysOnTopHint)
        self.resize(430, 320)
        lay = QVBoxLayout(self)
        self.list = QListWidget()
        self.list.itemDoubleClicked.connect(lambda _: self.edit())
        lay.addWidget(self.list)
        row = QHBoxLayout()
        for label, fn in [("Edit", self.edit), ("Delete", self.delete), ("Close", self.accept)]:
            b = QPushButton(label)
            b.clicked.connect(fn)
            row.addWidget(b)
        lay.addLayout(row)
        self.refresh()

    def refresh(self):
        self.list.clear()
        rows = self.store.upcoming(100)
        for r in rows:
            it = QListWidgetItem(f"{r['start_time']:%a %d %b %H:%M}  -  {r['title']}")
            it.setData(Qt.UserRole, r)
            self.list.addItem(it)
        if not rows:
            self.list.addItem("No upcoming meetings.")

    def current(self):
        it = self.list.currentItem()
        return it.data(Qt.UserRole) if it else None

    def edit(self):
        r = self.current()
        if not r:
            return
        d = AddMeeting(r["title"], r["start_time"])
        if d.exec() and d.title.text().strip():
            self.store.update(r["id"], d.title.text().strip(), d.when.dateTime().toPython())
            self.refresh()
            self.on_change()

    def delete(self):
        r = self.current()
        if not r:
            return
        if QMessageBox.question(self, "Delete meeting", f"Delete \"{r['title']}\"?") == QMessageBox.Yes:
            self.store.delete(r["id"])
            self.refresh()
            self.on_change()


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

    def manage():
        Manage(store, refresh_tip).exec()

    for label, fn in [("Add meeting…", add_meeting), ("Manage meetings…", manage),
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

    def remind(m):
        secs = (m["start_time"] - datetime.now()).total_seconds()
        if secs >= 60:
            when = f"starts in {round(secs / 60)} min!"
        elif secs > -300:
            when = "is starting now!"
        else:
            when = f"started {abs(round(secs / 60))} min ago"
        pet.say(f"📅 \"{m['title']}\" {when}", meeting=m if secs > 0 else None)

    def snooze(m):
        def later():
            try:
                fresh = store.get(m["id"])      # may have been edited or deleted meanwhile
            except mysql.connector.Error:
                fresh = None
            if fresh:
                remind(fresh)
        QTimer.singleShot(SNOOZE_MIN * 60_000, later)

    pet.on_snooze = snooze

    def check_meetings():
        try:
            for m in store.due():
                remind(m)
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