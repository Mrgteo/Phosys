#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Dify Webhook 报警发送模块
用于将关键错误和成功事件发送到 Dify 工作流进行日志记录
"""

import requests
import json
import traceback
import sys
import logging
from datetime import datetime
from typing import Optional
import threading

logger = logging.getLogger(__name__)

# --- 配置区域 (从 config.py 导入) ---
try:
    from config import DIFY_CONFIG
    DIFY_API_KEY = DIFY_CONFIG.get('api_key', '')
    DIFY_BASE_URL = DIFY_CONFIG.get('base_url', 'http://localhost:5001')
    DIFY_WORKFLOW_ID = DIFY_CONFIG.get('workflow_id', '')
    DIFY_USER_ID = DIFY_CONFIG.get('user_id', '')
except (ImportError, AttributeError) as e:
    # 如果 config.py 中没有配置，使用默认值
    DIFY_API_KEY = ""
    DIFY_BASE_URL = "http://localhost:5001"
    DIFY_WORKFLOW_ID = ""
    DIFY_USER_ID = ""


def _send_webhook_request(payload: dict):
    """
    实际发送 HTTP POST 请求的内部函数
    
    Args:
        payload: 请求体数据
    """
    if not DIFY_API_KEY:
        logger.warning("[Dify] ⚠️ API Key 未配置，跳过报警发送")
        return
    
    # 如果指定了 workflow_id，使用指定版本；否则使用已发布的工作流
    if DIFY_WORKFLOW_ID:
        url = f"{DIFY_BASE_URL}/v1/workflows/{DIFY_WORKFLOW_ID}/run"
    else:
        url = f"{DIFY_BASE_URL}/v1/workflows/run"
        logger.info("[Dify] 使用已发布的工作流版本（未指定 workflow_id）")
    headers = {
        "Authorization": f"Bearer {DIFY_API_KEY}",
        "Content-Type": "application/json"
    }
    
    try:
        logger.info(f"[Dify] 正在发送事件到 {url}")
        logger.info(f"[Dify] 事件类型: {payload.get('inputs', {}).get('event_type', 'unknown')}")
        logger.debug(f"[Dify] 请求体: {json.dumps(payload, ensure_ascii=False, indent=2)}")
        
        # 设置短超时，防止 Dify 响应慢时卡住主业务线程
        response = requests.post(url, headers=headers, json=payload, timeout=5)  # 增加到5秒超时
        if response.status_code not in [200, 201]:
            # 记录到本地日志作为回退
            logger.warning(f"[Dify] 报警发送失败: HTTP {response.status_code}, {response.text}")
        else:
            logger.info(f"[Dify] ✅ 报警发送成功: {payload.get('inputs', {}).get('level', 'UNKNOWN')} - {payload.get('inputs', {}).get('message', '')}")
            try:
                result = response.json()
                logger.debug(f"[Dify] 响应: {json.dumps(result, ensure_ascii=False, indent=2)}")
            except:
                logger.debug(f"[Dify] 响应文本: {response.text[:200]}")
    except requests.exceptions.Timeout:
        logger.warning(f"[Dify] ⚠️ 报警发送超时（5秒），URL: {url}")
    except requests.exceptions.ConnectionError as e:
        logger.warning(f"[Dify] ⚠️ 无法连接到 Dify 服务: {e}, URL: {url}")
    except Exception as e:
        logger.warning(f"[Dify] ⚠️ Webhook 连接错误: {e}, URL: {url}")
        import traceback
        logger.debug(f"[Dify] 错误堆栈: {traceback.format_exc()}")


def send_alarm_webhook(task_id: str, module: str, level: str, message: str, detail: str = ""):
    """
    发送结构化的报警 Webhook 到 Dify（已废弃，请使用 log_event）
    
    Args:
        task_id: 任务的唯一 ID (UUID)
        module: 触发报警的模块 (如: ASR_Core, PipelineService)
        level: 报警级别，必须是 ERROR 或 SUCCESS
        message: 简短的报警信息
        detail: 完整的错误堆栈或关键结果 JSON（可选）
    """
    # 向后兼容：调用新的 log_event 函数
    log_event(
        task_id=task_id,
        event_type="transcribe",  # 默认事件类型
        module=module,
        level=level,
        message=message,
        detail=detail
    )


def log_event(
    task_id: str,
    event_type: str,
    module: str,
    level: str,
    message: str,
    detail: str = "",
    file_id: str = "",
    filename: str = "",
    file_size: int = 0
):
    """
    通用事件日志函数 - 发送结构化事件到 Dify
    
    Args:
        task_id: 任务的唯一 ID (UUID)
        event_type: 事件类型 (upload, transcribe, download, delete, clear_history, error)
        module: 触发事件的模块 (如: VoiceGateway, PipelineService)
        level: 事件级别 (SUCCESS, ERROR)
        message: 简短的事件描述
        detail: 详细信息（JSON字符串或普通文本）
        file_id: 文件ID（可选）
        filename: 文件名（可选）
        file_size: 文件大小，单位字节（可选）
    """
    if level not in ["ERROR", "SUCCESS"]:
        logger.warning(f"[Dify] 跳过非关键事件: {level}")
        return
    
    # 只保留转写事件和错误事件的日志，其他事件类型不发送到 Dify
    if event_type not in ["transcribe", "error"]:
        logger.debug(f"[Dify] 跳过非转写事件: {event_type} - {message}")
        return
    
    if not DIFY_API_KEY:
        logger.warning(f"[Dify] ⚠️ API Key 未配置，跳过事件日志")
        return
    
    # workflow_id 是可选的，如果不指定则使用已发布的工作流
    if not DIFY_WORKFLOW_ID:
        logger.info("[Dify] 未指定 workflow_id，将使用已发布的工作流版本")
    
    logger.info(f"[Dify] 📤 准备发送事件日志: event_type={event_type}, level={level}, module={module}, message={message}, file_id={file_id}, filename={filename}")
    
    # 构建 detail，如果提供了额外信息，合并到 detail 中
    detail_obj = {}
    if detail:
        try:
            # 尝试解析为 JSON
            detail_obj = json.loads(detail)
            if not isinstance(detail_obj, dict):
                detail_obj = {"raw": detail}
        except (json.JSONDecodeError, TypeError):
            # 如果不是 JSON，作为普通文本
            detail_obj = {"raw": detail}
    
    # 添加文件信息到 detail
    if file_id:
        detail_obj["file_id"] = file_id
    if filename:
        detail_obj["filename"] = filename
    if file_size > 0:
        detail_obj["file_size"] = file_size
    
    # 将 detail_obj 转换回 JSON 字符串
    detail_str = json.dumps(detail_obj, ensure_ascii=False) if detail_obj else ""
    
    payload = {
        "inputs": {
            "task_id": str(task_id),
            "level": level,
            "module": module,
            "message": message,
            "detail": detail_str,
            "timestamp": datetime.now().isoformat(),
            "event_type": event_type,  # 新增：事件类型
            "file_id": str(file_id) if file_id else str(task_id),  # 新增：文件ID
            "filename": str(filename) if filename else "",  # 新增：文件名
            "file_size": int(file_size) if file_size > 0 else 0  # 新增：文件大小
        },
        "response_mode": "blocking",  # 保证日志发送的可靠性
        "user": DIFY_USER_ID if DIFY_USER_ID else f"event_{task_id}"
    }
    
    # 使用异步线程发送 (推荐!)，防止 Webhook 延迟影响主业务流
    threading.Thread(
        target=_send_webhook_request,
        args=(payload,),
        daemon=True,
        name=f"DifyEvent-{event_type}-{task_id[:8]}"
    ).start()


def log_error_alarm(task_id: str, module: str, message: str, exception: Optional[Exception] = None):
    """
    专门用于捕获异常并发送 ERROR 报警的辅助函数
    
    Args:
        task_id: 任务的唯一 ID
        module: 触发报警的模块
        message: 错误消息
        exception: 异常对象（可选），如果提供会自动提取堆栈信息
    """
    # 自动获取完整的堆栈信息
    if exception:
        try:
            error_stack = ''.join(traceback.format_exception(type(exception), exception, exception.__traceback__))
        except:
            error_stack = traceback.format_exc()
    else:
        error_stack = traceback.format_exc()
    
    # 增强错误消息：如果是特定类型的错误，添加更详细的模块信息
    enhanced_module = module
    if exception:
        error_str = str(exception)
        if "CUDA" in error_str or "GPU" in error_str or "OOM" in error_str:
            enhanced_module = "GPU_OOM"
        elif "timeout" in error_str.lower():
            enhanced_module = f"{module}_Timeout"
        elif "connection" in error_str.lower():
            enhanced_module = f"{module}_Connection"
    
    # 使用新的 log_event 函数
    log_event(
        task_id=task_id,
        event_type="error",
        module=enhanced_module,
        level="ERROR",
        message=message,
        detail=error_stack
    )


def log_success_alarm(task_id: str, module: str, message: str, detail: str = "", file_size: int = 0):
    """
    发送 SUCCESS 报警的辅助函数（转写成功专用）
    
    Args:
        task_id: 任务的唯一 ID
        module: 触发报警的模块
        message: 成功消息
        detail: 详细信息（如转写字数、耗时等，JSON格式）
        file_size: 文件大小（字节，可选）
    """
    # 从 detail 中提取 file_id 和 filename（如果存在）
    file_id = task_id
    filename = ""
    
    if detail:
        try:
            detail_obj = json.loads(detail)
            if isinstance(detail_obj, dict):
                file_id = detail_obj.get('file_id', task_id)
                filename = detail_obj.get('filename', '')
        except:
            pass
    
    log_event(
        task_id=task_id,
        event_type="transcribe",
        module=module,
        level="SUCCESS",
        message=message,
        detail=detail,
        file_id=file_id,
        filename=filename,
        file_size=file_size
    )


# ==================== 新增：特定事件类型的日志函数 ====================

def log_upload_event(file_id: str, filename: str, file_size: int, level: str, error: Optional[Exception] = None):
    """
    记录文件上传事件
    
    Args:
        file_id: 文件ID
        filename: 文件名
        file_size: 文件大小（字节）
        level: SUCCESS 或 ERROR
        error: 错误异常（可选）
    """
    if level == "SUCCESS":
        message = f"文件上传成功: {filename}"
        detail = ""
    else:
        message = f"文件上传失败: {filename}"
        if error:
            detail = ''.join(traceback.format_exception(type(error), error, error.__traceback__))
        else:
            detail = "未知错误"
    
    log_event(
        task_id=file_id,
        event_type="upload",
        module="VoiceGateway",
        level=level,
        message=message,
        detail=detail,
        file_id=file_id,
        filename=filename,
        file_size=file_size
    )


def log_download_event(file_id: str, filename: str, level: str, error: Optional[Exception] = None):
    """
    记录文件下载事件
    
    Args:
        file_id: 文件ID
        filename: 文件名
        level: SUCCESS 或 ERROR
        error: 错误异常（可选）
    """
    if level == "SUCCESS":
        message = f"文件下载成功: {filename}"
        detail = ""
    else:
        message = f"文件下载失败: {filename}"
        if error:
            detail = ''.join(traceback.format_exception(type(error), error, error.__traceback__))
        else:
            detail = "未知错误"
    
    log_event(
        task_id=file_id,
        event_type="download",
        module="VoiceGateway",
        level=level,
        message=message,
        detail=detail,
        file_id=file_id,
        filename=filename
    )


def log_delete_event(file_id: str, filename: str, level: str, error: Optional[Exception] = None, was_stopped: bool = False):
    """
    记录文件删除事件
    
    Args:
        file_id: 文件ID
        filename: 文件名
        level: SUCCESS 或 ERROR
        error: 错误异常（可选）
        was_stopped: 是否是被停止的转写文件（可选）
    """
    if level == "SUCCESS":
        message = f"文件删除成功: {filename}"
        detail_obj = {}
        if was_stopped:
            detail_obj["was_stopped"] = True
        detail = json.dumps(detail_obj, ensure_ascii=False) if detail_obj else ""
    else:
        message = f"文件删除失败: {filename}"
        if error:
            error_stack = ''.join(traceback.format_exception(type(error), error, error.__traceback__))
            detail_obj = {"error": error_stack}
            if was_stopped:
                detail_obj["was_stopped"] = True
            detail = json.dumps(detail_obj, ensure_ascii=False)
        else:
            detail_obj = {"error": "未知错误"}
            if was_stopped:
                detail_obj["was_stopped"] = True
            detail = json.dumps(detail_obj, ensure_ascii=False)
    
    log_event(
        task_id=file_id,
        event_type="delete",
        module="VoiceGateway",
        level=level,
        message=message,
        detail=detail,
        file_id=file_id,
        filename=filename
    )


def log_clear_history_event(
    level: str, 
    deleted_records: int = 0,
    deleted_audio_files: int = 0,
    deleted_transcript_files: int = 0,
    error: Optional[Exception] = None
):
    """
    记录清空历史记录事件
    
    Args:
        level: SUCCESS 或 ERROR
        deleted_records: 删除的历史记录条数
        deleted_audio_files: 删除的音频文件数
        deleted_transcript_files: 删除的转写文档数
        error: 错误异常（可选）
    """
    import uuid
    task_id = str(uuid.uuid4())
    
    if level == "SUCCESS":
        # 构建详细的消息
        parts = []
        if deleted_records > 0:
            parts.append(f"{deleted_records} 条历史记录")
        if deleted_audio_files > 0:
            parts.append(f"{deleted_audio_files} 个音频文件")
        if deleted_transcript_files > 0:
            parts.append(f"{deleted_transcript_files} 个转写文档")
        
        if parts:
            message = f"清空历史记录成功: 删除了 {', '.join(parts)}"
        else:
            message = "清空历史记录成功: 没有需要删除的内容"
        
        detail = json.dumps({
            "deleted_records": deleted_records,
            "deleted_audio_files": deleted_audio_files,
            "deleted_transcript_files": deleted_transcript_files
        }, ensure_ascii=False)
    else:
        message = f"清空历史记录失败"
        if error:
            detail = ''.join(traceback.format_exception(type(error), error, error.__traceback__))
        else:
            detail = "未知错误"
    
    log_event(
        task_id=task_id,
        event_type="clear_history",
        module="VoiceGateway",
        level=level,
        message=message,
        detail=detail
    )


def log_stop_transcription_event(file_id: str, filename: str, level: str, error: Optional[Exception] = None, progress: int = 0):
    """
    记录停止转写事件
    
    Args:
        file_id: 文件ID
        filename: 文件名
        level: SUCCESS 或 ERROR
        error: 错误异常（可选）
        progress: 停止时的进度（0-100，可选）
    """
    if level == "SUCCESS":
        message = f"转写已停止: {filename}"
        detail_obj = {
            "file_id": file_id,
            "filename": filename
        }
        if progress > 0:
            detail_obj["progress"] = progress
        detail = json.dumps(detail_obj, ensure_ascii=False)
    else:
        message = f"停止转写失败: {filename}"
        if error:
            error_stack = ''.join(traceback.format_exception(type(error), error, error.__traceback__))
            detail = json.dumps({
                "file_id": file_id,
                "filename": filename,
                "error": error_stack
            }, ensure_ascii=False)
        else:
            detail = json.dumps({
                "file_id": file_id,
                "filename": filename,
                "error": "未知错误"
            }, ensure_ascii=False)
    
    log_event(
        task_id=file_id,
        event_type="stop_transcribe",
        module="VoiceGateway",
        level=level,
        message=message,
        detail=detail,
        file_id=file_id,
        filename=filename
    )

