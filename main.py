from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from supabase import create_client, Client
import httpx
from bs4 import BeautifulSoup
import google.generativeai as genai
import os
from datetime import datetime
from typing import Dict, Optional, List
import json
import logging

logging.basicConfig(level=logging.INFO)

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

genai.configure(api_key=os.environ.get("GEMINI_API_KEY", ""))
# JSON出力を安定させるため、モデル設定を明示
model = genai.GenerativeModel("gemini-1.5-flash")

SUPABASE_URL = os.environ.get("SUPABASE_URL", "").strip().rstrip("/")
if SUPABASE_URL.endswith("/rest/v1"): 
    SUPABASE_URL = SUPABASE_URL[:-8]
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "").strip()

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

class ItemRequest(BaseModel):
    project_name: str
    category: str
    title: Optional[str] = "新規製品"
    url: Optional[str] = ""
    image_data: Optional[str] = None
    price: int = 0
    is_decided: bool = False
    user_ratings: Dict[str, int] = {}
    icon: str = "🏠"

@app.post("/api/items")
async def add_item(req: ItemRequest):
    data = req.model_dump()
    data["updated_at"] = datetime.now().isoformat()
    return supabase.table("items").insert(data).execute().data

@app.get("/api/items")
def get_items():
    return supabase.table("items").select("*").order("updated_at", desc=True).execute().data

@app.put("/api/items/{item_id}")
async def update_item(item_id: int, req: dict):
    req["updated_at"] = datetime.now().isoformat()
    return supabase.table("items").update(req).eq("id", item_id).execute().data

@app.post("/api/extract")
async def extract_info(url: str):
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            res = await client.get(url, follow_redirects=True)
            soup = BeautifulSoup(res.text, 'html.parser')
            text = soup.get_text()[:2500] # トークン節約
        
        prompt = f"""
        以下のWebページのテキストから、製品名と価格を抽出し、必ず以下のJSONフォーマットのみを出力してください。
        URL: {url}
        テキスト: {text}
        出力形式: {{"title": "製品名", "price": 1234}}
        ※価格は数字のみ。不明な場合は0にしてください。マークダウン(```json)は不要です。
        """
        response = model.generate_content(prompt)
        result_text = response.text.replace('```json', '').replace('```', '').strip()
        return {"result": json.loads(result_text)}
    except Exception as e:
        logging.error(f"抽出エラー: {e}")
        return {"result": {"title": "取得失敗 (手動で入力してください)", "price": 0}}

class RecommendRequest(BaseModel):
    category: str
    existing_items: List[str]

@app.post("/api/recommend")
async def recommend(req: RecommendRequest):
    try:
        items_str = ", ".join(req.existing_items)
        prompt = f"""
        ユーザーはカテゴリ「{req.category}」について以下の製品を検討中です: {items_str}。
        これらと競合する、または比較すべき別の優れた製品を3つ提案してください。
        必ず以下のJSON配列フォーマットのみを出力してください。マークダウン不要。
        [
            {{"title": "おすすめ製品名1", "price": 10000, "url": "#", "comment": "AI提案: 〜〜の理由でおすすめ"}},
            ...
        ]
        """
        response = model.generate_content(prompt)
        result_text = response.text.replace('```json', '').replace('```', '').strip()
        return {"suggestions": json.loads(result_text)}
    except Exception as e:
        logging.error(f"提案エラー: {e}")
        return {"suggestions": []}
