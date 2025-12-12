!pip install pyngrok

import os
import sqlite3
import time
import json
import threading
import uvicorn
import nest_asyncio
from pyngrok import ngrok
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Dict, Any


nest_asyncio.apply()

# ★★★ 請填入您的 Ngrok Token ★★★
NGROK_TOKEN = "36biCzr0Ibfu5xePl72Io9vxx1U_3u4PyckBZK54ZEBzg1743"
ngrok.set_auth_token(NGROK_TOKEN)

DB_NAME = "water_system.db"

# ★新增：全域變數，紀錄目前選定的目標 (預設值)
CURRENT_TARGET_CONFIG = {"target": "NH4_1209"}

def init_db():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('CREATE TABLE IF NOT EXISTS raw_sensor_data (id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT, device_id TEXT, ph REAL, cod REAL)')
    cursor.execute('CREATE TABLE IF NOT EXISTS ml_results (id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT, raw_id INTEGER, is_pollution BOOLEAN, data_json TEXT)')
    conn.commit()
    conn.close()

init_db()

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

class RawData(BaseModel):
    device_id: str; timestamp: str; ph: float; cod: float
class MLResult(BaseModel):
    timestamp: str; raw_id: int; is_pollution: bool; predicted_value: float; target_name: str; top_features: Dict[str, float]
class TargetConfig(BaseModel):
    target_name: str

# --- API 路由 ---

@app.post("/api/sensor/upload")
def upload_sensor_data(data: RawData):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("INSERT INTO raw_sensor_data (timestamp, device_id, ph, cod) VALUES (?, ?, ?, ?)", (data.timestamp, data.device_id, data.ph, data.cod))
    conn.commit()
    conn.close()
    return {"status": "saved"}

# ★修改：ML Worker 在抓資料時，順便告訴它現在的目標是誰
@app.get("/api/ml/fetch_latest")
def get_latest_raw_data():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM raw_sensor_data ORDER BY id DESC LIMIT 1")
    row = cursor.fetchone()
    conn.close()
    if row:
        return {
            "id": row[0], "timestamp": row[1], "device_id": row[2],
            "ph": row[3], "cod": row[4],
            "current_target": CURRENT_TARGET_CONFIG["target"] # 回傳目前設定的目標
        }
    return {"error": "no_data", "current_target": CURRENT_TARGET_CONFIG["target"]}

@app.post("/api/ml/submit_result")
def submit_ml_result(data: MLResult):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    dashboard_payload = {"val": data.predicted_value, "target": data.target_name, "feats": data.top_features}
    cursor.execute("INSERT INTO ml_results (timestamp, raw_id, is_pollution, data_json) VALUES (?, ?, ?, ?)",
                   (data.timestamp, data.raw_id, data.is_pollution, json.dumps(dashboard_payload)))
    conn.commit()
    conn.close()
    return {"status": "saved"}

@app.get("/api/dashboard/monitor")
def get_dashboard_data():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT m.timestamp, m.data_json FROM ml_results m ORDER BY m.id DESC LIMIT 1")
    row = cursor.fetchone()
    conn.close()
    if row:
        data = json.loads(row[1])
        return {"timestamp": row[0], "value": data["val"], "target": data["target"], "top_features": data["feats"]}
    return {"timestamp": "Waiting...", "value": 0, "target": "--", "top_features": {}}

# ★新增：讓前端設定目標的 API
@app.post("/api/config/set_target")
def set_target(config: TargetConfig):
    CURRENT_TARGET_CONFIG["target"] = config.target_name
    print(f"🔄 目標已切換為: {config.target_name}")
    return {"status": "success", "target": config.target_name}

def run_server():
    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="error")

if __name__ == "__main__":
    public_url = ngrok.connect(8000).public_url
    print(f"🎉 API 已上線: {public_url}")
    threading.Thread(target=run_server, daemon=True).start()
    while True: time.sleep(1)
