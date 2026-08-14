from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from supabase import create_client, Client
import httpx
from bs4 import BeautifulSoup
import google.generativeai as genai
import os
import logging

logging.basicConfig(level=logging.INFO)

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 環境変数の取得（末尾の余分な /rest/v1 や / を自動で削る安全対策）
SUPABASE_URL = os.environ.get("SUPABASE_URL", "").strip().rstrip("/")
if SUPABASE_URL.endswith("/rest/v1"):
    SUPABASE_URL = SUPABASE_URL[:-8]

SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "").strip()
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
genai.configure(api_key=GEMINI_API_KEY)

class ItemRequest(BaseModel):
    project_name: str
    category: str
    url: str
    comment: str = ""

@app.post("/api/items")
async def add_item(req: ItemRequest):
    title, image_url = "タイトル取得中...", ""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            res = await client.get(req.url, follow_redirects=True)
            soup = BeautifulSoup(res.text, 'html.parser')
            og_title = soup.find("meta", property="og:title")
            og_image = soup.find("meta", property="og:image")
            title = og_title["content"] if og_title else (soup.title.string if soup.title else "タイトルなし")
            image_url = og_image["content"] if og_image else ""
    except Exception as e:
        logging.error(f"OGP取得スキップ: {e}")

    data = {
        "project_name": req.project_name,
        "category": req.category,
        "url": req.url,
        "title": title,
        "image_url": image_url,
        "comment": req.comment
    }
    try:
        response = supabase.table("items").insert(data).execute()
        return response.data
    except Exception as e:
        logging.error(f"DB保存エラー: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/items")
def get_items():
    try:
        response = supabase.table("items").select("*").order("created_at", desc=True).execute()
        return response.data
    except Exception as e:
        logging.error(f"DB取得エラー: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/recommend")
def recommend_items(req: dict):
    items = supabase.table("items").select("title, comment").eq("category", req.get("category")).execute()
    item_texts = [f"- {item['title']} (メモ: {item['comment']})" for item in items.data]
    
    prompt = f"「{req.get('category')}」の候補とメモに基づき、ユーザーの好みを分析し、次に見るべきAmazon検索キーワードを3つ提案して: \n" + "\n".join(item_texts)
    
    model = genai.GenerativeModel("gemini-2.5-flash")
    response = model.generate_content(prompt)
    return {"recommendation": response.text}
