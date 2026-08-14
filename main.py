from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from supabase import create_client, Client
import httpx
from bs4 import BeautifulSoup
import google.generativeai as genai
import os

app = FastAPI()

# CORS設定（すべての外部サイトからのアクセスを許可）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
genai.configure(api_key=GEMINI_API_KEY)

class ItemRequest(BaseModel):
    category: str
    url: str
    comment: str = ""

class RecommendRequest(BaseModel):
    category: str

@app.post("/api/items")
async def add_item(req: ItemRequest):
    title, image_url = "タイトルなし", ""
    try:
        async with httpx.AsyncClient() as client:
            res = await client.get(req.url, follow_redirects=True)
            soup = BeautifulSoup(res.text, 'html.parser')
            
            og_title = soup.find("meta", property="og:title")
            og_image = soup.find("meta", property="og:image")
            title = og_title["content"] if og_title else (soup.title.string if soup.title else "タイトルなし")
            image_url = og_image["content"] if og_image else ""
    except Exception as e:
        print(f"OGP取得エラー: {e}")

    data = {
        "category": req.category,
        "url": req.url,
        "title": title,
        "image_url": image_url,
        "comment": req.comment
    }
    response = supabase.table("items").insert(data).execute()
    return response.data

@app.get("/api/items")
def get_items(category: str = None):
    query = supabase.table("items").select("*").order("created_at", desc=True)
    if category:
        query = query.eq("category", category)
    response = query.execute()
    return response.data

@app.post("/api/recommend")
def recommend_items(req: RecommendRequest):
    items = supabase.table("items").select("title, comment").eq("category", req.category).execute()
    if not items.data:
        return {"recommendation": "まだ商品が登録されていません。"}
    
    item_texts = [f"- {item['title']} (メモ: {item['comment']})" for item in items.data]
    prompt = f"以下の「{req.category}」の候補リストとメモから、このユーザーが好むテイストを分析し、次に見るべきおすすめの照明のスタイルと、Amazonで検索すべきキーワードを3つ提案してください。\n" + "\n".join(item_texts)
    
    model = genai.GenerativeModel("gemini-2.5-flash")
    response = model.generate_content(prompt)
    
    return {"recommendation": response.text}
