"""
app.py  -  THE SERVER (Flask)
=============================
This is the file you run:   python app.py

What it does:
  1. Shows the web page (index.html)
  2. Receives pictures from the page (webcam frames or uploaded photos)
  3. Uses detector.py to find the faces
  4. Saves every result (photo + count + time) in a small database (results.db)
  5. Sends the results back to the page so they can be displayed
"""

import csv
import io
import os
import sqlite3
from contextlib import closing
from datetime import datetime

import cv2
from flask import Flask, Response, jsonify, render_template, request, url_for

import detector

# ---------------------------------------------------------------
# SETTINGS
# ---------------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "results.db")                 # database file
SNAPSHOT_DIR = os.path.join(BASE_DIR, "static", "snapshots")   # saved result pictures
os.makedirs(SNAPSHOT_DIR, exist_ok=True)

# The slider on the page goes 1..5. Each level maps to a detector setting.
# Higher sensitivity -> LOWER min_neighbors -> more faces found.
SENSITIVITY_TO_NEIGHBORS = {1: 9, 2: 7, 3: 5, 4: 4, 5: 3}

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024   # max upload size: 16 MB


# ---------------------------------------------------------------
# DATABASE HELPERS (SQLite = a database stored in one simple file)
# ---------------------------------------------------------------
def get_db():
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row   # lets us read columns by name
    return connection


def init_db():
    """Create the table the first time the program runs."""
    with closing(get_db()) as db:
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS detections (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT    NOT NULL,
                source     TEXT    NOT NULL,
                face_count INTEGER NOT NULL,
                image_file TEXT    NOT NULL
            )
            """
        )
        db.commit()


init_db()


# ---------------------------------------------------------------
# SMALL HELPER FUNCTIONS
# ---------------------------------------------------------------
def read_sensitivity(value):
    """Turn the slider value into the min_neighbors setting (safe against bad input)."""
    try:
        level = int(value)
    except (TypeError, ValueError):
        level = 3
    level = max(1, min(5, level))
    return SENSITIVITY_TO_NEIGHBORS[level]


def save_result(image, faces, source):
    """Draw boxes, save the picture to disk, add a row to the database."""
    annotated = detector.draw_faces(image.copy(), faces)

    now = datetime.now()
    filename = f"{now.strftime('%Y%m%d_%H%M%S_%f')}_{source}.jpg"
    cv2.imwrite(os.path.join(SNAPSHOT_DIR, filename), annotated)

    created_at = now.strftime("%Y-%m-%d %H:%M:%S")
    with closing(get_db()) as db:
        cursor = db.execute(
            "INSERT INTO detections (created_at, source, face_count, image_file) VALUES (?, ?, ?, ?)",
            (created_at, source, len(faces), filename),
        )
        db.commit()
        record_id = cursor.lastrowid

    return {
        "id": record_id,
        "created_at": created_at,
        "source": source,
        "count": len(faces),
        "faces": faces,
        "image_url": url_for("static", filename=f"snapshots/{filename}"),
    }


def error(message, status=400):
    return jsonify({"error": message}), status


# ---------------------------------------------------------------
# ROUTES  (a route = a web address the page can talk to)
# ---------------------------------------------------------------
@app.route("/")
def home():
    return render_template("index.html")


@app.route("/api/detect", methods=["POST"])
def api_detect():
    """Used by the LIVE webcam: quick detection, nothing is saved."""
    data = request.get_json(silent=True) or {}
    image = detector.decode_base64_image(data.get("image"))
    if image is None:
        return error("Could not read the camera picture.")

    faces = detector.find_faces(image, read_sensitivity(data.get("sensitivity")))
    return jsonify({"count": len(faces), "faces": faces})


@app.route("/api/snapshot", methods=["POST"])
def api_snapshot():
    """Used by the 'Save Snapshot' button: detect, save the picture, log the result."""
    data = request.get_json(silent=True) or {}
    image = detector.decode_base64_image(data.get("image"))
    if image is None:
        return error("Could not read the camera picture.")

    faces = detector.find_faces(image, read_sensitivity(data.get("sensitivity")))
    return jsonify(save_result(image, faces, "webcam"))


@app.route("/api/upload", methods=["POST"])
def api_upload():
    """Used by the 'Upload Photo' tab: detect faces in an uploaded picture."""
    photo = request.files.get("photo")
    if photo is None or photo.filename == "":
        return error("Please choose a photo first.")

    image = detector.decode_bytes_image(photo.read())
    if image is None:
        return error("That file is not a valid image. Please use JPG or PNG.")

    image = detector.limit_size(image, 1200)
    faces = detector.find_faces(image, read_sensitivity(request.form.get("sensitivity")))
    return jsonify(save_result(image, faces, "upload"))


@app.route("/api/history")
def api_history():
    """Returns the latest 50 results + overall statistics for the dashboard."""
    with closing(get_db()) as db:
        rows = db.execute("SELECT * FROM detections ORDER BY id DESC LIMIT 50").fetchall()
        totals = db.execute(
            "SELECT COUNT(*) AS scans, COALESCE(SUM(face_count), 0) AS faces FROM detections"
        ).fetchone()

    records = [
        {
            "id": row["id"],
            "created_at": row["created_at"],
            "source": row["source"],
            "face_count": row["face_count"],
            "image_url": url_for("static", filename=f"snapshots/{row['image_file']}"),
        }
        for row in rows
    ]

    scans, faces = totals["scans"], totals["faces"]
    stats = {
        "total_scans": scans,
        "total_faces": faces,
        "average": round(faces / scans, 2) if scans else 0,
        "last_scan": records[0]["created_at"] if records else "-",
    }
    return jsonify({"records": records, "stats": stats})


@app.route("/api/export")
def api_export():
    """Download all results as a CSV file (opens in Excel)."""
    with closing(get_db()) as db:
        rows = db.execute("SELECT id, created_at, source, face_count FROM detections ORDER BY id").fetchall()

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["ID", "Date & Time", "Source", "Faces Found"])
    for row in rows:
        writer.writerow([row["id"], row["created_at"], row["source"], row["face_count"]])

    return Response(
        buffer.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=face_detection_results.csv"},
    )


@app.route("/api/clear", methods=["POST"])
def api_clear():
    """Delete all saved results and pictures."""
    with closing(get_db()) as db:
        db.execute("DELETE FROM detections")
        db.commit()

    for name in os.listdir(SNAPSHOT_DIR):
        if name.lower().endswith(".jpg"):
            os.remove(os.path.join(SNAPSHOT_DIR, name))

    return jsonify({"ok": True})


@app.errorhandler(413)
def too_large(_):
    return error("That file is too large (maximum 16 MB).", 413)


# ---------------------------------------------------------------
# START THE SERVER
# ---------------------------------------------------------------
if __name__ == "__main__":
    print("\n  Face Detection software is running!")
    print("  Open this address in Chrome or Edge:  http://127.0.0.1:8000\n")
    app.run(host="127.0.0.1", port=8000, debug=False)
