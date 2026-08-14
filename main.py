from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from supabase import create_client, Client
import os
from datetime import datetime
from typing import Dict

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

SUPABASE_URL = os.environ.get("SUPABASE_URL", "").strip().rstrip("/")
if SUPABASE_URL.endswith("/rest/v1"): SUPABASE_URL = SUPABASE_URL[:-8]
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "").strip()

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

class ItemRequest(BaseModel):
    project_name: str
    category: str
    url: str
    comment: str = ""
    icon: str = "🏠"
    price: int = 0
    status: str = "検討中"
    is_decided: bool = False
    user_ratings: Dict[str, int] = {}

@app.post("/api/items")
async def add_item(req: ItemRequest):
    data = req.dict()
    data["updated_at"] = datetime.now().isoformat()
    # 新規登録時はタイトルを仮でURLに
    data["title"] = req.url 
    response = supabase.table("items").insert(data).execute()
    return response.data

@app.get("/api/items")
def get_items():
    return supabase.table("items").select("*").order("updated_at", desc=True).execute().data
