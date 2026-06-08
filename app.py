"""入口模块

启动方式：
    1. 先初始化数据库：python database/init_db.py
    2. 启动服务：python app.py
    3. 打开管理面板：http://localhost:8000
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import uvicorn
from fastapi import FastAPI
from contextlib import asynccontextmanager, suppress

from config.settings import DASHBOARD_HOST, DASHBOARD_PORT, PROXY_HOST, PROXY_PORT
from proxy import ProxyServer


@asynccontextmanager
async def lifespan(app: FastAPI):
    from database.database import init_db

    await init_db()
    proxy_server = ProxyServer(host=PROXY_HOST, port=PROXY_PORT)
    await proxy_server.start()
    app.state.proxy_server = proxy_server
    print(f"数据库已初始化")
    print(f"HTTP代理启动: http://{PROXY_HOST}:{PROXY_PORT}")
    print(f"Dashboard 启动: http://{DASHBOARD_HOST}:{DASHBOARD_PORT}")
    try:
        yield
    finally:
        await proxy_server.stop()


app = FastAPI(
    title="HTTP代理缓存服务器",
    description="HTTP Proxy Cache Server Dashboard",
    version="1.0.0",
    lifespan=lifespan,
)

from dashboard.routes import router as dashboard_router

app.include_router(dashboard_router)


async def _reload_security_rules() -> dict:
    from cache import get_cache_manager
    from security import get_access_control

    access_control = get_access_control()
    await access_control.reload()
    with suppress(Exception):
        await get_cache_manager().clear()
    return {"ok": True, "status": access_control.get_status()}


@app.get("/")
async def root():
    from fastapi.responses import RedirectResponse

    return RedirectResponse(url="/dashboard/")


@app.post("/api/security/reload")
async def api_security_reload_alias():
    return await _reload_security_rules()


if __name__ == "__main__":
    uvicorn.run(
        "app:app",
        host=DASHBOARD_HOST,
        port=DASHBOARD_PORT,
        reload=False,
    )


#  演示命令：

#  curl.exe -X POST "http://127.0.0.1:8000/dashboard/api/headers/profile?profile=admin"

  #恢复租客视角：
#   curl.exe -X POST "http://127.0.0.1:8000/dashboard/api/headers/profile?profile=tenant"

