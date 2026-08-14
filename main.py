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

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

genai.configure(api_key=os.environ.get("GEMINI_API_KEY"))
model = genai.GenerativeModel("gemini-1.5-flash")

supabase: Client = create_client(os.environ.get("SUPABASE_URL"), os.environ.get("SUPABASE_KEY"))

class ItemRequest(BaseModel):
    project_name: str
    category: str
    title: Optional[str] = "新規製品"
    url: Optional[str] = ""
    image_data: Optional[str] = None
    price: int = 0
    is_decided: bool = False
    user_ratings: Dict[str, int] = {}

@app.post("/api/items")
async def add_item(req: ItemRequest):
    data = req.dict()
    data["updated_at"] = datetime.now().isoformat()
    return supabase.table("items").insert(data).execute().data

@app.get("/api/items")
def get_items():
    return supabase.table("items").select("*").order("updated_at", desc=True).execute().data

@app.put("/api/items/{item_id}")
async def update_item(item_id: int, req: dict):
    return supabase.table("items").update(req).eq("id", item_id).execute().data

@app.post("/api/extract")
async def extract_info(url: str):
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            res = await client.get(url, follow_redirects=True)
            soup = BeautifulSoup(res.text, 'html.parser')
            text = soup.get_text()[:2000]
        prompt = f"このWebページの製品名と価格(数字のみ)をJSONで抽出して。URL: {url}\nテキスト: {text}\nフォーマット: {{\"title\": \"...\", \"price\": 1234}}"
        response = model.generate_content(prompt)
        return {"result": response.text}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/recommend")
async def recommend(category: str, existing_items: List[str]):
    prompt = f"カテゴリ「{category}」の検討リスト: {', '.join(existing_items)}。このカテゴリで他に検討すべき類似製品を3つ提案して。"
    response = model.generate_content(prompt)
    return {"suggestion": response.text}
