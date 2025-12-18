"""
请求限流中间件
基于令牌桶算法的高性能限流器
"""

import time
import logging
import threading
from typing import Dict, Optional
from collections import deque

logger = logging.getLogger(__name__)


class TokenBucket:
    """令牌桶算法实现"""
    
    def __init__(self, capacity: int, refill_rate: float):
        """
        初始化令牌桶
        
        Args:
            capacity: 桶容量（最大令牌数）
            refill_rate: 令牌补充速率（令牌/秒）
        """
        self.capacity = capacity
        self.refill_rate = refill_rate
        self.tokens = capacity
        self.last_refill = time.time()
        self.lock = threading.Lock()
    
    def _refill(self):
        """补充令牌"""
        now = time.time()
        time_passed = now - self.last_refill
        tokens_to_add = time_passed * self.refill_rate
        
        self.tokens = min(self.capacity, self.tokens + tokens_to_add)
        self.last_refill = now
    
    def consume(self, tokens: int = 1) -> bool:
        """
        消费令牌
        
        Args:
            tokens: 要消费的令牌数
            
        Returns:
            是否成功消费
        """
        with self.lock:
            self._refill()
            
            if self.tokens >= tokens:
                self.tokens -= tokens
                return True
            return False
    
    def get_tokens(self) -> float:
        """获取当前令牌数"""
        with self.lock:
            self._refill()
            return self.tokens


class RateLimiter:
    """请求限流器"""
    
    def __init__(self, 
                 requests_per_minute: int = 30,
                 requests_per_hour: int = 200,
                 burst_size: int = 10):
        """
        初始化限流器
        
        Args:
            requests_per_minute: 每分钟最大请求数
            requests_per_hour: 每小时最大请求数
            burst_size: 突发请求容量
        """
        self.requests_per_minute = requests_per_minute
        self.requests_per_hour = requests_per_hour
        
        # 创建两个令牌桶：分钟级和小时级
        self.minute_bucket = TokenBucket(
            capacity=requests_per_minute,
            refill_rate=requests_per_minute / 60.0  # 令牌/秒
        )
        
        self.hour_bucket = TokenBucket(
            capacity=requests_per_hour,
            refill_rate=requests_per_hour / 3600.0  # 令牌/秒
        )
        
        # IP级别的限流（可选）
        self.ip_buckets: Dict[str, TokenBucket] = {}
        self.ip_lock = threading.Lock()
        
        logger.info(f"限流器已初始化: {requests_per_minute}/min, {requests_per_hour}/hour")
    
    def is_allowed(self, client_ip: Optional[str] = None) -> tuple:
        """
        检查是否允许请求
        
        Args:
            client_ip: 客户端IP（可选，用于IP级别限流）
            
        Returns:
            (is_allowed, reason)
        """
        # 检查全局限流
        if not self.minute_bucket.consume():
            return False, f"超过每分钟请求限制({self.requests_per_minute})"
        
        if not self.hour_bucket.consume():
            # 归还分钟桶的令牌
            with self.minute_bucket.lock:
                self.minute_bucket.tokens += 1
            return False, f"超过每小时请求限制({self.requests_per_hour})"
        
        # IP级别限流（如果提供了IP）
        if client_ip:
            with self.ip_lock:
                if client_ip not in self.ip_buckets:
                    # 为新IP创建令牌桶（每IP每分钟10个请求）
                    self.ip_buckets[client_ip] = TokenBucket(
                        capacity=10,
                        refill_rate=10 / 60.0
                    )
                
                ip_bucket = self.ip_buckets[client_ip]
            
            if not ip_bucket.consume():
                # 归还全局令牌
                with self.minute_bucket.lock:
                    self.minute_bucket.tokens += 1
                with self.hour_bucket.lock:
                    self.hour_bucket.tokens += 1
                return False, f"IP {client_ip} 超过请求限制"
        
        return True, "OK"
    
    def get_stats(self) -> Dict:
        """获取限流统计"""
        return {
            'minute_tokens': self.minute_bucket.get_tokens(),
            'hour_tokens': self.hour_bucket.get_tokens(),
            'ip_count': len(self.ip_buckets)
        }


# 全局限流器实例
from config import CONCURRENCY_CONFIG

rate_limiter = None
if CONCURRENCY_CONFIG.get('rate_limit', {}).get('enabled', True):
    rate_limiter = RateLimiter(
        requests_per_minute=CONCURRENCY_CONFIG['rate_limit'].get('requests_per_minute', 30),
        requests_per_hour=CONCURRENCY_CONFIG['rate_limit'].get('requests_per_hour', 200)
    )

