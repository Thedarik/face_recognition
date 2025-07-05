from fastapi import FastAPI, UploadFile, File, HTTPException
from pydantic import BaseModel
import sqlite3
import os
from datetime import datetime
import shutil
from pathlib import Path
import face_recognition  # pip install face_recognition
from typing import Optional

app = FastAPI()

UPLOAD_DIR = "uploads"
Path(UPLOAD_DIR).mkdir(exist_ok=True)

def init_db():
    conn = sqlite3.connect("attendance.db")
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS students (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            first_name TEXT NOT NULL,
            last_name TEXT NOT NULL,
            student_id TEXT UNIQUE NOT NULL,
            photo_path TEXT NOT NULL
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS attendance (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            FOREIGN KEY (student_id) REFERENCES students (student_id)
        )
    """)
    conn.commit()
    conn.close()

init_db()

class StudentCreate(BaseModel):
    first_name: str
    last_name: str
    student_id: str

@app.post("/students")
async def add_student(first_name: str, last_name: str, student_id: str, photo: UploadFile = File(...)):
    file_extension = photo.filename.split(".")[-1]
    photo_path = f"{UPLOAD_DIR}/{student_id}.{file_extension}"

    with open(photo_path, "wb") as buffer:
        shutil.copyfileobj(photo.file, buffer)

    conn = sqlite3.connect("attendance.db")
    cursor = conn.cursor()
    try:
        cursor.execute(
            "INSERT INTO students (first_name, last_name, student_id, photo_path) VALUES (?, ?, ?, ?)",
            (first_name, last_name, student_id, photo_path)
        )
        conn.commit()
    except sqlite3.IntegrityError:
        conn.close()
        raise HTTPException(status_code=400, detail="Bu student ID allaqachon mavjud")
    conn.close()

    return {"message": "O‘quvchi muvaffaqiyatli qo‘shildi", "student_id": student_id}

@app.get("/students")
async def get_students():
    conn = sqlite3.connect("attendance.db")
    cursor = conn.cursor()
    cursor.execute("SELECT first_name, last_name, student_id, photo_path FROM students")
    students = cursor.fetchall()
    conn.close()

    return [
        {
            "first_name": s[0],
            "last_name": s[1],
            "student_id": s[2],
            "photo_path": s[3]
        } for s in students
    ]

@app.post("/attendance")
async def take_attendance(photo: UploadFile = File(...)):
    file_extension = photo.filename.split(".")[-1]
    timestamp = datetime.now().isoformat().replace(":", "_")
    temp_photo_path = f"{UPLOAD_DIR}/attendance_temp_{timestamp}.{file_extension}"

    with open(temp_photo_path, "wb") as buffer:
        shutil.copyfileobj(photo.file, buffer)

    try:
        input_image = face_recognition.load_image_file(temp_photo_path)
        input_encodings = face_recognition.face_encodings(input_image)
        if not input_encodings:
            os.remove(temp_photo_path)
            raise HTTPException(status_code=400, detail="Yuz topilmadi.")
        input_encoding = input_encodings[0]
    except Exception as e:
        os.remove(temp_photo_path)
        raise HTTPException(status_code=500, detail=f"Yuzni o‘qishda xatolik: {str(e)}")

    conn = sqlite3.connect("attendance.db")
    cursor = conn.cursor()
    cursor.execute("SELECT student_id, photo_path FROM students")
    students = cursor.fetchall()

    best_match_id = None
    best_distance = 1.0
    tolerance = 0.45  # qat'iylik darajasi: past bo‘lsa, aniqlik yuqori

    for student_id, photo_path in students:
        try:
            known_image = face_recognition.load_image_file(photo_path)
            known_encodings = face_recognition.face_encodings(known_image)
            if not known_encodings:
                continue
            known_encoding = known_encodings[0]

            distance = face_recognition.face_distance([known_encoding], input_encoding)[0]
            if distance < best_distance:
                best_distance = distance
                best_match_id = student_id
        except Exception:
            continue

    os.remove(temp_photo_path)

    if best_distance >= tolerance:
        raise HTTPException(
            status_code=404,
            detail=f"Yuz mos kelmadi. Eng yaqin moslik: {round(best_distance, 3)}"
        )

    cursor.execute("SELECT first_name, last_name FROM students WHERE student_id = ?", (best_match_id,))
    student = cursor.fetchone()
    conn.commit()
    conn.close()

    return {
        "message": "Yo‘qlama qayd etildi",
        "student_id": best_match_id,
        "first_name": student[0],
        "last_name": student[1],
        "distance": round(best_distance, 4)
    }
