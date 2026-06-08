from fastapi import APIRouter, Body, Request, Query
from fastapi.responses import HTMLResponse, JSONResponse
from contextlib import suppress
from pathlib import Path

from database.database import (
    get_access_logs,
    get_logs_count,
    get_cache_stats,
    get_top_resources,
    get_method_stats,
    get_cache_count,
)
from config.settings import PROXY_HOST, PROXY_PORT, DASHBOARD_PORT
from proxy.header_modifier import get_header_modifier
from security import get_access_control

router = APIRouter(prefix="/dashboard", tags=["dashboard"])

TEMPLATE_DIR = Path(__file__).parent / "templates"


def render_template(name: str, **kwargs) -> str:
    """简易 Jinja2 模板渲染"""
    from jinja2 import Environment, FileSystemLoader

    env = Environment(loader=FileSystemLoader(str(TEMPLATE_DIR)))
    template = env.get_template(name)
    return template.render(**kwargs)


# ========== 页面路由 ==========

@router.get("/", response_class=HTMLResponse)
async def dashboard_home(request: Request):
    """主页 - 系统概览"""
    stats = await get_cache_stats()
    top = await get_top_resources(10)
    recent_logs = await get_access_logs(limit=20)
    cache_count = await get_cache_count()
    methods = await get_method_stats()
    return render_template(
        "index.html",
        stats=stats,
        top_resources=top,
        recent_logs=recent_logs,
        cache_count=cache_count,
        methods=methods,
        proxy_host=PROXY_HOST,
        proxy_port=PROXY_PORT,
    )


@router.get("/logs", response_class=HTMLResponse)
async def dashboard_logs(
    request: Request,
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
):
    """日志页面 - 访问记录列表"""
    offset = (page - 1) * limit
    logs = await get_access_logs(limit=limit, offset=offset)
    total = await get_logs_count()
    total_pages = max(1, (total + limit - 1) // limit)
    return render_template(
        "logs.html",
        logs=logs,
        page=page,
        limit=limit,
        total=total,
        total_pages=total_pages,
    )


@router.get("/stats", response_class=HTMLResponse)
async def dashboard_stats(request: Request):
    """统计页面"""
    stats = await get_cache_stats()
    top = await get_top_resources(20)
    methods = await get_method_stats()
    return render_template(
        "stats.html",
        stats=stats,
        top_resources=top,
        methods=methods,
    )


# ========== API 路由 ==========

@router.get("/api/stats", response_class=JSONResponse)
async def api_stats():
    """获取统计信息 JSON"""
    stats = await get_cache_stats()
    top = await get_top_resources(10)
    methods = await get_method_stats()
    return {
        "total_requests": stats.total_requests,
        "cache_hits": stats.cache_hits,
        "cache_misses": stats.cache_misses,
        "hit_rate": stats.hit_rate,
        "cached_resources": stats.cached_resources,
        "total_cache_size_bytes": stats.total_cache_size,
        "top_resources": [{"url": r.url, "count": r.access_count} for r in top],
        "methods": [{"method": m.method, "count": m.count} for m in methods],
    }


@router.get("/api/logs", response_class=JSONResponse)
async def api_logs(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    """获取日志 JSON"""
    logs = await get_access_logs(limit=limit, offset=offset)
    total = await get_logs_count()
    return {
        "total": total,
        "logs": [
            {
                "id": log.id,
                "access_time": log.access_time,
                "client_ip": log.client_ip,
                "target_url": log.target_url,
                "method": log.method,
                "status_code": log.status_code,
                "cache_hit": log.cache_hit,
                "response_size": log.response_size,
                "duration_ms": log.duration_ms,
            }
            for log in logs
        ],
    }


@router.get("/api/health", response_class=JSONResponse)
async def api_health():
    """健康检查"""
    from database.database import get_logs_count as _count, get_cache_count as _ccount
    try:
        log_count = await _count()
        cache_count = await _ccount()
        return {
            "status": "running",
            "db_connected": True,
            "log_count": log_count,
            "cache_count": cache_count,
        }
    except Exception as e:
        return {
            "status": "error",
            "db_connected": False,
            "error": str(e),
        }


@router.get("/api/security/status", response_class=JSONResponse)
async def api_security_status():
    """获取黑名单/白名单状态"""
    return get_access_control().get_status()


@router.post("/api/security/blacklist", response_class=JSONResponse)
async def api_add_blacklist_rule(pattern: str = Body(..., embed=True)):
    """添加黑名单规则"""
    access_control = get_access_control()
    added = await access_control.add_blacklist_rule(pattern)
    await access_control.save_rules()
    return {"ok": added, "status": access_control.get_status()}


@router.delete("/api/security/blacklist", response_class=JSONResponse)
async def api_remove_blacklist_rule(pattern: str = Query(...)):
    """删除黑名单规则"""
    access_control = get_access_control()
    removed = await access_control.remove_blacklist_rule(pattern)
    await access_control.save_rules()
    return {"ok": removed, "status": access_control.get_status()}


@router.post("/api/security/whitelist", response_class=JSONResponse)
async def api_add_whitelist_rule(pattern: str = Body(..., embed=True)):
    """添加白名单规则"""
    access_control = get_access_control()
    added = await access_control.add_whitelist_rule(pattern)
    await access_control.save_rules()
    return {"ok": added, "status": access_control.get_status()}


@router.delete("/api/security/whitelist", response_class=JSONResponse)
async def api_remove_whitelist_rule(pattern: str = Query(...)):
    """删除白名单规则"""
    access_control = get_access_control()
    removed = await access_control.remove_whitelist_rule(pattern)
    await access_control.save_rules()
    return {"ok": removed, "status": access_control.get_status()}


@router.post("/api/security/reload", response_class=JSONResponse)
async def api_reload_security_rules():
    """从配置文件热加载黑名单/白名单规则"""
    from cache import get_cache_manager

    access_control = get_access_control()
    await access_control.reload()
    with suppress(Exception):
        await get_cache_manager().clear()
    return {"ok": True, "status": access_control.get_status()}


@router.get("/api/headers/rules", response_class=JSONResponse)
async def api_header_rules():
    """获取请求头改写规则"""
    return get_header_modifier().get_rules()


@router.put("/api/headers/rules", response_class=JSONResponse)
async def api_update_header_rules(rules: dict = Body(...)):
    """替换请求头改写规则"""
    header_modifier = get_header_modifier()
    return {"ok": True, "rules": header_modifier.save(rules)}


@router.post("/api/headers/reload", response_class=JSONResponse)
async def api_reload_header_rules():
    """从配置文件重新读取请求头改写规则"""
    return {"ok": True, "rules": get_header_modifier().load()}


@router.post("/api/headers/profile", response_class=JSONResponse)
async def api_set_header_profile(
    profile_query: str | None = Query(None, alias="profile"),
    payload: dict | None = Body(None),
):
    """切换模拟客户端档案，例如 tenant / landlord / admin"""
    profile = profile_query or (payload or {}).get("profile")
    if not profile:
        return JSONResponse(
            {"ok": False, "error": "missing profile; use ?profile=admin or JSON {\"profile\":\"admin\"}"},
            status_code=400,
        )
    header_modifier = get_header_modifier()
    return {"ok": True, "rules": header_modifier.set_active_profile(profile)}
