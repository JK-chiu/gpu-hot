"""Async WebSocket handlers for hub mode"""

import asyncio
import logging
import json
from fastapi import WebSocket

logger = logging.getLogger(__name__)

# Global WebSocket connections
websocket_connections = set()

def register_hub_handlers(app, hub):
    """Register FastAPI WebSocket handlers for hub mode"""
    
    @app.websocket("/socket.io/")
    async def websocket_endpoint(websocket: WebSocket):
        await websocket.accept()
        websocket_connections.add(websocket)
        logger.debug('Dashboard client connected')

        try:
            # Keep connection alive
            while True:
                await websocket.receive_text()
        except Exception as e:
            logger.debug(f'Dashboard client disconnected: {e}')
        finally:
            websocket_connections.discard(websocket)


async def hub_loop(hub, connections):
    """Async background loop that emits aggregated cluster data"""
    logger.info("Hub monitoring loop started")
    
    while hub.running:
        try:
            cluster_data = await hub.get_cluster_data()
            
            # Send to all connected clients
            if connections:
                disconnected = set()
                for websocket in connections:
                    try:
                        await websocket.send_text(json.dumps(cluster_data))
                    except:
                        disconnected.add(websocket)
                
                # Remove disconnected clients
                connections.difference_update(disconnected)
                
        except Exception as e:
            logger.error(f"Error in hub loop: {e}")
        
        # Match node update rate for real-time responsiveness
        await asyncio.sleep(0.5)

