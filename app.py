#!/usr/bin/env python3
"""GPU Hot - Real-time NVIDIA GPU Monitoring Dashboard (FastAPI + AsyncIO)"""

import asyncio
import logging
import aiohttp
import re
import time as _time
from contextlib import asynccontextmanager
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, JSONResponse
from core import config
from version import __version__

# Setup logging
logging.basicConfig(
    level=logging.DEBUG if config.DEBUG else logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def app_lifespan(app: FastAPI):
    """Initialize and tear down background services for the app."""
    rrd_buffer = getattr(app.state, 'rrd_buffer', None)
    if rrd_buffer is None:
        yield
        return

    await rrd_buffer.init_db()
    app.state.rrd_task = asyncio.create_task(rrd_buffer.consolidate_loop())

    try:
        yield
    finally:
        task = getattr(app.state, 'rrd_task', None)
        if task is None:
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


app = FastAPI(title="GPU Hot", version=__version__, lifespan=app_lifespan)
_STATIC_VER = str(int(_time.time()))

# Serve static files
app.mount("/static", StaticFiles(directory="static"), name="static")

# Mode selection
if config.MODE == 'hub':
    # Hub mode: aggregate data from multiple nodes
    if not config.NODE_URLS:
        raise ValueError("Hub mode requires NODE_URLS environment variable")
    
    logger.info("Starting GPU Hot in HUB mode (FastAPI)")
    logger.info(f"Connecting to {len(config.NODE_URLS)} node(s): {config.NODE_URLS}")
    
    from core.hub import Hub
    from core.hub_handlers import register_hub_handlers
    
    hub = Hub(config.NODE_URLS)
    register_hub_handlers(app, hub)
    monitor_or_hub = hub
    app.state.rrd_buffer = None
    app.state.rrd_task = None

else:
    # Default mode: monitor local GPUs and serve dashboard
    logger.info("Starting GPU Hot (FastAPI)")
    logger.info(f"Node name: {config.NODE_NAME}")
    
    from core.monitor import GPUMonitor
    from core.handlers import register_handlers
    from core.rrd_buffer import RRDBuffer
    
    monitor = GPUMonitor()
    rrd_buffer = RRDBuffer()
    app.state.rrd_buffer = rrd_buffer
    app.state.rrd_task = None
    register_handlers(app, monitor, rrd_buffer)
    monitor_or_hub = monitor


@app.get("/")
async def index():
    """Serve the main dashboard with cache-busting query strings"""
    with open("templates/index.html", "r") as f:
        html = f.read()
    html = re.sub(
        r'((?:src|href)="/static/[^"]+?)(")',
        lambda m: f'{m.group(1)}?v={_STATIC_VER}{m.group(2)}',
        html
    )
    return HTMLResponse(content=html, headers={"Cache-Control": "no-store"})


@app.get("/api/gpu-data")
async def api_gpu_data():
    """REST API endpoint for GPU data"""
    if config.MODE == 'hub':
        return {"gpus": {}, "timestamp": "hub_mode"}
    
    if hasattr(monitor_or_hub, 'get_gpu_data'):
        return {"gpus": await monitor_or_hub.get_gpu_data(), "timestamp": "async"}
    
    return {"gpus": {}, "timestamp": "no_data"}


@app.get("/api/rrd/{gpu_id}")
async def api_rrd(gpu_id: str, range: str = "1min"):
    """REST API endpoint for historical RRD-style GPU data."""
    valid_ranges = {'1min', '5min', '30min', '2hr', '1day'}
    if range not in valid_ranges:
        return JSONResponse({'error': 'invalid range'}, status_code=400)

    rrd_buffer = getattr(app.state, 'rrd_buffer', None)
    if rrd_buffer is None:
        return JSONResponse({'error': 'rrd unavailable'}, status_code=404)

    loop = asyncio.get_running_loop()
    data = await loop.run_in_executor(None, rrd_buffer.query, gpu_id, range)
    return JSONResponse(data)


def compare_versions(current, latest):
    """Compare semantic versions. Returns True if latest > current"""
    try:
        current_parts = [int(x) for x in current.split('.')]
        latest_parts = [int(x) for x in latest.split('.')]
        
        # Pad to same length
        max_len = max(len(current_parts), len(latest_parts))
        current_parts += [0] * (max_len - len(current_parts))
        latest_parts += [0] * (max_len - len(latest_parts))
        
        # Compare each part
        for c, l in zip(current_parts, latest_parts):
            if l > c:
                return True
            elif l < c:
                return False
        
        return False  # Versions are equal
    except (ValueError, AttributeError):
        return False


@app.get("/api/version")
async def api_version():
    """Get current version and check for updates from GitHub"""
    current_version = __version__
    
    try:
        # Check GitHub for latest release
        async with aiohttp.ClientSession() as session:
            async with session.get(
                "https://api.github.com/repos/psalias2006/gpu-hot/releases/latest",
                timeout=aiohttp.ClientTimeout(total=5)
            ) as response:
                if response.status == 200:
                    data = await response.json()
                    latest_version = data.get("tag_name", "").lstrip("v")
                    
                    # Only show update if latest > current
                    update_available = compare_versions(current_version, latest_version) if latest_version else False
                    
                    return JSONResponse({
                        "current": current_version,
                        "latest": latest_version,
                        "update_available": update_available,
                        "release_url": data.get("html_url", "")
                    })
    except Exception as e:
        logger.debug(f"Failed to check for updates: {e}")
    
    # Return current version even if GitHub check fails
    return JSONResponse({
        "current": current_version,
        "latest": None,
        "update_available": False,
        "release_url": None
    })


if __name__ == '__main__':
    import uvicorn
    try:
        logger.info(f"Server running on {config.HOST}:{config.PORT}")
        uvicorn.run(app, host=config.HOST, port=config.PORT, log_level="info")
    finally:
        if hasattr(monitor_or_hub, 'shutdown'):
            asyncio.run(monitor_or_hub.shutdown())
