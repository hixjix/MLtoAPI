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
from typing import Dict, Any, List, Optional
import uuid

nest_asyncio.apply()

# ★★★ 請填入您的 Ngrok Token ★★★
NGROK_TOKEN = "請填入您的 Ngrok Token" 
ngrok.set_auth_token(NGROK_TOKEN)

DB_NAME = "water_system.db"
CURRENT_TARGET_CONFIG = {"target": "NH4_1209"}

# ★新增：任務佇列與結果暫存區 (簡易版 Message Queue)
ANALYSIS_TASKS = [] 
ANALYSIS_RESULTS = {}

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

# --- 資料模型 ---
class RawData(BaseModel):
    device_id: str; timestamp: str; ph: float; cod: float

class MLResult(BaseModel):
    timestamp: str; raw_id: int; is_pollution: bool; predicted_value: float; target_name: str; top_features: Dict[str, float]

class TargetConfig(BaseModel):
    target_name: str

# ★新增：LIME/PI 請求與結果模型
class AnalysisRequest(BaseModel):
    type: str  # "LIME" or "PI"
    target_name: str
    params: Dict[str, Any] # LIME 放 timestamp, PI 放 start/end date

class AnalysisResult(BaseModel):
    task_id: str
    status: str
    data: Dict[str, Any]

# --- API 路由 ---

@app.post("/api/sensor/upload")
def upload_sensor_data(data: RawData):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("INSERT INTO raw_sensor_data (timestamp, device_id, ph, cod) VALUES (?, ?, ?, ?)", (data.timestamp, data.device_id, data.ph, data.cod))
    conn.commit()
    conn.close()
    return {"status": "saved"}

# [ML端使用] 獲取最新 Sensor 資料 + ★領取分析任務
@app.get("/api/ml/fetch_latest")
def get_latest_raw_data():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM raw_sensor_data ORDER BY id DESC LIMIT 1")
    row = cursor.fetchone()
    conn.close()
    
    # 取出所有待處理任務，並清空佇列 (一次領完)
    pending_tasks = ANALYSIS_TASKS.copy()
    ANALYSIS_TASKS.clear()

    response = {
        "current_target": CURRENT_TARGET_CONFIG["target"],
        "pending_tasks": pending_tasks # ★ 告訴 ML 有這些額外工作要做
    }

    if row:
        response.update({"id": row[0], "timestamp": row[1], "device_id": row[2], "ph": row[3], "cod": row[4]})
    else:
        response["error"] = "no_data"
        
    return response

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

# [ML端使用] ★ 回傳分析結果 (LIME/PI)
@app.post("/api/ml/submit_analysis")
def submit_analysis_result(res: AnalysisResult):
    ANALYSIS_RESULTS[res.task_id] = res.data
    return {"status": "received"}

# [前端使用] ★ 發送 LIME/PI 請求
@app.post("/api/analysis/request")
def request_analysis(req: AnalysisRequest):
    task_id = str(uuid.uuid4())
    task = {
        "id": task_id,
        "type": req.type,
        "target": req.target_name,
        "params": req.params
    }
    ANALYSIS_TASKS.append(task)
    return {"status": "queued", "task_id": task_id}

# [前端使用] ★ 查詢分析結果
@app.get("/api/analysis/result/{task_id}")
def get_analysis_result(task_id: str):
    if task_id in ANALYSIS_RESULTS:
        return {"status": "completed", "data": ANALYSIS_RESULTS[task_id]}
    return {"status": "processing"}

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
