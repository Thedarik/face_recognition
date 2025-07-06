from fastapi import FastAPI, UploadFile, File, HTTPException, Form
import sqlite3
import os
from datetime import datetime
import shutil
from pathlib import Path
import face_recognition
import json

app = FastAPI()

# 📂 Fayllar uchun papkalar
UPLOAD_DIR = "uploads"
GROUPS_JSON = "groups_json"
Path(UPLOAD_DIR).mkdir(exist_ok=True)
Path(GROUPS_JSON).mkdir(exist_ok=True)

# 🛠️ Baza yaratish
def init_db():
    conn = sqlite3.connect("attendance.db")
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS groups (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            group_id TEXT UNIQUE NOT NULL,
            group_name TEXT NOT NULL
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS students (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            first_name TEXT NOT NULL,
            last_name TEXT NOT NULL,
            student_id TEXT UNIQUE NOT NULL,
            photo_path TEXT NOT NULL,
            group_id TEXT,
            FOREIGN KEY (group_id) REFERENCES groups (group_id)
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

# ➕ Guruh yaratish
@app.post("/groups")
async def create_group(
    group_id: str = Form(...),
    group_name: str = Form(...)
):
    conn = sqlite3.connect("attendance.db")
    cursor = conn.cursor()

    try:
        cursor.execute("INSERT INTO groups (group_id, group_name) VALUES (?, ?)", (group_id, group_name))
        conn.commit()
    except sqlite3.IntegrityError:
        conn.close()
        raise HTTPException(status_code=400, detail="Bu guruh ID allaqachon mavjud.")
    conn.close()

    group_data = {
        "group_id": group_id,
        "group_name": group_name,
        "students": []
    }

    group_file_path = os.path.join(GROUPS_JSON, f"{group_id}.json")
    with open(group_file_path, "w", encoding="utf-8") as f:
        json.dump(group_data, f, ensure_ascii=False, indent=4)

    return {"message": "Guruh muvaffaqiyatli yaratildi", "group_id": group_id}

# ➕ O‘quvchi qo‘shish
@app.post("/students")
async def add_student(
    first_name: str = Form(...),
    last_name: str = Form(...),
    student_id: str = Form(...),
    group_id: str = Form(...),
    photo: UploadFile = File(...)
):
    conn = sqlite3.connect("attendance.db")
    cursor = conn.cursor()

    cursor.execute("SELECT 1 FROM groups WHERE group_id = ?", (group_id,))
    if not cursor.fetchone():
        conn.close()
        raise HTTPException(status_code=400, detail="Bunday group_id mavjud emas.")

    file_extension = photo.filename.split(".")[-1]
    photo_path = f"{UPLOAD_DIR}/{student_id}.{file_extension}"

    with open(photo_path, "wb") as buffer:
        shutil.copyfileobj(photo.file, buffer)

    try:
        cursor.execute("""
            INSERT INTO students (first_name, last_name, student_id, photo_path, group_id)
            VALUES (?, ?, ?, ?, ?)
        """, (first_name, last_name, student_id, photo_path, group_id))
        conn.commit()
    except sqlite3.IntegrityError:
        conn.close()
        raise HTTPException(status_code=400, detail="Bu student ID allaqachon mavjud.")
    conn.close()

    # JSON faylga ham qo‘shamiz
    group_file_path = os.path.join(GROUPS_JSON, f"{group_id}.json")
    if os.path.exists(group_file_path):
        with open(group_file_path, "r+", encoding="utf-8") as f:
            data = json.load(f)
            data["students"].append({
                "first_name": first_name,
                "last_name": last_name,
                "student_id": student_id,
                "photo_path": photo_path
            })
            f.seek(0)
            json.dump(data, f, ensure_ascii=False, indent=4)
            f.truncate()

    return {"message": "O‘quvchi qo‘shildi", "student_id": student_id}

# 📋 Barcha studentlar
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

# 📸 Yuz orqali yo‘qlama olish
@app.post("/attendance")
async def take_attendance(photo: UploadFile = File(...)):
    file_extension = photo.filename.split(".")[-1]
    timestamp = datetime.now().isoformat().replace(":", "_")
    temp_photo_path = f"{UPLOAD_DIR}/temp_{timestamp}.{file_extension}"

    with open(temp_photo_path, "wb") as buffer:
        shutil.copyfileobj(photo.file, buffer)

    try:
        input_image = face_recognition.load_image_file(temp_photo_path)
        input_encodings = face_recognition.face_encodings(input_image)
        if not input_encodings:
            raise HTTPException(status_code=400, detail="Yuz topilmadi.")
        input_encoding = input_encodings[0]
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Yuzni o‘qishda xatolik: {str(e)}")

    conn = sqlite3.connect("attendance.db")
    cursor = conn.cursor()
    cursor.execute("SELECT student_id, photo_path FROM students")
    students = cursor.fetchall()

    best_match_id = None
    best_distance = 1.0
    tolerance = 0.45

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
        except:
            continue

    os.remove(temp_photo_path)

    if best_distance >= tolerance or not best_match_id:
        raise HTTPException(status_code=404, detail=f"Yuz mos kelmadi. Eng yaqin: {round(best_distance, 3)}")

    cursor.execute("INSERT INTO attendance (student_id, timestamp) VALUES (?, ?)", (best_match_id, datetime.now().isoformat()))
    cursor.execute("SELECT first_name, last_name FROM students WHERE student_id = ?", (best_match_id,))
    student = cursor.fetchone()
    conn.commit()
    conn.close()

    return {
        "message": "Yo‘qlama bajarildi",
        "student_id": best_match_id,
        "first_name": student[0],
        "last_name": student[1],
        "distance": round(best_distance, 4)
    }

# 📅 Studentning barcha yo‘qlama tarixini olish
@app.get("/attendance/history/{student_id}")
async def get_attendance_history(student_id: str):
    conn = sqlite3.connect("attendance.db")
    cursor = conn.cursor()
    cursor.execute("SELECT timestamp FROM attendance WHERE student_id = ? ORDER BY timestamp DESC", (student_id,))
    rows = cursor.fetchall()
    conn.close()

    if not rows:
        return {
            "student_id": student_id,
            "message": "Bu student hali yo‘qlamadan o‘tmagan.",
            "attendance_history": []
        }

    return {
        "student_id": student_id,
        "attendance_history": [row[0] for row in rows]
    }

# ❌ Student o‘chirish
# ❌ Student o‘chirish (SQLite + JSON)
@app.delete("/students/{student_id}")
async def delete_student(student_id: str):
    conn = sqlite3.connect("attendance.db")
    cursor = conn.cursor()

    # Studentni topamiz
    cursor.execute("SELECT photo_path, group_id FROM students WHERE student_id = ?", (student_id,))
    result = cursor.fetchone()
    if not result:
        conn.close()
        raise HTTPException(status_code=404, detail="Student topilmadi")

    photo_path, group_id = result

    # Photo faylni o‘chirish
    if os.path.exists(photo_path):
        os.remove(photo_path)

    # SQLite dan studentni o‘chirish
    cursor.execute("DELETE FROM students WHERE student_id = ?", (student_id,))
    conn.commit()
    conn.close()

    # groups_json/<group_id>.json dan o‘quvchini o‘chirish
    group_file_path = os.path.join(GROUPS_JSON, f"{group_id}.json")
    if os.path.exists(group_file_path):
        with open(group_file_path, "r+", encoding="utf-8") as f:
            data = json.load(f)
            # student_id bo‘yicha filterlab yangilaymiz
            data["students"] = [s for s in data["students"] if s["student_id"] != student_id]
            f.seek(0)
            json.dump(data, f, ensure_ascii=False, indent=4)
            f.truncate()

    return {"message": "O‘quvchi o‘chirildi", "student_id": student_id}


# ❌ Guruh o‘chirish
@app.delete("/groups/{group_id}")
async def delete_group(group_id: str):
    conn = sqlite3.connect("attendance.db")
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM groups WHERE group_id = ?", (group_id,))
    if not cursor.fetchone():
        conn.close()
        raise HTTPException(status_code=404, detail="Guruh topilmadi")

    cursor.execute("DELETE FROM groups WHERE group_id = ?", (group_id,))
    conn.commit()
    conn.close()

    group_file_path = os.path.join(GROUPS_JSON, f"{group_id}.json")
    if os.path.exists(group_file_path):
        os.remove(group_file_path)

    return {"message": "Guruh o‘chirildi", "group_id": group_id}

# 📁 Barcha guruhlar (JSON fayllardan)
@app.get("/groups_json")
async def get_all_group_files():
    result = []
    for filename in os.listdir(GROUPS_JSON):
        if filename.endswith(".json"):
            file_path = os.path.join(GROUPS_JSON, filename)
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    result.append(data)
            except:
                continue
    return result



# ❌ Barcha studentlarni va ularning ma'lumotlarini tozalovchi API
# 🧹 To'liq tizimni tozalovchi API
@app.delete("/clear_all_data")
async def clear_all_data():
    conn = sqlite3.connect("attendance.db")
    cursor = conn.cursor()

    # Barcha yo'qlama yozuvlarini o'chirish
    cursor.execute("DELETE FROM attendance")

    # Barcha studentlarni o'chirish
    cursor.execute("DELETE FROM students")

    # Barcha guruhlarni o'chirish
    cursor.execute("DELETE FROM groups")
    conn.commit()

    # uploads/ ichidagi barcha fayllarni o'chirish
    for filename in os.listdir(UPLOAD_DIR):
        file_path = os.path.join(UPLOAD_DIR, filename)
        if os.path.isfile(file_path):
            os.remove(file_path)

    # groups_json/ ichidagi barcha JSON fayllarni o'chirish
    for filename in os.listdir(GROUPS_JSON):
        if filename.endswith(".json"):
            file_path = os.path.join(GROUPS_JSON, filename)
            if os.path.isfile(file_path):
                os.remove(file_path)

    conn.close()

    return {"message": "Tizim tozalandi: barcha studentlar, guruhlar, rasmlar, yo‘qlamalar va JSON fayllar o‘chirildi."}

