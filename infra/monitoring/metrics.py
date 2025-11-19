"""
性能监控和指标收集模块
用于追踪系统性能、资源使用和请求统计
"""

import time
import psutil
import logging
import threading
from typing import Dict, List, Optional
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


@dataclass
class RequestMetrics:
    """请求指标"""
    endpoint: str
    method: str
    status_code: int
    duration: float  # 秒
    timestamp: float


@dataclass
class SystemMetrics:
    """系统指标"""
    cpu_percent: float
    memory_percent: float
    memory_used_mb: float
    memory_available_mb: float
    active_threads: int
    timestamp: float = field(default_factory=time.time)


class MetricsCollector:
    """指标收集器"""
    
    def __init__(self, history_size: int = 1000):
        """
        初始化指标收集器
        
        Args:
            history_size: 历史记录保留数量
        """
        self.history_size = history_size
        
        # 请求指标
        self.request_history: deque = deque(maxlen=history_size)
        self.request_lock = threading.Lock()
        
        # 系统指标
        self.system_history: deque = deque(maxlen=history_size)
        self.system_lock = threading.Lock()
        
        # 统计计数器
        self.counters = {
            'total_requests': 0,
            'failed_requests': 0,
            'active_requests': 0,
            'total_transcriptions': 0,
            'successful_transcriptions': 0,
            'failed_transcriptions': 0
        }
        self.counter_lock = threading.Lock()
        
        # 启动系统监控线程
        self.monitoring = True
        self.monitor_thread = threading.Thread(
            target=self._system_monitor_loop,
            daemon=True,
            name='SystemMonitor'
        )
        self.monitor_thread.start()
        
        logger.info("指标收集器已启动")
    
    def record_request(self, endpoint: str, method: str, status_code: int, duration: float):
        """记录请求"""
        with self.request_lock:
            metrics = RequestMetrics(
                endpoint=endpoint,
                method=method,
                status_code=status_code,
                duration=duration,
                timestamp=time.time()
            )
            self.request_history.append(metrics)
        
        # 更新计数器
        with self.counter_lock:
            self.counters['total_requests'] += 1
            if status_code >= 400:
                self.counters['failed_requests'] += 1
    
    def increment_active_requests(self):
        """增加活跃请求数"""
        with self.counter_lock:
            self.counters['active_requests'] += 1
    
    def decrement_active_requests(self):
        """减少活跃请求数"""
        with self.counter_lock:
            self.counters['active_requests'] = max(0, self.counters['active_requests'] - 1)
    
    def record_transcription(self, success: bool):
        """记录转写任务"""
        with self.counter_lock:
            self.counters['total_transcriptions'] += 1
            if success:
                self.counters['successful_transcriptions'] += 1
            else:
                self.counters['failed_transcriptions'] += 1
    
    def _system_monitor_loop(self):
        """系统监控循环（后台线程）"""
        while self.monitoring:
            try:
                # 收集系统指标
                cpu_percent = psutil.cpu_percent(interval=1)
                memory = psutil.virtual_memory()
                
                metrics = SystemMetrics(
                    cpu_percent=cpu_percent,
                    memory_percent=memory.percent,
                    memory_used_mb=memory.used / (1024 * 1024),
                    memory_available_mb=memory.available / (1024 * 1024),
                    active_threads=threading.active_count()
                )
                
                with self.system_lock:
                    self.system_history.append(metrics)
                
                time.sleep(30)  # 每30秒收集一次
                
            except Exception as e:
                logger.error(f"系统监控错误: {e}")
                time.sleep(60)
    
    def get_request_stats(self, time_window: int = 3600) -> Dict:
        """
        获取请求统计
        
        Args:
            time_window: 时间窗口（秒），默认1小时
        """
        cutoff_time = time.time() - time_window
        
        with self.request_lock:
            recent_requests = [r for r in self.request_history if r.timestamp >= cutoff_time]
        
        if not recent_requests:
            return {
                'total': 0,
                'success': 0,
                'error': 0,
                'avg_duration': 0,
                'max_duration': 0,
                'min_duration': 0
            }
        
        success_requests = [r for r in recent_requests if r.status_code < 400]
        error_requests = [r for r in recent_requests if r.status_code >= 400]
        
        durations = [r.duration for r in recent_requests]
        
        return {
            'total': len(recent_requests),
            'success': len(success_requests),
            'error': len(error_requests),
            'avg_duration': sum(durations) / len(durations),
            'max_duration': max(durations),
            'min_duration': min(durations),
            'requests_per_minute': len(recent_requests) / (time_window / 60)
        }
    
    def get_system_stats(self) -> Dict:
        """获取当前系统统计"""
        with self.system_lock:
            if not self.system_history:
                return {}
            
            latest = self.system_history[-1]
            
            # 计算平均值（最近10个采样点）
            recent_samples = list(self.system_history)[-10:]
            avg_cpu = sum(s.cpu_percent for s in recent_samples) / len(recent_samples)
            avg_memory = sum(s.memory_percent for s in recent_samples) / len(recent_samples)
            
            return {
                'current': {
                    'cpu_percent': latest.cpu_percent,
                    'memory_percent': latest.memory_percent,
                    'memory_used_mb': latest.memory_used_mb,
                    'memory_available_mb': latest.memory_available_mb,
                    'active_threads': latest.active_threads
                },
                'average': {
                    'cpu_percent': avg_cpu,
                    'memory_percent': avg_memory
                }
            }
    
    def get_transcription_stats(self) -> Dict:
        """获取转写统计"""
        with self.counter_lock:
            total = self.counters['total_transcriptions']
            success = self.counters['successful_transcriptions']
            failed = self.counters['failed_transcriptions']
            
            return {
                'total': total,
                'successful': success,
                'failed': failed,
                'success_rate': (success / total * 100) if total > 0 else 0
            }
    
    def get_all_stats(self) -> Dict:
        """获取所有统计信息"""
        with self.counter_lock:
            counters = self.counters.copy()
        
        return {
            'counters': counters,
            'requests': self.get_request_stats(),
            'system': self.get_system_stats(),
            'transcriptions': self.get_transcription_stats()
        }
    
    def check_resource_limits(self, max_memory_percent: float = 90.0) -> tuple:
        """
        检查资源限制
        
        Returns:
            (is_ok, message)
        """
        with self.system_lock:
            if not self.system_history:
                return True, "No system data"
            
            latest = self.system_history[-1]
            
            if latest.memory_percent > max_memory_percent:
                return False, f"内存使用过高: {latest.memory_percent:.1f}%"
            
            return True, "OK"
    
    def shutdown(self):
        """关闭监控"""
        self.monitoring = False
        if self.monitor_thread.is_alive():
            self.monitor_thread.join(timeout=5)
        logger.info("指标收集器已关闭")


# 全局指标收集器实例
metrics_collector = MetricsCollector()

