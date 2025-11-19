"""
WebSocket连接管理器
管理所有客户端连接，支持状态广播
"""

import logging
from typing import Dict, Set
from fastapi import WebSocket

logger = logging.getLogger(__name__)


class ConnectionManager:
    """WebSocket连接管理器"""
    
    def __init__(self):
        # 存储所有活跃的WebSocket连接
        self.active_connections: Set[WebSocket] = set()
        # 存储每个文件ID对应的订阅连接
        self.file_subscriptions: Dict[str, Set[WebSocket]] = {}
        # 存储每个文件的上一次进度值，用于去重（避免发送重复的进度更新）
        self.last_progress: Dict[str, int] = {}  # {file_id: last_progress}
        # 存储每个文件的上一次状态，用于去重
        self.last_status: Dict[str, str] = {}  # {file_id: last_status}
    
    async def connect(self, websocket: WebSocket):
        """接受新的WebSocket连接"""
        await websocket.accept()
        self.active_connections.add(websocket)
        logger.info(f"WebSocket连接已建立，当前连接数: {len(self.active_connections)}")
    
    def disconnect(self, websocket: WebSocket):
        """移除WebSocket连接"""
        self.active_connections.discard(websocket)
        # 从所有文件订阅中移除
        for file_id in list(self.file_subscriptions.keys()):
            self.file_subscriptions[file_id].discard(websocket)
            if not self.file_subscriptions[file_id]:
                del self.file_subscriptions[file_id]
        logger.info(f"WebSocket连接已断开，当前连接数: {len(self.active_connections)}")
    
    def subscribe_file(self, websocket: WebSocket, file_id: str):
        """订阅特定文件的状态更新"""
        if file_id not in self.file_subscriptions:
            self.file_subscriptions[file_id] = set()
        self.file_subscriptions[file_id].add(websocket)
    
    async def broadcast(self, message: dict):
        """向所有连接广播消息"""
        disconnected = set()
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception as e:
                logger.error(f"发送消息失败: {e}")
                disconnected.add(connection)
        
        # 清理断开的连接
        for connection in disconnected:
            self.disconnect(connection)
    
    async def send_to_file_subscribers(self, file_id: str, message: dict):
        """向订阅特定文件的连接发送消息"""
        if file_id not in self.file_subscriptions:
            return
        
        disconnected = set()
        for connection in self.file_subscriptions[file_id]:
            try:
                await connection.send_json(message)
            except Exception as e:
                logger.error(f"发送文件状态失败: {e}")
                disconnected.add(connection)
        
        # 清理断开的连接
        for connection in disconnected:
            self.disconnect(connection)
    
    async def send_file_status(self, file_id: str, status: str, progress: int = 0, 
                               message: str = "", extra_data: dict = None):
        """
        发送文件状态更新（带去重逻辑，避免发送重复的进度值）
        
        只有当进度值增加、状态变化或完成时才发送，避免长音频处理时进度条反复跳
        """
        # 获取上一次的进度和状态
        last_progress = self.last_progress.get(file_id, -1)
        last_status = self.last_status.get(file_id, "")
        
        # 判断是否需要发送更新：
        # 1. 进度值增加（严格大于）
        # 2. 状态变化（completed/error 状态总是发送）
        # 3. 完成状态总是发送
        progress_increased = progress > last_progress
        status_changed = status != last_status
        is_final_status = status in ['completed', 'error', 'deleted']
        
        # 如果进度没有增加、状态没变化且不是最终状态，则跳过发送（去重）
        if not progress_increased and not status_changed and not is_final_status:
            # 忽略重复的进度更新
            return
        
        # 更新记录的上一次进度和状态
        self.last_progress[file_id] = progress
        self.last_status[file_id] = status
        
        data = {
            "type": "file_status",
            "file_id": file_id,
            "status": status,
            "progress": progress,
            "message": message
        }
        if extra_data:
            data.update(extra_data)
        
        # 广播给所有连接（因为文件列表页面需要看到所有文件状态）
        await self.broadcast(data)
        
        # 如果文件已完成或出错，清理记录（释放内存）
        if is_final_status:
            self.last_progress.pop(file_id, None)
            self.last_status.pop(file_id, None)


# 全局连接管理器实例
ws_manager = ConnectionManager()

