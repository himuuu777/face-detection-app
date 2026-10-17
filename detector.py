"""
detector.py  -  THE "BRAIN" OF THE PROJECT
==========================================
This file only does face detection. It knows nothing about websites.
app.py calls the functions in this file.

Technology: OpenCV + Haar Cascade (a pre-trained face model that comes with OpenCV).
"""

import os

import base64
import cv2
import numpy as np


# ---------------------------------------------------------------
# STEP 1: LOAD THE FACE MODEL (only once, when the program starts)
# ---------------------------------------------------------------
# The Haar Cascade face model is part of OpenCV 4. OpenCV 5 removed it,
# so this project needs version 4 (requirements.txt already asks for it).
if not hasattr(cv2, "CascadeClassifier"):
    raise RuntimeError(
        "This project needs OpenCV version 4. Please run these two commands:\n"
        "    pip uninstall -y opencv-python opencv-contrib-python opencv-python-headless\n"
        '    pip install "opencv-python<5"'
    )

CASCADE_PATH = os.path.join(cv2.data.haarcascades, "haarcascade_frontalface_default.xml")
_face_model = cv2.CascadeClassifier(CASCADE_PATH)

if _face_model.empty():
    raise RuntimeError(
        "Could not load the face detection model. "
        "Try:  pip install --upgrade opencv-python"
    )


# ---------------------------------------------------------------
# STEP 2: TURN UPLOADED DATA INTO AN IMAGE OpenCV CAN USE
# ---------------------------------------------------------------
def decode_bytes_image(raw_bytes):
    """Raw file bytes -> OpenCV image. Returns None if it is not a valid image."""
    if not raw_bytes:
        return None
    array = np.frombuffer(raw_bytes, dtype=np.uint8)
    return cv2.imdecode(array, cv2.IMREAD_COLOR)


def decode_base64_image(data_url):
    """
    The webcam page sends pictures as text like 'data:image/jpeg;base64,/9j/4AAQ...'.
    This turns that text back into an OpenCV image.
    """
    if not data_url or not isinstance(data_url, str):
        return None
    if "," in data_url:
        data_url = data_url.split(",", 1)[1]  # remove the 'data:image/jpeg;base64,' part
    try:
        raw_bytes = base64.b64decode(data_url)
    except Exception:
        return None
    return decode_bytes_image(raw_bytes)


def limit_size(image, max_width=1200):
    """Shrink very big photos so detection stays fast."""
    height, width = image.shape[:2]
    if width <= max_width:
        return image
    scale = max_width / width
    return cv2.resize(image, (max_width, int(height * scale)), interpolation=cv2.INTER_AREA)


# ---------------------------------------------------------------
# STEP 3: FIND THE FACES
# ---------------------------------------------------------------
def find_faces(image, min_neighbors=5):
    """
    Returns a list of faces. Each face looks like {"x": 10, "y": 20, "w": 80, "h": 80}
    (x, y = top-left corner, w = width, h = height).

    min_neighbors = how many overlapping detections are needed to accept a face.
        LOWER  -> finds more faces, but more false alarms
        HIGHER -> fewer false alarms, but may miss real faces
    """
    # Grey image: the model only needs brightness, not colour (also faster)
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

    # Improve contrast so faces in poor light are easier to find
    gray = cv2.equalizeHist(gray)

    # Ignore tiny detections: smaller than 10% of the picture's shorter side
    height, width = gray.shape
    smallest_face = max(30, int(min(height, width) * 0.10))

    found = _face_model.detectMultiScale(
        gray,
        scaleFactor=1.1,                 # how much the picture shrinks on each scan
        minNeighbors=min_neighbors,
        minSize=(smallest_face, smallest_face),
    )

    return [{"x": int(x), "y": int(y), "w": int(w), "h": int(h)} for (x, y, w, h) in found]


# ---------------------------------------------------------------
# STEP 4: DRAW GREEN BOXES ON THE PICTURE
# ---------------------------------------------------------------
def draw_faces(image, faces):
    """Draws a green box + label on every face and the total count at the top-left."""
    green = (80, 200, 60)        # OpenCV colours are Blue, Green, Red
    font = cv2.FONT_HERSHEY_SIMPLEX

    for number, face in enumerate(faces, start=1):
        x, y, w, h = face["x"], face["y"], face["w"], face["h"]
        cv2.rectangle(image, (x, y), (x + w, y + h), green, 3)

        label = f"Face {number}"
        (text_w, text_h), _ = cv2.getTextSize(label, font, 0.6, 2)
        top = max(0, y - text_h - 10)
        cv2.rectangle(image, (x, top), (x + text_w + 10, top + text_h + 10), green, -1)
        cv2.putText(image, label, (x + 5, top + text_h + 3), font, 0.6, (255, 255, 255), 2)

    cv2.putText(image, f"Faces: {len(faces)}", (12, 32), font, 0.9, (0, 0, 255), 2)
    return image
