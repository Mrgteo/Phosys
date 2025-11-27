"""
WebSocket连接管理器
管理所有客户端连接，支持状态广播
"""

import logging
import asyncio
from typing import Dict, Set, Optional
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
        
        # ✅ 修复：添加异步锁保护去重逻辑
        self._status_lock = asyncio.Lock()
        
        # ✅ 修复：为每个文件维护独立的进度更新队列，确保顺序执行
        self._file_queues: Dict[str, asyncio.Queue] = {}  # {file_id: Queue}
        self._queue_tasks: Dict[str, asyncio.Task] = {}  # {file_id: Task}
        self._queue_lock = asyncio.Lock()  # 保护队列字典的锁
    
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
    
    async def _get_or_create_queue(self, file_id: str) -> asyncio.Queue:
        """获取或创建文件对应的进度更新队列"""
        async with self._queue_lock:
            if file_id not in self._file_queues:
                # 创建新队列
                queue = asyncio.Queue()
                self._file_queues[file_id] = queue
                
                # 启动队列处理任务
                task = asyncio.create_task(self._process_file_queue(file_id, queue))
                self._queue_tasks[file_id] = task
                logger.debug(f"为文件 {file_id} 创建进度更新队列和处理任务")
            
            return self._file_queues[file_id]
    
    async def _process_file_queue(self, file_id: str, queue: asyncio.Queue):
        """
        处理文件进度更新队列，确保按顺序执行
        
        每个文件有独立的队列处理任务，保证进度更新的顺序性
        """
        try:
            while True:
                # 从队列获取更新消息
                update_data = await queue.get()
                
                # 如果收到 None，表示停止处理
                if update_data is None:
                    break
                
                # 处理进度更新
                await self._send_file_status_internal(
                    file_id=update_data['file_id'],
                    status=update_data['status'],
                    progress=update_data['progress'],
                    message=update_data['message'],
                    extra_data=update_data.get('extra_data')
                )
                
                # 标记任务完成
                queue.task_done()
        
        except asyncio.CancelledError:
            logger.debug(f"文件 {file_id} 的队列处理任务被取消")
        except Exception as e:
            logger.error(f"处理文件 {file_id} 的进度更新队列时出错: {e}")
        finally:
            # 清理队列和任务
            async with self._queue_lock:
                self._file_queues.pop(file_id, None)
                self._queue_tasks.pop(file_id, None)
            logger.debug(f"已清理文件 {file_id} 的进度更新队列")
    
    async def _send_file_status_internal(self, file_id: str, status: str, progress: int = 0, 
                                         message: str = "", extra_data: dict = None):
        """
        内部方法：实际发送文件状态更新（带异步锁保护的去重逻辑）
        """
        async with self._status_lock:
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
        
        # 构建消息数据
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
            async with self._status_lock:
                self.last_progress.pop(file_id, None)
                self.last_status.pop(file_id, None)
            
            # 停止队列处理任务
            await self._stop_file_queue(file_id)
    
    async def _stop_file_queue(self, file_id: str):
        """停止文件队列处理任务"""
        async with self._queue_lock:
            if file_id in self._file_queues:
                queue = self._file_queues[file_id]
                # 发送 None 信号停止处理
                try:
                    await queue.put(None)
                except Exception as e:
                    logger.error(f"停止文件 {file_id} 的队列时出错: {e}")
    
    async def send_file_status(self, file_id: str, status: str, progress: int = 0, 
                               message: str = "", extra_data: dict = None):
        """
        发送文件状态更新（使用队列机制确保顺序执行）
        
        将进度更新放入文件对应的队列中，由独立的处理任务按顺序执行
        这样可以避免多个文件同时转写时的进度更新乱序问题
        """
        try:
            # 获取或创建文件对应的队列
            queue = await self._get_or_create_queue(file_id)
            
            # 将更新消息放入队列
            await queue.put({
                'file_id': file_id,
                'status': status,
                'progress': progress,
                'message': message,
                'extra_data': extra_data
            })
        except Exception as e:
            logger.error(f"将文件 {file_id} 的进度更新放入队列时出错: {e}")
            # 如果队列机制失败，回退到直接发送（但可能丢失顺序保证）
            await self._send_file_status_internal(file_id, status, progress, message, extra_data)
    
    async def shutdown(self):
        """
        关闭连接管理器，清理所有队列和任务
        
        应在应用关闭时调用，确保所有资源正确释放
        """
        logger.info("正在关闭WebSocket连接管理器...")
        
        # 停止所有队列处理任务
        async with self._queue_lock:
            file_ids = list(self._file_queues.keys())
        
        # 停止所有队列
        for file_id in file_ids:
            await self._stop_file_queue(file_id)
        
        # 等待所有任务完成
        async with self._queue_lock:
            tasks = list(self._queue_tasks.values())
        
        if tasks:
            # 等待所有任务完成或取消
            await asyncio.gather(*tasks, return_exceptions=True)
        
        logger.info("WebSocket连接管理器已关闭")


# 全局连接管理器实例
ws_manager = ConnectionManager()

