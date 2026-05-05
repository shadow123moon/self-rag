# main.py
import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI
from database import engine, Base
from api.documents import router as documents_router
from api.health import router as health_router
from api.search import router as search_router
from api.chat import router as chat_router
from api.conversations import router as conversations_router
from models import document
from models import conversation
import logging

from services.bm25_service import build_bm25_index

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
@asynccontextmanager
async def lifespan(app: FastAPI):
    # 自动建表（同步操作放到线程池，避免阻塞事件循环）
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, lambda: Base.metadata.create_all(bind=engine))
    await loop.run_in_executor(None, build_bm25_index)
    yield

app = FastAPI(lifespan=lifespan)


app.include_router(health_router)
app.include_router(documents_router)
app.include_router(search_router)
app.include_router(chat_router)
app.include_router(conversations_router)
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
