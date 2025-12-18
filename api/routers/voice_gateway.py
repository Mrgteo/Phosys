"""
API - 语音服务网关 (完整版)
包含所有功能：转写、会议纪要、Dify集成、OpenAI兼容等
"""

import os
import uuid
import logging
import threading
import json
import asyncio
import zipfile
import io
import base64
import re
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Union
from concurrent.futures import ThreadPoolExecutor, wait
import jieba
import jieba.analyse

from fastapi import APIRouter, UploadFile, File, Form, HTTPException, Request, WebSocket, WebSocketDisconnect, Request
from fastapi.responses import JSONResponse, FileResponse, StreamingResponse
from werkzeug.utils import secure_filename
from docx import Document
from docx.shared import Inches, Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.oxml import OxmlElement
from docx.enum.table import WD_TABLE_ALIGNMENT
from openai import OpenAI

from application.voice.pipeline_service_funasr import PipelineService  # 使用FunASR版本
from infra.audio_io.storage import AudioStorage
from infra.websocket import ws_manager
from config import FILE_CONFIG, LANGUAGE_CONFIG, DEEPSEEK_CONFIG, AI_MODEL_CONFIG

logger = logging.getLogger(__name__)

# 导入 Dify 报警模块
try:
    from infra.monitoring.dify_webhook_sender import (
        log_success_alarm, 
        log_error_alarm,
        log_upload_event,
        log_download_event,
        log_delete_event,
        log_clear_history_event,
        log_stop_transcription_event
    )
    DIFY_ALARM_ENABLED = True
    logger.info("✅ Dify 报警模块已加载 (VoiceGateway)")
except ImportError as e:
    DIFY_ALARM_ENABLED = False
    logger.warning(f"⚠️ Dify 报警模块未找到，报警功能已禁用: {e}")

router = APIRouter(prefix="/api/voice", tags=["voice"])

# 全局变量
pipeline_service: Optional[PipelineService] = None
audio_storage: Optional[AudioStorage] = None

# 历史记录文件
HISTORY_FILE = os.path.join(FILE_CONFIG['output_dir'], 'history_records.json')

# 线程安全的文件管理器
class ThreadSafeFileManager:
    """线程安全的文件管理器"""
    
    def __init__(self):
        self._files = []
        self._processing_files = []
        self._completed_files = []
        self._lock = threading.RLock()  # 递归锁，支持同一线程多次获取
    
    def add_file(self, file_info: dict):
        """添加文件"""
        with self._lock:
            self._files.append(file_info)
    
    def get_file(self, file_id: str) -> Optional[dict]:
        """获取文件信息"""
        with self._lock:
            for f in self._files:
                if f['id'] == file_id:
                    return f
            return None
    
    def get_all_files(self) -> List[dict]:
        """获取所有文件（返回副本）"""
        with self._lock:
            return self._files.copy()
    
    def update_file(self, file_id: str, updates: dict):
        """更新文件信息"""
        with self._lock:
            for f in self._files:
                if f['id'] == file_id:
                    f.update(updates)
                    return True
            return False
    
    def remove_file(self, file_id: str) -> bool:
        """移除文件"""
        with self._lock:
            for i, f in enumerate(self._files):
                if f['id'] == file_id:
                    self._files.pop(i)
                    self._processing_files = [fid for fid in self._processing_files if fid != file_id]
                    self._completed_files = [fid for fid in self._completed_files if fid != file_id]
                    return True
            return False
    
    def add_to_processing(self, file_id: str):
        """添加到处理队列"""
        with self._lock:
            if file_id not in self._processing_files:
                self._processing_files.append(file_id)
    
    def remove_from_processing(self, file_id: str):
        """从处理队列移除"""
        with self._lock:
            self._processing_files = [fid for fid in self._processing_files if fid != file_id]
    
    def add_to_completed(self, file_id: str):
        """添加到已完成队列"""
        with self._lock:
            if file_id not in self._completed_files:
                self._completed_files.append(file_id)
    
    def get_processing_files(self) -> List[str]:
        """获取处理中的文件ID列表"""
        with self._lock:
            return self._processing_files.copy()
    
    def get_completed_files(self) -> List[str]:
        """获取已完成的文件ID列表"""
        with self._lock:
            return self._completed_files.copy()
    
    def to_dict(self) -> dict:
        """转换为字典（用于序列化）"""
        with self._lock:
            return {
                'files': self._files.copy(),
                'processing_files': self._processing_files.copy(),
                'completed_files': self._completed_files.copy()
            }

# 使用线程安全的文件管理器
uploaded_files_manager = ThreadSafeFileManager()

# 线程池用于并发处理转写任务（从配置读取）
from config import CONCURRENCY_CONFIG
TRANSCRIPTION_THREAD_POOL = ThreadPoolExecutor(
    max_workers=CONCURRENCY_CONFIG.get('transcription_workers', 5),
    thread_name_prefix='transcribe-worker'
)

# 任务字典：存储 file_id -> Future 的映射，用于取消任务
transcription_tasks = {}  # {file_id: Future}
transcription_tasks_lock = threading.Lock()  # 保护任务字典的锁

# ⚠️ 移除全局锁 - 模型池已经处理并发，不再需要全局锁


# 保存主事件循环引用
_main_loop = None

def set_main_loop(loop):
    """设置主事件循环引用"""
    global _main_loop
    _main_loop = loop
    logger.info("主事件循环已设置")

def send_ws_message_sync(file_id: str, status: str, progress: int = 0, message: str = "", **kwargs):
    """
    在同步代码中发送WebSocket消息的辅助函数
    通过asyncio.run_coroutine_threadsafe在事件循环中执行异步任务
    """
    if _main_loop is None:
        logger.warning("主事件循环未设置，无法发送WebSocket消息")
        return
    
    try:
        # 在主事件循环中调度异步任务
        asyncio.run_coroutine_threadsafe(
            ws_manager.send_file_status(file_id, status, progress, message, kwargs),
            _main_loop
        )
    except Exception as e:
        logger.error(f"发送WebSocket消息失败: {e}")


def init_voice_gateway(service: PipelineService, storage: AudioStorage):
    """初始化网关服务"""
    global pipeline_service, audio_storage
    pipeline_service = service
    audio_storage = storage
    # 启动时加载历史记录
    load_history_from_file()


def load_history_from_file():
    """从文件加载历史记录（只加载已完成的，不影响当前正在处理的文件）"""
    global uploaded_files_manager
    try:
        if os.path.exists(HISTORY_FILE):
            with open(HISTORY_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                completed_files_from_disk = data.get('files', [])
                
                # 保留当前内存中未完成的文件
                all_files = uploaded_files_manager.get_all_files()
                current_incomplete_files = [f for f in all_files 
                                           if f['status'] in ['uploaded', 'processing', 'error']]
                
                # 合并：未完成的文件 + 磁盘上的已完成文件
                # 使用字典去重，以file_id为key
                files_dict = {}
                
                # 先添加未完成的文件
                for f in current_incomplete_files:
                    files_dict[f['id']] = f
                
                # 再添加已完成的文件（如果有重复，已完成的会覆盖）
                for f in completed_files_from_disk:
                    files_dict[f['id']] = f
                
                # 重新构建管理器（需要在锁内完成）
                uploaded_files_manager._lock.acquire()
                try:
                    uploaded_files_manager._files = list(files_dict.values())
                    uploaded_files_manager._completed_files = data.get('completed_files', [])
                finally:
                    uploaded_files_manager._lock.release()
                
                logger.info(f"已加载 {len(completed_files_from_disk)} 条历史记录，当前总文件数: {len(files_dict)}")
    except Exception as e:
        logger.error(f"加载历史记录失败: {e}")


def save_history_to_file():
    """保存历史记录到文件"""
    try:
        # 只保存已完成的文件记录
        all_files = uploaded_files_manager.get_all_files()
        completed_files = [f for f in all_files if f['status'] == 'completed']
        data = {
            'files': completed_files,
            'completed_files': uploaded_files_manager.get_completed_files()
        }
        with open(HISTORY_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        logger.info(f"已保存 {len(completed_files)} 条历史记录")
    except Exception as e:
        logger.error(f"保存历史记录失败: {e}")


def allowed_file(filename: str) -> bool:
    """检查文件格式"""
    ALLOWED_EXTENSIONS = {'mp3', 'wav', 'm4a', 'flac', 'aac', 'ogg', 'wma'}
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def save_transcript_to_word(transcript_data, filename_prefix="transcript", language="zh", audio_filename=None, file_id=None):
    """将转录结果保存为Word文档"""
    try:
        doc = Document()
        
        # 定义黑色（RGB(0,0,0)）
        black_color = RGBColor(0, 0, 0)
        
        title = doc.add_heading('语音转文字结果', 0)
        title.alignment = WD_ALIGN_PARAGRAPH.CENTER
        # 设置标题为微软雅黑，黑色
        for run in title.runs:
            run.font.name = 'Microsoft YaHei'
            run.font.color.rgb = black_color
            run._element.rPr.rFonts.set(qn('w:eastAsia'), '微软雅黑')
        doc.add_paragraph()
        
        info_table = doc.add_table(rows=3, cols=2)
        # 恢复原来的表格样式
        info_table.style = 'Light Grid Accent 1'
        
        for row in info_table.rows:
            row.cells[0].width = Inches(1.5)
            row.cells[1].width = Inches(5.0)
        
        # 设置表格第一列（标签）为宋体11号加粗，黑色，居中
        info_table.rows[0].cells[0].text = '生成时间'
        label_para = info_table.rows[0].cells[0].paragraphs[0]
        label_para.alignment = WD_ALIGN_PARAGRAPH.CENTER
        label_run = label_para.runs[0]
        label_run.bold = False
        label_run.font.size = Pt(11)
        label_run.font.name = 'SimSun'
        label_run.font.color.rgb = black_color
        label_run._element.rPr.rFonts.set(qn('w:eastAsia'), '宋体')
        
        # 设置表格第二列（值）为宋体11号加粗，黑色，居中
        info_table.rows[0].cells[1].text = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        value_para = info_table.rows[0].cells[1].paragraphs[0]
        value_para.alignment = WD_ALIGN_PARAGRAPH.CENTER
        value_run = value_para.runs[0]
        value_run.bold = False
        value_run.font.size = Pt(11)
        value_run.font.name = 'SimSun'
        value_run.font.color.rgb = black_color
        value_run._element.rPr.rFonts.set(qn('w:eastAsia'), '宋体')
        
        info_table.rows[1].cells[0].text = '音频文件'
        label_para = info_table.rows[1].cells[0].paragraphs[0]
        label_para.alignment = WD_ALIGN_PARAGRAPH.CENTER
        label_run = label_para.runs[0]
        label_run.bold = False
        label_run.font.size = Pt(11)
        label_run.font.name = 'SimSun'
        label_run.font.color.rgb = black_color
        label_run._element.rPr.rFonts.set(qn('w:eastAsia'), '宋体')
        
        info_table.rows[1].cells[1].text = audio_filename or "未知文件"
        value_para = info_table.rows[1].cells[1].paragraphs[0]
        value_para.alignment = WD_ALIGN_PARAGRAPH.CENTER
        value_run = value_para.runs[0]
        value_run.bold = False
        value_run.font.size = Pt(11)
        value_run.font.name = 'SimSun'
        value_run.font.color.rgb = black_color
        value_run._element.rPr.rFonts.set(qn('w:eastAsia'), '宋体')
        
        info_table.rows[2].cells[0].text = '文本长度'
        label_para = info_table.rows[2].cells[0].paragraphs[0]
        label_para.alignment = WD_ALIGN_PARAGRAPH.CENTER
        label_run = label_para.runs[0]
        label_run.bold = False
        label_run.font.size = Pt(11)
        label_run.font.name = 'SimSun'
        label_run.font.color.rgb = black_color
        label_run._element.rPr.rFonts.set(qn('w:eastAsia'), '宋体')
        
        total_chars = sum(len(entry['text']) for entry in transcript_data)
        info_table.rows[2].cells[1].text = f"{total_chars} 字符"
        value_para = info_table.rows[2].cells[1].paragraphs[0]
        value_para.alignment = WD_ALIGN_PARAGRAPH.CENTER
        value_run = value_para.runs[0]
        value_run.bold = False
        value_run.font.size = Pt(11)
        value_run.font.name = 'SimSun'
        value_run.font.color.rgb = black_color
        value_run._element.rPr.rFonts.set(qn('w:eastAsia'), '宋体')
        
        doc.add_paragraph()
        
        for entry in transcript_data:
            speaker_para = doc.add_paragraph()
            speaker_run = speaker_para.add_run(entry['speaker'])
            speaker_run.bold = False
            speaker_run.font.size = Pt(12)
            speaker_run.font.name = 'SimSun'
            speaker_run.font.color.rgb = black_color
            speaker_run._element.rPr.rFonts.set(qn('w:eastAsia'), '宋体')
            # 设置发言人段落的下间距为0，使内容紧跟在后面
            speaker_para.paragraph_format.space_after = Pt(0)
            
            # 减小发言人和内容的间距，设置段落间距为0
            text_para = doc.add_paragraph()
            text_para.paragraph_format.space_before = Pt(0)
            text_para.paragraph_format.space_after = Pt(0)
            text_run = text_para.add_run(entry['text'])
            text_run.font.size = Pt(12)
            text_run.font.name = 'SimSun'
            text_run.font.color.rgb = black_color
            text_run._element.rPr.rFonts.set(qn('w:eastAsia'), '宋体')
            
            # 不同发言人之间的间距保持正常
            doc.add_paragraph()
        
        # ✅ 修复：使用微秒级时间戳 + file_id 确保文件名唯一性
        # 如果两个文件在同一秒内完成，使用微秒可以区分
        # 如果提供了 file_id，也加入文件名中，进一步确保唯一性
        now = datetime.now()
        timestamp = now.strftime('%Y%m%d_%H%M%S_%f')  # 包含微秒
        
        # 如果提供了 file_id，使用前8个字符作为唯一标识
        if file_id:
            file_id_short = file_id.replace('-', '')[:8]  # 移除连字符，取前8位
            filename = f"{filename_prefix}_{timestamp}_{file_id_short}.docx"
        else:
            filename = f"{filename_prefix}_{timestamp}.docx"
        
        filepath = os.path.join(FILE_CONFIG['output_dir'], filename)
        
        doc.save(filepath)
        return filename, filepath
        
    except Exception as e:
        logger.error(f"保存Word文档失败: {e}")
        return None, None


def generate_meeting_summary(transcript_data, custom_prompt=None, model=None):
    """使用AI生成会议纪要"""
    try:
        if not transcript_data:
            logger.warning("转写数据为空，无法生成会议纪要")
            return None
        
        transcript_text = ""
        for entry in transcript_data:
            speaker = entry.get('speaker', '未知发言人')
            text = entry.get('text', '')
            transcript_text += f"{speaker}: {text}\n\n"
        
        if not transcript_text.strip():
            logger.warning("转写文本为空，无法生成会议纪要")
            return None
        
        logger.info(f"开始生成会议纪要，转写文本长度: {len(transcript_text)} 字符")
        
        # 根据传入的模型选择对应的配置
        # 模型值可能是：deepseek, qwen, glm 或旧的 deepseek-chat 等格式
        model_key = None
        if model:
            # 标准化模型名称
            model_lower = model.lower()
            if 'deepseek' in model_lower or model_lower == 'deepseek':
                model_key = 'deepseek'
            elif 'qwen' in model_lower or model_lower == 'qwen':
                model_key = 'qwen'
            elif 'glm' in model_lower or model_lower == 'glm':
                model_key = 'glm'
        
        # 如果没有指定模型或模型不在配置中，使用默认的 deepseek
        if not model_key or model_key not in AI_MODEL_CONFIG:
            model_key = 'deepseek'
            logger.info(f"使用默认模型: {model_key}")
        
        # 获取对应模型的配置
        model_config = AI_MODEL_CONFIG.get(model_key, AI_MODEL_CONFIG['deepseek'])
        api_key = model_config.get('api_key')
        api_base = model_config.get('api_base')
        model_name = model_config.get('model')
        
        # 如果配置中没有API KEY，尝试从环境变量读取
        if not api_key:
            api_key = os.getenv('DEEPSEEK_API_KEY') or os.getenv('OPENAI_API_KEY')
        if not api_base:
            api_base = os.getenv('DEEPSEEK_API_BASE') or os.getenv('OPENAI_API_BASE', 'https://api.deepseek.com')
        
        if not api_key:
            logger.warning("未配置API KEY，使用默认模板")
            return generate_default_summary(transcript_data)
        
        logger.info(f"使用模型: {model_key} ({model_config.get('display_name', model_key)}), API Base: {api_base}")
        
        client = OpenAI(api_key=api_key, base_url=api_base)
        
        # 使用自定义提示词，如果没有则使用默认提示词
        if custom_prompt:
            # 替换 {transcript} 占位符，如果没有占位符则自动追加转写内容
            if '{transcript}' in custom_prompt:
                prompt = custom_prompt.replace('{transcript}', transcript_text)
                logger.info("使用自定义提示词，已替换 {transcript} 占位符")
            else:
                # 如果提示词中没有占位符，检查是否有"会议转录内容："这一行
                if '会议转录内容：' in custom_prompt:
                    # 如果有，在该行后面插入转写内容
                    prompt = custom_prompt.replace('会议转录内容：', f'会议转录内容：\n{transcript_text}')
                else:
                    # 如果没有，自动在末尾追加转写内容
                    prompt = f"{custom_prompt}\n\n会议转录内容：\n{transcript_text}"
                logger.info("使用自定义提示词，自动追加转写内容（提示词中未包含 {transcript} 占位符）")
            
            # 为自定义提示词也添加要求（避免确认消息）
            if '不要包含任何确认消息' not in prompt and '不要添加任何前缀说明' not in prompt:
                prompt += "\n\n重要要求：直接输出会议纪要内容，不要包含任何确认消息、引导语句或说明性文字（如'这是根据您提供的会议转录内容生成的会议纪要'、'好的'、'已根据'等）。不要添加任何前缀说明，直接开始输出。"
        else:
            logger.info("使用默认提示词模板")
            prompt = f"""请根据以下会议转录内容，生成一份结构化的会议纪要。

会议转录内容：
{transcript_text}

请严格按照以下格式生成会议纪要：

会议主题：[根据会议内容总结主题]
主持人：[从转录中识别主持人]
参会人数：[统计参与会议的总人数]
关键词：[会议纪要关键词]

一、会议议题及讨论内容
二、行动清单（待办事项）
三、其他说明

重要要求：
1. 直接输出会议纪要内容，不要包含任何确认消息、引导语句或说明性文字（如"这是根据您提供的会议转录内容生成的会议纪要"、"好的"、"已根据"等）
2. 不要添加任何前缀说明，直接开始输出会议主题
3. 不要使用"为您生成"、"已根据"、"这是"等引导性语句
4. 输出内容应该是纯粹的会议纪要，不包含任何元信息或确认信息
5. 关键词部分应提取会议中的核心专业术语、重要概念、关键议题等，用空格分隔，数量控制在10-20个之间"""
        
        response = client.chat.completions.create(
            model=model_name,
            messages=[
                {
                    "role": "system", 
                    "content": "你是一个专业的会议纪要助手。重要规则：直接输出会议纪要内容，不要包含任何确认消息、引导语句、说明性文字或元信息（如'这是根据您提供的会议转录内容生成的会议纪要'、'好的'、'已根据'、'为您生成'等）。直接开始输出会议主题，不要添加任何前缀。"
                },
                {"role": "user", "content": prompt}
            ],
            temperature=0.7,
            max_tokens=4000
        )
        
        # 去除AI返回内容中的确认消息和markdown格式
        raw_content = response.choices[0].message.content
        
        # 智能去除确认消息和引导消息（更通用的方法）
        # 方法1：识别并去除以确认性短语开头的段落
        lines = raw_content.split('\n')
        cleaned_lines = []
        skip_until_content = True  # 标记是否还在跳过确认消息阶段
        
        for i, line in enumerate(lines):
            line_stripped = line.strip()
            
            # 如果遇到空行，可能是确认消息和实际内容的边界
            if not line_stripped:
                if skip_until_content:
                    continue  # 跳过确认消息后的空行
                else:
                    cleaned_lines.append(line)  # 保留内容中的空行
                continue
            
            # 检查是否是确认消息或引导消息
            is_confirmation = False
            
            # 确认消息关键词模式（更全面的匹配）
            confirmation_keywords = [
                r'^(好的|明白了|收到|了解)[，,。\s]*',
                r'^(已根据|根据您提供|根据.*?转录|根据.*?内容)',
                r'^(为您生成|为您.*?生成|已.*?生成.*?会议纪要)',
                r'^(这是.*?生成的.*?会议纪要|这是根据.*?生成的)',
                r'^(以下是|下面.*?是|我将.*?为您)',
                r'^(根据.*?内容.*?生成|基于.*?内容.*?生成)',
                r'^(好的[，,]\s*)?(已|已经).*?(生成|为您|根据)',
                r'^.*?(为您|已为您|已经为您).*?(生成|创建|制作).*?(会议纪要|纪要)',
            ]
            
            for pattern in confirmation_keywords:
                if re.match(pattern, line_stripped, re.IGNORECASE):
                    is_confirmation = True
                    break
            
            # 检查是否包含确认性短语（即使不在开头）
            confirmation_phrases = [
                '这是根据您提供的',
                '这是根据.*?生成的',
                '已根据.*?为您生成',
                '为您生成.*?会议纪要',
                '已为您生成',
                '已经为您生成',
                '根据.*?内容.*?生成.*?会议纪要',
            ]
            
            for phrase in confirmation_phrases:
                if re.search(phrase, line_stripped, re.IGNORECASE):
                    is_confirmation = True
                    break
            
            # 如果这一行是确认消息，跳过
            if is_confirmation:
                skip_until_content = True
                continue
            
            # 如果遇到实际内容（以"会议主题"、"主持人"、"参会人数"等开头），停止跳过
            if re.match(r'^(会议主题|会议时间|会议地点|主持人|记录人|参与人员|参会人数|一、|二、|三、)', line_stripped):
                skip_until_content = False
                cleaned_lines.append(line)
            elif not skip_until_content:
                # 已经进入实际内容，保留所有行
                cleaned_lines.append(line)
            elif len(line_stripped) > 20 and not any(keyword in line_stripped for keyword in ['根据', '生成', '为您', '已', '这是']):
                # 如果行较长且不包含确认关键词，可能是实际内容
                skip_until_content = False
                cleaned_lines.append(line)
        
        raw_content = '\n'.join(cleaned_lines)
        
        # 方法2：去除开头可能残留的确认消息（作为兜底）
        # 去除以确认性短语开头的文本（最多去除前500字符）
        confirmation_start_patterns = [
            r'^(好的[，,]\s*)?(已根据|根据您提供|根据.*?转录|根据.*?内容).*?',
            r'^(为您生成|已.*?生成.*?会议纪要).*?',
            r'^(这是.*?生成的.*?会议纪要|这是根据.*?生成的).*?',
            r'^(以下是|下面.*?是|我将.*?为您).*?',
        ]
        
        for pattern in confirmation_start_patterns:
            # 只检查前500字符，避免误删实际内容
            if len(raw_content) > 500:
                prefix = raw_content[:500]
                match = re.match(pattern, prefix, re.IGNORECASE | re.DOTALL)
                if match:
                    # 找到第一个实际内容标记（如"会议主题"、"主持人"、"参会人数"等）
                    content_start = re.search(r'(会议主题|会议时间|会议地点|主持人|记录人|参与人员|参会人数|一、|二、|三、)', raw_content)
                    if content_start:
                        raw_content = raw_content[content_start.start():]
                    else:
                        # 如果没有找到标记，去除匹配的部分
                        raw_content = raw_content[match.end():].lstrip()
                    break
            else:
                # 内容较短，直接处理
                raw_content = re.sub(pattern, '', raw_content, flags=re.IGNORECASE | re.DOTALL)
                break
        
        # 去除分隔线（--- 或 ===）
        raw_content = re.sub(r'^[-=]{3,}\s*$', '', raw_content, flags=re.MULTILINE)
        
        # 去除markdown标题格式（### **会议纪要** 或 ## 标题 等）
        # 先去除特定的"会议纪要"标题行（支持多种格式）
        raw_content = re.sub(r'^#{1,6}\s*\*{0,2}\s*会议纪要\s*\*{0,2}\s*$', '', raw_content, flags=re.IGNORECASE | re.MULTILINE)
        # 去除所有markdown标题标记（保留标题文本内容）
        raw_content = re.sub(r'^#{1,6}\s+', '', raw_content, flags=re.MULTILINE)
        
        # 去除markdown粗体格式（**文本**）
        raw_content = re.sub(r'\*\*([^*]+)\*\*', r'\1', raw_content)
        
        # 去除单独的"会议纪要"标题行（去除markdown格式后，可能是纯文本的"会议纪要"）
        # 匹配整行只有"会议纪要"的情况（可能前后有空格或标点）
        raw_content = re.sub(r'^[\s]*会议纪要[\s]*$', '', raw_content, flags=re.IGNORECASE | re.MULTILINE)
        
        # 去除markdown斜体格式（*文本*）
        raw_content = re.sub(r'(?<!\*)\*([^*]+)\*(?!\*)', r'\1', raw_content)
        
        # 去除markdown代码块格式（```代码```）
        raw_content = re.sub(r'```[\s\S]*?```', '', raw_content)
        
        # 去除markdown行内代码格式（`代码`）
        raw_content = re.sub(r'`([^`]+)`', r'\1', raw_content)
        
        # 去除markdown列表标记（- 或 * 或 1.）
        raw_content = re.sub(r'^[\s]*[-*]\s+', '', raw_content, flags=re.MULTILINE)
        raw_content = re.sub(r'^[\s]*\d+\.\s+', '', raw_content, flags=re.MULTILINE)
        
        # 去除多余的空行（连续3个或以上空行替换为2个空行）
        raw_content = re.sub(r'\n{3,}', '\n\n', raw_content)
        
        # 再次去除单独的"会议纪要"标题行（在所有格式处理完成后）
        # 匹配整行只有"会议纪要"的情况，可能前后有空格
        raw_content = re.sub(r'^[\s]*会议纪要[\s]*\n?', '', raw_content, flags=re.IGNORECASE | re.MULTILINE)
        
        # 去除开头的空白字符和空行
        raw_content = raw_content.strip()
        
        # 获取当前本地时间（datetime.now()返回系统本地时间）
        current_time = datetime.now()
        summary = {
            'raw_text': raw_content,
            'generated_at': current_time.strftime('%Y-%m-%d %H:%M:%S'),
            'model': model,
            'status': 'success'
        }
        
        return summary
        
    except Exception as e:
        logger.error(f"生成会议纪要失败: {e}")
        return {
            'raw_text': f"生成会议纪要时发生错误: {str(e)}",
            'generated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'status': 'error',
            'error': str(e)
        }


def generate_default_summary(transcript_data):
    """生成默认会议纪要"""
    speaker_stats = {}
    total_words = 0
    
    for entry in transcript_data:
        speaker = entry.get('speaker', '未知发言人')
        text = entry.get('text', '')
        
        if speaker not in speaker_stats:
            speaker_stats[speaker] = {'count': 0, 'words': 0}
        
        speaker_stats[speaker]['count'] += 1
        speaker_stats[speaker]['words'] += len(text)
        total_words += len(text)
    
    summary_text = f"""## 会议概要
本次会议共有{len(speaker_stats)}位参与者，会议记录共{len(transcript_data)}段发言，总计约{total_words}字。

## 参与人员
"""
    
    for speaker, stats in speaker_stats.items():
        summary_text += f"- {speaker}: 发言{stats['count']}次\n"
    
    return {
        'raw_text': summary_text,
        'generated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),  # 使用系统本地时间
        'model': 'default_template',
        'status': 'success'
    }


def save_meeting_summary_to_word(transcript_data, summary_data, filename_prefix="meeting_summary", file_id=None, audio_filename=None, audio_duration=None):
    """将会议纪要保存为Word文档"""
    
    def set_table_borders_black(table):
        """设置表格边框为黑色"""
        tbl = table._tbl
        tblBorders = OxmlElement('w:tblBorders')
        for border_name in ['top', 'left', 'bottom', 'right', 'insideH', 'insideV']:
            border = OxmlElement(f'w:{border_name}')
            border.set(qn('w:val'), 'single')
            border.set(qn('w:sz'), '4')
            border.set(qn('w:space'), '0')
            border.set(qn('w:color'), '000000')  # 黑色
            tblBorders.append(border)
        tbl.tblPr.append(tblBorders)
    
    try:
        doc = Document()
        
        # 定义黑色（RGB(0,0,0)）
        black_color = RGBColor(0, 0, 0)
        
        title = doc.add_heading('会议纪要', 0)
        title.alignment = WD_ALIGN_PARAGRAPH.CENTER
        # 设置标题为华文中宋 二号字体
        for run in title.runs:
            run.font.name = 'STZhongsong'  # 华文中宋
            run.font.size = Pt(22)  # 二号字体
            run.font.color.rgb = black_color
            run._element.rPr.rFonts.set(qn('w:eastAsia'), '华文中宋')
        
        doc.add_paragraph()
        
        # 计算音频时长（如果未提供，从 transcript_data 计算）
        if audio_duration is None and transcript_data:
            # 从最后一个转写段的结束时间获取总时长
            last_entry = transcript_data[-1] if transcript_data else None
            if last_entry and 'end_time' in last_entry:
                audio_duration = last_entry['end_time']
            else:
                audio_duration = 0
        
        # 格式化时长
        def format_duration(seconds):
            """将秒数格式化为 分钟 秒 的格式"""
            if seconds is None or seconds <= 0:
                return "0分钟 0秒"
            minutes = int(seconds // 60)
            secs = int(seconds % 60)
            return f"{minutes}分钟 {secs}秒"
        
        # 添加生成时间和音频信息
        info_table = doc.add_table(rows=3, cols=2)
        info_table.style = 'Light Grid Accent 1'
        # 设置表格边框为黑色
        set_table_borders_black(info_table)
        
        for row in info_table.rows:
            row.cells[0].width = Inches(1.5)
            row.cells[1].width = Inches(5.0)
        
        # 第一行：生成时间
        info_table.rows[0].cells[0].text = '生成时间'
        label_para = info_table.rows[0].cells[0].paragraphs[0]
        label_para.alignment = WD_ALIGN_PARAGRAPH.CENTER
        label_run = label_para.runs[0]
        label_run.bold = False
        label_run.font.size = Pt(16)  # 三号字体
        label_run.font.name = '仿宋_GB2312'  # 仿宋_GB2312
        label_run.font.color.rgb = black_color
        label_run._element.rPr.rFonts.set(qn('w:eastAsia'), '仿宋_GB2312')
        label_run._element.rPr.rFonts.set(qn('w:ascii'), '仿宋_GB2312')  # 数字和英文字符也使用仿宋_GB2312
        label_run._element.rPr.rFonts.set(qn('w:hAnsi'), '仿宋_GB2312')  # 高ANSI字符也使用仿宋_GB2312
        
        generated_time = summary_data.get('generated_at', datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
        # 转换为更友好的格式：2025年8月31日 下午5:35
        try:
            dt = datetime.strptime(generated_time, '%Y-%m-%d %H:%M:%S')
            formatted_time = dt.strftime('%Y年%m月%d日')
            hour = dt.hour
            minute = dt.minute
            
            # 正确处理上午/下午时间显示
            if hour == 0:
                # 凌晨0点
                time_part = "凌晨0"
            elif hour < 12:
                # 上午1-11点
                time_part = f"上午{hour}"
            elif hour == 12:
                # 中午12点
                time_part = "下午12"
            else:
                # 下午1-11点（13-23点转换为1-11点）
                time_part = f"下午{hour - 12}"
            
            formatted_time = f"{formatted_time} {time_part}:{minute:02d}"
        except Exception as e:
            logger.warning(f"格式化生成时间失败: {e}, 使用原始时间: {generated_time}")
            formatted_time = generated_time
        
        info_table.rows[0].cells[1].text = formatted_time
        value_para = info_table.rows[0].cells[1].paragraphs[0]
        value_para.alignment = WD_ALIGN_PARAGRAPH.CENTER
        value_run = value_para.runs[0]
        value_run.bold = False
        value_run.font.size = Pt(16)  # 三号字体
        value_run.font.name = '仿宋_GB2312'  # 仿宋_GB2312
        value_run.font.color.rgb = black_color
        value_run._element.rPr.rFonts.set(qn('w:eastAsia'), '仿宋_GB2312')
        value_run._element.rPr.rFonts.set(qn('w:ascii'), '仿宋_GB2312')  # 数字和英文字符也使用仿宋_GB2312
        value_run._element.rPr.rFonts.set(qn('w:hAnsi'), '仿宋_GB2312')  # 高ANSI字符也使用仿宋_GB2312
        
        # 第二行：音频时长
        info_table.rows[1].cells[0].text = '音频时长'
        label_para = info_table.rows[1].cells[0].paragraphs[0]
        label_para.alignment = WD_ALIGN_PARAGRAPH.CENTER
        label_run = label_para.runs[0]
        label_run.bold = False
        label_run.font.size = Pt(16)  # 三号字体
        label_run.font.name = '仿宋_GB2312'  # 仿宋_GB2312
        label_run.font.color.rgb = black_color
        label_run._element.rPr.rFonts.set(qn('w:eastAsia'), '仿宋_GB2312')
        label_run._element.rPr.rFonts.set(qn('w:ascii'), '仿宋_GB2312')  # 数字和英文字符也使用仿宋_GB2312
        label_run._element.rPr.rFonts.set(qn('w:hAnsi'), '仿宋_GB2312')  # 高ANSI字符也使用仿宋_GB2312
        
        info_table.rows[1].cells[1].text = format_duration(audio_duration)
        value_para = info_table.rows[1].cells[1].paragraphs[0]
        value_para.alignment = WD_ALIGN_PARAGRAPH.CENTER
        value_run = value_para.runs[0]
        value_run.bold = False
        value_run.font.size = Pt(16)  # 三号字体
        value_run.font.name = '仿宋_GB2312'  # 仿宋_GB2312
        value_run.font.color.rgb = black_color
        value_run._element.rPr.rFonts.set(qn('w:eastAsia'), '仿宋_GB2312')
        value_run._element.rPr.rFonts.set(qn('w:ascii'), '仿宋_GB2312')  # 数字和英文字符也使用仿宋_GB2312
        value_run._element.rPr.rFonts.set(qn('w:hAnsi'), '仿宋_GB2312')  # 高ANSI字符也使用仿宋_GB2312
        
        # 第三行：音频文件名（如果有）
        if audio_filename:
            info_table.rows[2].cells[0].text = '音频文件'
            label_para = info_table.rows[2].cells[0].paragraphs[0]
            label_para.alignment = WD_ALIGN_PARAGRAPH.CENTER
            label_run = label_para.runs[0]
            label_run.bold = False
            label_run.font.size = Pt(16)  # 三号字体
            label_run.font.name = '仿宋_GB2312'  # 仿宋_GB2312
            label_run.font.color.rgb = black_color
            label_run._element.rPr.rFonts.set(qn('w:eastAsia'), '仿宋_GB2312')
            label_run._element.rPr.rFonts.set(qn('w:ascii'), '仿宋_GB2312')  # 数字和英文字符也使用仿宋_GB2312
            label_run._element.rPr.rFonts.set(qn('w:hAnsi'), '仿宋_GB2312')  # 高ANSI字符也使用仿宋_GB2312
            
            info_table.rows[2].cells[1].text = audio_filename
            value_para = info_table.rows[2].cells[1].paragraphs[0]
            value_para.alignment = WD_ALIGN_PARAGRAPH.CENTER
            value_run = value_para.runs[0]
            value_run.bold = False
            value_run.font.size = Pt(16)  # 三号字体
            value_run.font.name = '仿宋_GB2312'  # 仿宋_GB2312
            value_run.font.color.rgb = black_color
            value_run._element.rPr.rFonts.set(qn('w:eastAsia'), '仿宋_GB2312')
            value_run._element.rPr.rFonts.set(qn('w:ascii'), '仿宋_GB2312')  # 数字和英文字符也使用仿宋_GB2312
            value_run._element.rPr.rFonts.set(qn('w:hAnsi'), '仿宋_GB2312')  # 高ANSI字符也使用仿宋_GB2312
        else:
            # 如果没有音频文件名，隐藏第三行
            info_table.rows[2].cells[0].text = ''
            info_table.rows[2].cells[1].text = ''
        
        doc.add_paragraph()
        
        # 添加纪要内容，智能识别标题、表格等格式
        # 标记是否已添加关键词（在会议主题、主持人、参会人数之后）
        raw_text = summary_data.get('raw_text', '')
        lines = raw_text.split('\n')
        
        # 跟踪一级标题和二级标题序号
        current_level1_title = None  # 当前一级标题（一、二、三等）
        level2_counter = 0  # 二级标题计数器
        chinese_numerals = ['一', '二', '三', '四', '五', '六', '七', '八', '九', '十', 
                           '十一', '十二', '十三', '十四', '十五', '十六', '十七', '十八', '十九', '二十']
        
        i = 0
        while i < len(lines):
            line = lines[i].strip()
            
            # 跳过空行
            if not line:
                doc.add_paragraph()
                i += 1
                continue
            
            # 如果当前行是"关键词"行，标记为已处理，继续处理后续行
            if line.strip() == '关键词':
                # 关键词标题行，按普通文本处理
                para = doc.add_paragraph(line)
                para.alignment = WD_ALIGN_PARAGRAPH.LEFT
                para.paragraph_format.space_before = Pt(0)
                para.paragraph_format.space_after = Pt(6)
                para.paragraph_format.line_spacing = 1.0
                for run in para.runs:
                    run.bold = False
                    run.font.name = '仿宋_GB2312'
                    run.font.size = Pt(16)  # 三号字体
                    run.font.color.rgb = black_color
                    run._element.rPr.rFonts.set(qn('w:eastAsia'), '仿宋_GB2312')
                    run._element.rPr.rFonts.set(qn('w:ascii'), '仿宋_GB2312')
                    run._element.rPr.rFonts.set(qn('w:hAnsi'), '仿宋_GB2312')
                
                # 检查下一行是否是关键词内容
                if i + 1 < len(lines) and lines[i + 1].strip() and lines[i + 1].strip() != '':
                    i += 1
                    keywords_content = lines[i].strip()
                    if keywords_content:  # 如果下一行是关键词内容
                        keywords_para = doc.add_paragraph(keywords_content)
                        keywords_para.alignment = WD_ALIGN_PARAGRAPH.LEFT
                        keywords_para.paragraph_format.space_before = Pt(0)
                        keywords_para.paragraph_format.space_after = Pt(0)
                        keywords_para.paragraph_format.line_spacing = 1.15
                        for run in keywords_para.runs:
                            run.bold = False
                            run.font.name = '仿宋_GB2312'
                            run.font.size = Pt(16)  # 三号字体
                            run.font.color.rgb = black_color
                            run._element.rPr.rFonts.set(qn('w:eastAsia'), '仿宋_GB2312')
                            run._element.rPr.rFonts.set(qn('w:ascii'), '仿宋_GB2312')
                            run._element.rPr.rFonts.set(qn('w:hAnsi'), '仿宋_GB2312')
                
                i += 1
                continue
            
            # 检测表格：查找包含"序号"、"事项描述"等表头的行
            if '序号' in line and ('事项描述' in line or '负责人' in line or '备注' in line):
                # 这是一个表格，开始解析表格
                table_data = []
                headers = []
                
                # 解析表头
                if '|' in line:
                    # Markdown表格格式
                    header_line = line
                    if header_line.startswith('|') and header_line.endswith('|'):
                        headers = [h.strip() for h in header_line.split('|')[1:-1]]
                        i += 1
                        # 跳过分隔行（如 |---|---|）
                        if i < len(lines) and '|' in lines[i] and ('---' in lines[i] or ':-' in lines[i]):
                            i += 1
                else:
                    # 文本格式的表格，从当前行提取表头
                    # 按常见分隔符分割（空格、制表符等）
                    parts = re.split(r'\s{2,}|\t|：|:', line)
                    headers = [p.strip() for p in parts if p.strip() and len(p.strip()) > 0]
                    # 如果分割失败，使用默认表头
                    if not headers or len(headers) < 2:
                        headers = ['序号', '事项描述', '负责人', '备注/期望结果']
                    i += 1
                
                # 如果没有找到表头，使用默认表头
                if not headers:
                    headers = ['序号', '事项描述', '负责人', '备注/期望结果']
                
                # 解析表格数据行
                current_row = []
                row_number = 1
                
                while i < len(lines):
                    data_line = lines[i].strip()
                    
                    # 空行可能表示表格结束或行内分隔
                    if not data_line:
                        # 如果当前行有数据，保存它
                        if current_row:
                            if len(current_row) < len(headers):
                                # 补齐到表头数量
                                while len(current_row) < len(headers):
                                    current_row.append('')
                            table_data.append(current_row[:len(headers)])
                            current_row = []
                        i += 1
                        # 如果连续两个空行，结束表格
                        if i < len(lines) and not lines[i].strip():
                            break
                        continue
                    
                    # 检测是否是表格数据行
                    if '|' in data_line:
                        # Markdown表格格式
                        if data_line.startswith('|') and data_line.endswith('|'):
                            row_data = [d.strip() for d in data_line.split('|')[1:-1]]
                            if len(row_data) >= len(headers):
                                table_data.append(row_data[:len(headers)])
                            i += 1
                        else:
                            break
                    elif re.match(r'^\d+[\.、]', data_line):
                        # 数字开头的行，新的表格行开始
                        # 如果之前有未完成的行，先保存
                        if current_row:
                            while len(current_row) < len(headers):
                                current_row.append('')
                            table_data.append(current_row[:len(headers)])
                        
                        # 开始新行：序号
                        match = re.match(r'^(\d+)[\.、]\s*(.*)', data_line)
                        if match:
                            row_number = match.group(1)
                            rest = match.group(2).strip()
                            current_row = [row_number, rest]
                        else:
                            current_row = [str(row_number), data_line]
                        row_number += 1
                        i += 1
                    elif current_row and len(current_row) < len(headers):
                        # 当前行的后续列数据
                        # 判断是新列还是当前列的延续
                        # 如果包含"发言人"、"负责人"等关键词，可能是新列
                        is_new_column = False
                        if len(current_row) >= 2:  # 序号和事项描述已存在
                            # 检查是否包含负责人相关的关键词
                            if any(keyword in data_line for keyword in ['发言人', '负责人', 'Speaker']):
                                is_new_column = True
                            # 检查是否包含备注相关的关键词
                            elif len(current_row) >= 3 and any(keyword in data_line for keyword in ['评估', '备注', '期望', '结果']):
                                is_new_column = True
                        
                        if is_new_column or len(current_row) == 0:
                            # 新列
                            current_row.append(data_line)
                        else:
                            # 当前列的延续，追加到最后一列
                            last_col_idx = len(current_row) - 1
                            if last_col_idx >= 0:
                                current_row[last_col_idx] += '\n' + data_line
                        i += 1
                    else:
                        # 不是表格数据，结束表格解析
                        if current_row:
                            while len(current_row) < len(headers):
                                current_row.append('')
                            table_data.append(current_row[:len(headers)])
                        break
                
                # 保存最后一行
                if current_row:
                    while len(current_row) < len(headers):
                        current_row.append('')
                    table_data.append(current_row[:len(headers)])
                
                # 创建Word表格（包括表头行）
                if table_data or headers:
                    try:
                        # 表格行数 = 表头(1行) + 数据行数
                        table = doc.add_table(rows=len(table_data) + 1, cols=len(headers))
                        table.style = 'Light Grid Accent 1'
                        # 设置表格边框为黑色
                        set_table_borders_black(table)
                        
                        # 设置表头
                        header_row = table.rows[0]
                        for j, header in enumerate(headers):
                            if j < len(header_row.cells):
                                cell = header_row.cells[j]
                                cell.text = header
                                para = cell.paragraphs[0]
                                para.alignment = WD_ALIGN_PARAGRAPH.CENTER
                                for run in para.runs:
                                    run.bold = False
                                    run.font.name = '仿宋_GB2312'  # 仿宋_GB2312
                                    run.font.size = Pt(16)  # 三号字体
                                    run.font.color.rgb = black_color
                                    run._element.rPr.rFonts.set(qn('w:eastAsia'), '仿宋_GB2312')
                                    run._element.rPr.rFonts.set(qn('w:ascii'), '仿宋_GB2312')  # 数字和英文字符也使用仿宋_GB2312
                                    run._element.rPr.rFonts.set(qn('w:hAnsi'), '仿宋_GB2312')  # 高ANSI字符也使用仿宋_GB2312
                        
                        # 填充数据
                        for row_idx, row_data in enumerate(table_data):
                            if row_idx + 1 < len(table.rows):
                                row = table.rows[row_idx + 1]  # +1 因为第一行是表头
                                for col_idx, cell_data in enumerate(row_data):
                                    if col_idx < len(row.cells) and col_idx < len(headers):
                                        cell = row.cells[col_idx]
                                        cell.text = str(cell_data) if cell_data else ''
                                        para = cell.paragraphs[0]
                                        para.alignment = WD_ALIGN_PARAGRAPH.LEFT
                                        for run in para.runs:
                                            run.font.name = '仿宋_GB2312'  # 仿宋_GB2312
                                            run.font.size = Pt(16)  # 三号字体
                                            run.font.color.rgb = black_color
                                            run._element.rPr.rFonts.set(qn('w:eastAsia'), '仿宋_GB2312')
                                            run._element.rPr.rFonts.set(qn('w:ascii'), '仿宋_GB2312')  # 数字和英文字符也使用仿宋_GB2312
                                            run._element.rPr.rFonts.set(qn('w:hAnsi'), '仿宋_GB2312')  # 高ANSI字符也使用仿宋_GB2312
                    except Exception as e:
                        logger.error(f"创建表格失败: {e}")
                        # 如果表格创建失败，按普通文本处理
                        para = doc.add_paragraph(line)
                        for run in para.runs:
                            run.font.name = '仿宋_GB2312'  # 仿宋_GB2312
                            run.font.size = Pt(16)  # 三号字体
                            run.font.color.rgb = black_color
                            run._element.rPr.rFonts.set(qn('w:eastAsia'), '仿宋_GB2312')
                            run._element.rPr.rFonts.set(qn('w:ascii'), '仿宋_GB2312')  # 数字和英文字符也使用仿宋_GB2312
                            run._element.rPr.rFonts.set(qn('w:hAnsi'), '仿宋_GB2312')  # 高ANSI字符也使用仿宋_GB2312
                
                doc.add_paragraph()
                continue
            
            # 通用标题识别规则（不依赖硬编码标签列表）
            # 识别规则优先级：
            # 1. Markdown格式的标题（**标题**）
            # 2. 章节标题（一、二、三等中文数字开头）
            # 3. 数字编号标题（1. 2. 等）
            # 4. 以冒号结尾的行（可能是标题）
            is_title = False
            title_text = line
            title_size = Pt(14)  # 默认标题大小（大标题）
            
            # 先去除markdown格式，便于后续判断
            clean_line = re.sub(r'^\*\*|\*\*$', '', line).strip()
            
            # 规则1：Markdown格式的标题（**标题** 或 **标题:**）
            if re.match(r'^\*\*.*?\*\*', line):
                is_title = True
                title_text = clean_line
                # 如果以冒号结尾，是小标题
                if clean_line.endswith(':') or clean_line.endswith('：'):
                    title_size = Pt(12)  # 小标题
                else:
                    title_size = Pt(14)  # 大标题
            
            # 规则2：章节标题（中文数字开头：一、二、三等）
            elif re.match(r'^[一二三四五六七八九十]+[、.]', clean_line):
                is_title = True
                title_text = clean_line
                title_size = Pt(16)  # 三号字体（黑体）
                # 更新当前一级标题，重置二级标题计数器
                current_level1_title = clean_line
                level2_counter = 0
            
            # 规则3：数字编号标题（1. 2. 等，但排除纯数字行）
            elif re.match(r'^\d+[、.]\s+', clean_line) and len(clean_line) > 3:
                is_title = True
                title_text = clean_line
                title_size = Pt(16)  # 三号字体（黑体）
            
            # 规则3.5：带括号的中文数字标题（（一）、（二）等）- 使用楷体_GB2312
            elif re.match(r'^[（(][一二三四五六七八九十]+[）)]', clean_line):
                is_title = True
                title_text = clean_line
                title_size = Pt(16)  # 三号字体（楷体_GB2312）
            
            # 规则4：以冒号结尾的行（可能是标题）
            elif clean_line.endswith(':') or clean_line.endswith('：'):
                # 排除明显是正文的情况：
                # - 包含句号、逗号、顿号等标点（可能是正文）
                # - 长度过长（超过120字符可能是正文）
                # - 包含明显的正文特征（如"的"、"了"等常见助词过多）
                if not re.search(r'[。，、]', clean_line) and len(clean_line) < 120:
                    # 进一步检查：如果标题部分（冒号前）包含过多助词，可能是正文
                    title_part = clean_line.rstrip('：:').strip()
                    # 计算助词密度（的、了、在、是等）
                    particle_count = len(re.findall(r'[的了在是就有]', title_part))
                    # 如果助词数量超过标题长度的10%，可能是正文
                    if particle_count < len(title_part) * 0.1:
                        is_title = True
                        # 如果当前有一级标题，且这个小标题没有序号，自动添加序号
                        if current_level1_title and not re.match(r'^[（(][一二三四五六七八九十]+[）)]', title_part):
                            level2_counter += 1
                            if level2_counter <= len(chinese_numerals):
                                title_text = f"（{chinese_numerals[level2_counter - 1]}）{clean_line}"
                            else:
                                title_text = clean_line
                        else:
                            title_text = clean_line
                        title_size = Pt(16)  # 三号字体（楷体_GB2312，因为是小标题）
            
            # 规则5：标题后跟内容的情况（如 "标题: 内容"）
            if not is_title:
                label_content_match = re.match(r'^(\*\*)?([^：:*]+?)(\*\*)?[:：]\s+(.+)$', line)
                if label_content_match:
                    potential_label = label_content_match.group(2).strip()
                    # 检查标签部分是否符合标题特征：
                    # - 长度合理（不超过100字符）
                    # - 不包含句号、逗号等
                    # - 助词密度低
                    if (len(potential_label) < 100 and 
                        not re.search(r'[。，、]', potential_label)):
                        particle_count = len(re.findall(r'[的了在是就有]', potential_label))
                        if particle_count < len(potential_label) * 0.1:
                            is_title = True
                            # 如果当前有一级标题，且这个小标题没有序号，自动添加序号
                            clean_potential_label = re.sub(r'^\*\*|\*\*$', '', potential_label).strip()
                            content_part = label_content_match.group(4).strip()
                            
                            if current_level1_title and not re.match(r'^[（(][一二三四五六七八九十]+[）)]', clean_potential_label):
                                level2_counter += 1
                                if level2_counter <= len(chinese_numerals):
                                    numbered_label = f"（{chinese_numerals[level2_counter - 1]}）{clean_potential_label}"
                                    # 重新构建标题文本，保留markdown格式（如果有）
                                    if line.startswith('**') and line.count('**') >= 2:
                                        title_text = f"**{numbered_label}**：{content_part}"
                                    else:
                                        title_text = f"{numbered_label}：{content_part}"
                                else:
                                    title_text = re.sub(r'^\*\*|\*\*$', '', line).strip()
                            else:
                                title_text = re.sub(r'^\*\*|\*\*$', '', line).strip()
                            title_size = Pt(16)  # 三号字体（楷体_GB2312，因为是小标题）
            
            if is_title:
                # 判断标题类型，设置对应的字体
                # 检查是否是（一）、（二）等格式 - 使用楷体_GB2312
                is_bracketed_title = re.match(r'^[（(][一二三四五六七八九十]+[）)]', title_text)
                # 检查是否是一、二、三等格式 - 使用黑体
                is_chinese_num_title = re.match(r'^[一二三四五六七八九十]+[、.]', title_text)
                
                # 添加标题段落，加粗显示，左对齐
                para = doc.add_paragraph()
                para.alignment = WD_ALIGN_PARAGRAPH.LEFT
                # 设置段落间距为紧凑
                para.paragraph_format.space_before = Pt(0)
                para.paragraph_format.space_after = Pt(6)  # 标题后间距
                para.paragraph_format.line_spacing = 1.0  # 单倍行距
                # 检查是否是小标题（以冒号结尾，且不是一级标题）- 使用楷体_GB2312
                is_small_title = (not is_chinese_num_title and not is_bracketed_title and 
                                 (title_text.endswith(':') or title_text.endswith('：')) and
                                 current_level1_title is not None)
                
                # 检查是否是标签后跟内容的情况（如 "会议主题: 内容"）
                label_content_match = re.match(r'^([^：:]+?)[:：]\s+(.+)$', title_text)
                if label_content_match:
                    # 标签和内容分开处理：标签加粗，内容不加粗
                    label_part = label_content_match.group(1).strip() + ': '
                    content_part = label_content_match.group(2).strip()
                    
                    # 添加标签部分（加粗）
                    label_run = para.add_run(label_part)
                    label_run.bold = False
                    if is_bracketed_title or is_small_title:
                        # （一）、（二）等标题或小标题使用楷体_GB2312
                        label_run.font.name = 'KaiTi_GB2312'
                        label_run._element.rPr.rFonts.set(qn('w:eastAsia'), '楷体_GB2312')
                    elif is_chinese_num_title:
                        # 一、二、三等标题使用黑体
                        label_run.font.name = 'SimHei'
                        label_run._element.rPr.rFonts.set(qn('w:eastAsia'), '黑体')
                    else:
                        # 其他标题使用黑体
                        label_run.font.name = 'SimHei'
                        label_run._element.rPr.rFonts.set(qn('w:eastAsia'), '黑体')
                    label_run.font.size = title_size
                    label_run.font.color.rgb = black_color
                    
                    # 添加内容部分（不加粗，使用仿宋_GB2312）
                    content_run = para.add_run(content_part)
                    content_run.bold = False
                    content_run.font.name = '仿宋_GB2312'
                    content_run.font.size = Pt(16)  # 三号字体
                    content_run.font.color.rgb = black_color
                    content_run._element.rPr.rFonts.set(qn('w:eastAsia'), '仿宋_GB2312')
                    content_run._element.rPr.rFonts.set(qn('w:ascii'), '仿宋_GB2312')  # 数字和英文字符也使用仿宋_GB2312
                    content_run._element.rPr.rFonts.set(qn('w:hAnsi'), '仿宋_GB2312')  # 高ANSI字符也使用仿宋_GB2312
                else:
                    # 整行都是标题，全部加粗
                    run = para.add_run(title_text)
                    run.bold = False
                    if is_bracketed_title or is_small_title:
                        # （一）、（二）等标题或小标题使用楷体_GB2312
                        run.font.name = 'KaiTi_GB2312'
                        run._element.rPr.rFonts.set(qn('w:eastAsia'), '楷体_GB2312')
                    elif is_chinese_num_title:
                        # 一、二、三等标题使用黑体
                        run.font.name = 'SimHei'
                        run._element.rPr.rFonts.set(qn('w:eastAsia'), '黑体')
                    else:
                        # 其他标题使用黑体
                        run.font.name = 'SimHei'
                        run._element.rPr.rFonts.set(qn('w:eastAsia'), '黑体')
                    run.font.size = title_size
                    run.font.color.rgb = black_color
            else:
                # 普通文本段落，左对齐，不加粗，使用仿宋_GB2312 三号字体
                para = doc.add_paragraph()
                para.alignment = WD_ALIGN_PARAGRAPH.LEFT
                # 设置段落间距为紧凑
                para.paragraph_format.space_before = Pt(0)
                para.paragraph_format.space_after = Pt(0)  # 段落间距为0
                para.paragraph_format.line_spacing = 1.15  # 1.15倍行距，稍微紧凑
                run = para.add_run(line)
                run.bold = False  # 明确设置为不加粗
                run.font.name = '仿宋_GB2312'  # 仿宋_GB2312
                run.font.size = Pt(16)  # 三号字体
                run.font.color.rgb = black_color
                run._element.rPr.rFonts.set(qn('w:eastAsia'), '仿宋_GB2312')
                run._element.rPr.rFonts.set(qn('w:ascii'), '仿宋_GB2312')  # 数字和英文字符也使用仿宋_GB2312
                run._element.rPr.rFonts.set(qn('w:hAnsi'), '仿宋_GB2312')  # 高ANSI字符也使用仿宋_GB2312
            
            i += 1
        
        # ✅ 使用微秒级时间戳 + file_id 确保文件名唯一性
        now = datetime.now()
        timestamp = now.strftime('%Y%m%d_%H%M%S_%f')  # 包含微秒
        
        # 如果提供了 file_id，使用前8个字符作为唯一标识
        if file_id:
            file_id_short = file_id.replace('-', '')[:8]  # 移除连字符，取前8位
            filename = f"{filename_prefix}_{timestamp}_{file_id_short}.docx"
        else:
            filename = f"{filename_prefix}_{timestamp}.docx"
        
        # 使用单独的会议纪要目录
        summary_dir = FILE_CONFIG.get('summary_dir', 'meeting_summaries')
        # 确保目录存在
        if not os.path.exists(summary_dir):
            os.makedirs(summary_dir, exist_ok=True)
            logger.info(f"创建会议纪要目录: {summary_dir}")
        
        filepath = os.path.join(summary_dir, filename)
        
        doc.save(filepath)
        return filename, filepath
        
    except Exception as e:
        logger.error(f"保存会议纪要Word文档失败: {e}")
        return None, None


# ==================== API路由 ====================

# ==================== RESTful文件资源接口 ====================

@router.get("/files")
async def list_all_files(
    filepath: Optional[str] = None,
    status: Optional[str] = None,
    limit: Optional[int] = None,
    offset: int = 0,
    include_history: bool = False,
    download: int = 0
):
    """
    📋 列出所有文件（RESTful风格，方案2优化）
    
    查询参数：
    - filepath: 可选，如果提供则直接返回该路径的音频文件（类似 /api/voice/files/{file_id}）
    - status: 过滤状态 (uploaded/processing/completed/error)
    - limit: 返回数量限制
    - offset: 分页偏移量
    - include_history: 是否包含历史记录，默认False
    - download: 当提供filepath时，是否下载（0=预览，1=下载）
    
    返回：文件列表及统计信息，或音频文件（当提供filepath时）
    """
    try:
        # 如果提供了filepath，直接返回音频文件
        if filepath:
            # 安全检查：防止路径遍历攻击
            # 规范化路径并确保在允许的目录内
            normalized_path = os.path.normpath(filepath)
            
            # 检查路径是否在uploads目录内
            upload_dir = os.path.abspath(FILE_CONFIG['upload_dir'])
            file_full_path = os.path.abspath(normalized_path)
            
            # 确保文件路径在uploads目录内
            if not file_full_path.startswith(upload_dir):
                raise HTTPException(status_code=403, detail="文件路径不在允许的目录内")
            
            # 检查文件是否存在
            if not os.path.exists(file_full_path):
                raise HTTPException(status_code=404, detail="音频文件不存在")
            
            # 检查是否为文件（不是目录）
            if not os.path.isfile(file_full_path):
                raise HTTPException(status_code=400, detail="指定路径不是文件")
            
            # 获取文件名（用于下载时的文件名）
            filename = os.path.basename(file_full_path)
            
            if download == 1:
                return FileResponse(
                    file_full_path,
                    media_type='application/octet-stream',
                    filename=filename
                )
            else:
                return FileResponse(
                    file_full_path,
                    media_type='audio/mpeg'
                )
        
        # 如果需要历史记录，从文件加载
        if include_history:
            load_history_from_file()
        
        # 获取所有文件
        all_files = uploaded_files_manager.get_all_files()
        
        # 根据状态过滤
        if status:
            filtered_files = [f for f in all_files if f['status'] == status]
        else:
            filtered_files = all_files
        
        # 排序：processing > uploaded > completed > error
        status_priority = {'processing': 0, 'uploaded': 1, 'completed': 2, 'error': 3}
        filtered_files.sort(key=lambda x: (
            status_priority.get(x['status'], 999),
            x.get('upload_time', '')
        ), reverse=True)
        
        # 分页
        total_count = len(filtered_files)
        if limit:
            filtered_files = filtered_files[offset:offset+limit]
        else:
            filtered_files = filtered_files[offset:]
        
        # 🔧 为每个文件添加可访问的下载URL
        for file_info in filtered_files:
            # 添加音频下载链接
            if 'download_urls' not in file_info:
                file_info['download_urls'] = {}
            file_info['download_urls']['audio'] = f"/api/voice/audio/{file_info['id']}?download=1"
            
            # 添加转写文档下载链接（如果存在）
            if file_info.get('transcript_file'):
                file_info['download_urls']['transcript'] = f"/api/voice/download_transcript/{file_info['id']}"
            
            # 添加会议纪要下载链接（如果存在）
            if file_info.get('meeting_summary'):
                file_info['download_urls']['summary'] = f"/api/voice/download_summary/{file_info['id']}"
        
        # 统计信息
        status_counts = {
            'uploaded': len([f for f in all_files if f['status'] == 'uploaded']),
            'processing': len([f for f in all_files if f['status'] == 'processing']),
            'completed': len([f for f in all_files if f['status'] == 'completed']),
            'error': len([f for f in all_files if f['status'] == 'error'])
        }
        
        return {
            'success': True,
            'files': filtered_files,
            'pagination': {
                'total': total_count,
                'limit': limit,
                'offset': offset,
                'returned': len(filtered_files)
            },
            'statistics': status_counts
        }
        
    except Exception as e:
        logger.error(f"列出文件失败: {e}")
        return JSONResponse({
            'success': False,
            'message': f'获取文件列表失败: {str(e)}'
        }, status_code=500)


@router.get("/files/{file_id}")
async def get_file_detail(
    file_id: str,
    include_transcript: bool = False,
    include_summary: bool = False
):
    """
    📄 获取文件详情（RESTful风格，方案2优化）
    
    路径参数：
    - file_id: 文件ID
    
    查询参数：
    - include_transcript: 是否包含转写结果，默认False
    - include_summary: 是否包含会议纪要，默认False
    
    返回：文件详细信息
    """
    try:
        file_info = next((f for f in uploaded_files_manager.get_all_files() if f['id'] == file_id), None)
        
        if not file_info:
            raise HTTPException(status_code=404, detail='文件不存在')
        
        # 构建基本响应
        result = {
            'success': True,
            'file': {
                'id': file_info['id'],
                'filename': file_info.get('original_name', file_info.get('filename')),
                'size': file_info.get('size', 0),
                'status': file_info['status'],
                'progress': file_info.get('progress', 0),
                'language': file_info.get('language', 'zh'),
                'upload_time': file_info.get('upload_time'),
                'complete_time': file_info.get('complete_time'),
                'error_message': file_info.get('error_message', '')
            }
        }
        
        # 添加下载链接
        result['file']['download_urls'] = {
            'audio': f"/api/voice/audio/{file_id}?download=1"
        }
        
        if file_info.get('transcript_file'):
            result['file']['download_urls']['transcript'] = f"/api/voice/download_transcript/{file_id}"
        
        if file_info.get('meeting_summary'):
            result['file']['download_urls']['summary'] = f"/api/voice/download_summary/{file_id}"
        
        # 可选：包含转写结果
        if include_transcript and file_info['status'] == 'completed':
            transcript_data = file_info.get('transcript_data', [])
            result['transcript'] = transcript_data
            
            # 添加统计信息
            if transcript_data:
                speakers = set(t.get('speaker', '') for t in transcript_data if t.get('speaker'))
                result['statistics'] = {
                    'speakers_count': len(speakers),
                    'segments_count': len(transcript_data),
                    'total_characters': sum(len(t.get('text', '')) for t in transcript_data),
                    'speakers': list(speakers)
                }
        
        # 可选：包含会议纪要
        if include_summary and file_info.get('meeting_summary'):
            result['summary'] = file_info['meeting_summary']
        
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取文件详情失败: {e}")
        raise HTTPException(status_code=500, detail=f'获取文件详情失败: {str(e)}')


@router.patch("/files/{file_id}")
async def update_file(file_id: str, request: Request):
    """
    🔄 更新文件（RESTful风格，方案2优化）
    
    路径参数：
    - file_id: 文件ID
    
    请求体：
    - action: 操作类型 (retranscribe)
    - language: 语言（重新转写时）
    - hotword: 热词（重新转写时）
    
    返回：更新后的文件信息
    """
    try:
        body = await request.json()
        action = body.get('action')
        
        file_info = next((f for f in uploaded_files_manager.get_all_files() if f['id'] == file_id), None)
        
        if not file_info:
            raise HTTPException(status_code=404, detail='文件不存在')
        
        if action == 'retranscribe':
            # 重新转写
            if file_info['status'] == 'processing':
                raise HTTPException(status_code=400, detail='文件正在处理中')
            
            language = body.get('language', file_info.get('language', 'zh'))
            hotword = body.get('hotword', '')
            
            # 重置状态
            file_info['status'] = 'processing'
            file_info['progress'] = 0
            file_info['language'] = language
            
            # 提交转写任务
            def retranscribe_task():
                try:
                    def update_progress(step, progress, message="", transcript_entry=None):
                        file_info['progress'] = progress
                        send_ws_message_sync(file_id, 'processing', progress, message)
                    
                    # ✅ 执行转写（不再需要全局锁）
                    # ✅ 修复：直接传递 callback，避免多任务共享状态冲突
                    transcript, _, _ = pipeline_service.execute_transcription(
                        file_info['filepath'],
                        hotword=hotword,
                        language=language,
                        instance_id=file_id,
                        callback=update_progress  # 直接传递 callback，每个任务有独立的 tracker
                    )
                    
                    if transcript:
                        file_info['transcript_data'] = transcript
                        # ✅ 修复：传入 file_id 确保每个文件生成唯一的转写文档文件名
                        filename, filepath = save_transcript_to_word(
                            transcript, language=language,
                            audio_filename=file_info['original_name'],
                            file_id=file_id
                        )
                        if filename:
                            file_info['transcript_file'] = filepath
                        
                        file_info['status'] = 'completed'
                        file_info['progress'] = 100
                        file_info['complete_time'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                        save_history_to_file()
                        send_ws_message_sync(file_id, 'completed', 100, '重新转写完成')
                    else:
                        file_info['status'] = 'error'
                        file_info['error_message'] = '重新转写失败'
                        send_ws_message_sync(file_id, 'error', 0, '重新转写失败')
                        
                except Exception as e:
                    logger.error(f"重新转写失败: {e}")
                    file_info['status'] = 'error'
                    file_info['error_message'] = str(e)
                    send_ws_message_sync(file_id, 'error', 0, f"重新转写失败: {str(e)}")
            
            TRANSCRIPTION_THREAD_POOL.submit(retranscribe_task)
            
            return {
                'success': True,
                'message': '已开始重新转写',
                'file_id': file_id,
                'status': 'processing'
            }
        
        else:
            raise HTTPException(status_code=400, detail=f'不支持的操作: {action}')
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"更新文件失败: {e}")
        raise HTTPException(status_code=500, detail=f'更新文件失败: {str(e)}')


# ==================== 原有接口（保持向后兼容） ====================

@router.post("/upload")
async def upload_audio(audio_files: List[UploadFile] = File(..., alias="audio_file")):
    """
    上传音频文件（支持单个或多个文件）
    
    参数：
    - audio_files: 文件列表（表单字段名：audio_file，支持多个同名字段）
    
    使用方式：
    - 单个文件：form-data 中一个 audio_file 字段
    - 多个文件：form-data 中多个 audio_file 字段
    
    返回：
    - 单个文件：保持向后兼容，返回 {success, message, file, file_id}
    - 多个文件：返回 {success, message, files, file_ids, failed_files}
    """
    
    if not audio_files:
        return JSONResponse({'success': False, 'message': '没有选择文件'}, status_code=400)
    
    # 验证所有文件格式
    for audio_file in audio_files:
        if not audio_file.filename:
            return JSONResponse({'success': False, 'message': '存在空文件名的文件'}, status_code=400)
        if not allowed_file(audio_file.filename):
            return JSONResponse({
                'success': False, 
                'message': f'文件 {audio_file.filename} 格式不支持，支持的格式：mp3, wav, m4a, flac, aac, ogg, wma'
            }, status_code=400)
    
    uploaded_files = []
    failed_files = []
    
    for audio_file in audio_files:
        try:
            filename = secure_filename(audio_file.filename)
            # 使用微秒级时间戳确保批量上传时文件名唯一
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S_%f')
            name, ext = os.path.splitext(filename)
            safe_filename = f"{name}_{timestamp}{ext}"
            
            contents = await audio_file.read()
            file_size = len(contents)
            filepath = audio_storage.save_uploaded_file(contents, safe_filename)
            
            file_id = str(uuid.uuid4())
            
            file_info = {
                'id': file_id,
                'filename': safe_filename,
                'original_name': audio_file.filename,
                'filepath': filepath,
                'size': file_size,
                'upload_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'status': 'uploaded',
                'progress': 0,
                'error_message': ''
            }
            
            uploaded_files_manager.add_file(file_info)
            uploaded_files.append(file_info)
            logger.info(f"文件上传成功: {audio_file.filename}, ID: {file_id}")
            
            # --- 发送上传成功事件到 Dify ---
            if DIFY_ALARM_ENABLED:
                log_upload_event(
                    file_id=file_id,
                    filename=audio_file.filename,
                    file_size=file_size,
                    level="SUCCESS"
                )
            
        except Exception as e:
            logger.error(f"文件上传失败 {audio_file.filename}: {e}")
            failed_files.append({
                'filename': audio_file.filename,
                'error': str(e)
            })
            
            # --- 发送上传失败事件到 Dify ---
            if DIFY_ALARM_ENABLED:
                try:
                    file_id_temp = str(uuid.uuid4())
                    log_upload_event(
                        file_id=file_id_temp,
                        filename=audio_file.filename,
                        file_size=0,
                        level="ERROR",
                        error=e
                    )
                except:
                    pass
    
    # 返回结果
    if not uploaded_files:
        return JSONResponse({
            'success': False, 
            'message': '所有文件上传失败',
            'failed_files': failed_files
        }, status_code=500)
    
    # 统一返回格式：始终包含 files 和 file_ids 数组，方便模板转换节点使用
    # 单个文件时，同时保留 file 和 file_id 字段以保持向后兼容
    result = {
        'success': True,
        'message': f'成功上传 {len(uploaded_files)} 个文件' if len(uploaded_files) > 1 else '文件上传成功',
        'files': uploaded_files,
        'file_ids': [f['id'] for f in uploaded_files]  # 方便批量转写和模板转换
    }
    
    # 单个文件时，添加向后兼容字段
    if len(uploaded_files) == 1:
        result['file'] = uploaded_files[0]
        result['file_id'] = uploaded_files[0]['id']
    
    # 如果有失败的文件，添加失败信息
    if failed_files:
        result['failed_files'] = failed_files
    
    return result


def clean_transcript_words(transcript_data):
    """
    清理 transcript 中的 words 字段，只保留基本转写信息
    """
    if not transcript_data:
        return transcript_data
    
    cleaned = []
    for entry in transcript_data:
        cleaned_entry = {
            'speaker': entry.get('speaker', ''),
            'text': entry.get('text', ''),
            'start_time': entry.get('start_time', 0),
            'end_time': entry.get('end_time', 0)
        }
        cleaned.append(cleaned_entry)
    
    return cleaned


@router.post("/transcribe")
async def transcribe(request: Request):
    """开始转写（支持批量和并发处理；支持等待完成再返回）"""
    global TRANSCRIPTION_THREAD_POOL
    
    try:
        body = await request.json()
        
        # ✅ 兼容模式：同时支持 file_id (单个) 和 file_ids (数组)
        file_ids = body.get('file_ids', [])
        file_id = body.get('file_id', '')
        
        # 如果提供了单个 file_id，转换为数组
        if file_id and not file_ids:
            file_ids = [file_id]
        # 如果 file_ids 是字符串，尝试解析（可能是 JSON 字符串、Python 列表字符串或单个 ID）
        elif isinstance(file_ids, str):
            # 先尝试解析 JSON 字符串（Dify 模板转换可能输出 JSON 字符串）
            try:
                parsed = json.loads(file_ids)
                if isinstance(parsed, list):
                    file_ids = parsed
                else:
                    file_ids = [parsed]
            except (json.JSONDecodeError, TypeError):
                # 如果不是 JSON，尝试解析 Python 列表字符串格式（如 "['id1', 'id2']"）
                try:
                    # 使用 ast.literal_eval 安全解析 Python 字面量
                    import ast
                    parsed = ast.literal_eval(file_ids)
                    if isinstance(parsed, list):
                        file_ids = parsed
                    else:
                        file_ids = [parsed]
                except (ValueError, SyntaxError):
                    # 如果都解析失败，当作单个 ID 处理
                    file_ids = [file_ids]
        
        language = body.get('language', 'zh')
        hotword = body.get('hotword', '')
        # 新增：是否等待完成以及超时时间（秒）
        wait_until_complete = body.get('wait', True)
        timeout_seconds = int(body.get('timeout', 3600))  # 默认最多等待1小时
    except:
        return {'success': False, 'message': '请求参数错误'}
    
    if not file_ids:
        return {'success': False, 'message': '请选择要转写的文件（file_id 或 file_ids）'}
    
    # 确保 file_ids 是列表，且每个元素都是字符串
    if not isinstance(file_ids, list):
        logger.error(f"file_ids 不是列表类型: {type(file_ids)}, 值: {file_ids}")
        return {'success': False, 'message': f'file_ids 格式错误，期望数组，实际类型: {type(file_ids).__name__}'}
    
    # 规范化 file_ids：确保所有元素都是字符串
    normalized_file_ids = []
    for item in file_ids:
        if isinstance(item, str):
            normalized_file_ids.append(item)
        elif isinstance(item, (list, tuple)):
            # 如果元素本身是列表，展开它
            normalized_file_ids.extend([str(x) for x in item])
        else:
            normalized_file_ids.append(str(item))
    
    file_ids = normalized_file_ids
    logger.info(f"解析后的 file_ids: {file_ids}, 类型: {type(file_ids)}, 长度: {len(file_ids)}")
    
    # 检查所有文件是否存在且可处理
    files_to_process = []
    for file_id in file_ids:
        if not isinstance(file_id, str):
            logger.error(f"file_id 不是字符串: {type(file_id)}, 值: {file_id}")
            return {'success': False, 'message': f'文件ID格式错误: {file_id}'}
        
        file_info = next((f for f in uploaded_files_manager.get_all_files() if f['id'] == file_id), None)
        if file_info:
            if file_info['status'] == 'processing':
                return {'success': False, 'message': f'文件 {file_info["original_name"]} 正在处理中'}
            files_to_process.append(file_info)
        else:
            logger.warning(f"文件ID不存在: {file_id}, 所有可用文件ID: {[f['id'] for f in uploaded_files_manager.get_all_files()]}")
            return {'success': False, 'message': f'文件ID {file_id} 不存在'}
    
    if not files_to_process:
        return {'success': False, 'message': '没有可处理的文件'}
    
    # 🔧 提前更新所有文件状态为 processing，这样前端立即可以看到状态变化
    for file_info in files_to_process:
        file_info['status'] = 'processing'
        file_info['progress'] = 0
        file_info['language'] = language
        uploaded_files_manager.add_to_processing(file_info['id'])
        logger.info(f"文件 {file_info['original_name']} 状态已更新为 processing")
        
        # 🔔 WebSocket推送：开始转写
        send_ws_message_sync(
            file_info['id'], 
            'processing', 
            0, 
            f"开始转写: {file_info['original_name']}"
        )
    
    # 定义单文件处理函数
    def process_single_file(file_info):
        try:
            file_id = file_info['id']
            logger.info(f"[线程池] 开始处理文件: {file_info['original_name']}, 线程: {threading.current_thread().name}")
            
            # 检查是否已被取消
            if file_info.get('_cancelled', False):
                logger.info(f"[线程池] 文件 {file_id} 已被取消，跳过处理")
                file_info['status'] = 'uploaded'
                file_info['progress'] = 0
                return
            
            # 创建进度回调
            def update_file_progress(step, progress, message="", transcript_entry=None):
                # 检查是否已被取消
                if file_info.get('_cancelled', False):
                    logger.info(f"[线程池] 检测到文件 {file_id} 已被取消，停止处理")
                    raise InterruptedError("转写任务已被取消")
                
                file_info['progress'] = progress
                # 🔔 WebSocket推送：进度更新
                send_ws_message_sync(
                    file_id,
                    'processing',
                    progress,
                    message or f"处理中: {step}"
                )
            
            # ✅ 不再需要全局锁 - 模型池已经处理并发
            # ✅ 修复：直接传递 callback，避免多任务共享状态冲突
            
            # 再次检查是否已被取消
            if file_info.get('_cancelled', False):
                logger.info(f"[线程池] 文件 {file_id} 在开始转写前已被取消")
                file_info['status'] = 'uploaded'
                file_info['progress'] = 0
                return
            
            logger.info(f"[线程池] 开始转写: {file_info['original_name']}")
            transcript, _, _ = pipeline_service.execute_transcription(
                file_info['filepath'],
                hotword=hotword,
                language=language,
                instance_id=file_id,
                cancellation_flag=lambda: file_info.get('_cancelled', False),  # 传递取消检查函数
                callback=update_file_progress  # 直接传递 callback，每个任务有独立的 tracker
            )
            
            # 检查是否在转写过程中被取消
            if file_info.get('_cancelled', False):
                logger.info(f"[线程池] 文件 {file_id} 在转写过程中被取消")
                file_info['status'] = 'uploaded'
                file_info['progress'] = 0
                file_info['error_message'] = '转写已停止'
                send_ws_message_sync(
                    file_id,
                    'uploaded',
                    0,
                    '转写已停止'
                )
                
                # --- 发送停止转写成功事件到 Dify（转写过程中被取消）---
                if DIFY_ALARM_ENABLED:
                    log_stop_transcription_event(
                        file_id=file_id,
                        filename=file_info.get('original_name', 'unknown'),
                        level="SUCCESS",
                        progress=file_info.get('progress', 0)
                    )
                
                return
            
            logger.info(f"[线程池] 转写完成: {file_info['original_name']}")
            
            # 保存转写结果
            if transcript:
                file_info['transcript_data'] = transcript
                logger.info(f"[线程池] 已保存 {len(transcript)} 条转写记录")
                
                # 自动生成Word文档
                # ✅ 修复：传入 file_id 确保每个文件生成唯一的转写文档文件名
                filename, filepath = save_transcript_to_word(
                    transcript,
                    language=language,
                    audio_filename=file_info['original_name'],
                    file_id=file_id
                )
                if filename:
                    file_info['transcript_file'] = filepath
                    logger.info(f"[线程池] 转写文档已保存: {filename}")
                
                # 更新状态为完成
                file_info['status'] = 'completed'
                file_info['progress'] = 100
                file_info['complete_time'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                
                # 添加到已完成列表
                if file_info['id'] not in uploaded_files_manager.get_completed_files():
                    uploaded_files_manager.add_to_completed(file_info['id'])
                
                # 保存历史记录
                save_history_to_file()
                
                # 🔔 WebSocket推送：转写完成
                send_ws_message_sync(
                    file_info['id'],
                    'completed',
                    100,
                    f"转写完成: {file_info['original_name']}"
                )
                
                logger.info(f"[线程池] 文件处理完成: {file_info['original_name']}")
                
                # --- 发送 SUCCESS 报警到 Dify ---
                logger.info(f"[Dify检查] DIFY_ALARM_ENABLED={DIFY_ALARM_ENABLED}, file_id={file_id}")
                if DIFY_ALARM_ENABLED:
                    # 准备完整的转写数据（JSON格式），供 Dify 代码模块处理
                    import json
                    transcript_data = []
                    for entry in transcript:
                        # 只保留必要的字段，去除 words 等详细信息以减小数据量
                        transcript_data.append({
                            'speaker': entry.get('speaker', ''),
                            'text': entry.get('text', ''),
                            'start_time': entry.get('start_time', 0),
                            'end_time': entry.get('end_time', 0)
                        })
                    
                    # 构建包含完整转写数据的 detail（JSON格式）
                    detail_data = {
                        'file_id': file_id,
                        'filename': file_info['original_name'],
                        'transcript': transcript_data,
                        'total_chars': sum(len(entry.get('text', '')) for entry in transcript) if transcript else 0,
                        'segment_count': len(transcript) if transcript else 0
                    }
                    success_detail = json.dumps(detail_data, ensure_ascii=False)
                    
                    logger.info(f"[Dify] 准备发送 SUCCESS 报警: task_id={file_id}, module=VoiceGateway")
                    # 获取文件大小（如果存在）
                    file_size = file_info.get('size', 0)
                    
                    log_success_alarm(
                        task_id=file_id,
                        module="VoiceGateway",
                        message=f"转写任务成功完成: {file_info['original_name']}",
                        detail=success_detail,
                        file_size=file_size
                    )
                else:
                    logger.warning(f"[Dify] 报警功能已禁用，跳过 SUCCESS 报警")
            else:
                file_info['status'] = 'error'
                file_info['error_message'] = '转写失败'
                
                # 🔔 WebSocket推送：转写失败
                send_ws_message_sync(
                    file_info['id'],
                    'error',
                    0,
                    '转写失败'
                )
                
                # --- 发送 ERROR 报警到 Dify ---
                if DIFY_ALARM_ENABLED:
                    log_error_alarm(
                        task_id=file_id,
                        module="VoiceGateway",
                        message=f"转写失败: {file_info['original_name']} - 转写结果为空",
                        exception=None
                    )
                
        except InterruptedError as e:
            # 处理中断异常
            file_id = file_info['id']
            logger.info(f"[线程池] 文件 {file_id} 转写被中断: {e}")
            file_info['status'] = 'uploaded'
            file_info['progress'] = 0
            file_info['error_message'] = '转写已停止'
            
            # 🔔 WebSocket推送：转写已停止
            send_ws_message_sync(
                file_id,
                'uploaded',
                0,
                '转写已停止'
            )
        except Exception as e:
            file_id = file_info['id']
            logger.error(f"[线程池] 处理文件失败 {file_info['original_name']}: {e}")
            
            # 如果是因为取消导致的异常，不标记为错误
            if file_info.get('_cancelled', False):
                file_info['status'] = 'uploaded'
                file_info['progress'] = 0
                file_info['error_message'] = '转写已停止'
                send_ws_message_sync(
                    file_id,
                    'uploaded',
                    0,
                    '转写已停止'
                )
            else:
                file_info['status'] = 'error'
                file_info['error_message'] = str(e)
                
                # 🔔 WebSocket推送：异常错误
                send_ws_message_sync(
                    file_id,
                    'error',
                    0,
                    f"处理失败: {str(e)}"
                )
                
                # --- 发送 ERROR 报警到 Dify ---
                if DIFY_ALARM_ENABLED:
                    log_error_alarm(
                        task_id=file_id,
                        module="VoiceGateway",
                        message=f"处理文件失败: {file_info['original_name']}",
                        exception=e
                    )
            
            import traceback
            traceback.print_exc()
        finally:
            file_id = file_info['id']
            # 从处理列表中移除
            if file_id in uploaded_files_manager.get_processing_files():
                uploaded_files_manager.remove_from_processing(file_id)
            
            # 从任务字典中移除
            with transcription_tasks_lock:
                if file_id in transcription_tasks:
                    del transcription_tasks[file_id]
    
    # 使用线程池并发处理所有文件，并保留 future 以便可选等待
    futures = []
    for file_info in files_to_process:
        file_id = file_info['id']
        # 初始化取消标志
        file_info['_cancelled'] = False
        
        future = TRANSCRIPTION_THREAD_POOL.submit(process_single_file, file_info)
        futures.append((future, file_info))
        
        # 将Future存储到任务字典中，用于取消任务
        with transcription_tasks_lock:
            transcription_tasks[file_id] = future
    
    logger.info(f"已提交 {len(files_to_process)} 个文件到线程池处理")
    
    # 如果需要阻塞等待至完成，则轮询等待直到完成或超时
    if wait_until_complete:
        import time as _time
        deadline = _time.time() + timeout_seconds
        pending_ids = set(fi['id'] for _, fi in futures)
        failed_ids = set()
        completed_ids = set()
        
        # 轮询状态直到全部完成或超时
        while _time.time() < deadline and pending_ids:
            finished_now = []
            for _, fi in futures:
                fid = fi['id']
                if fid not in pending_ids:
                    continue
                status = fi.get('status')
                if status in ('completed', 'error'):
                    finished_now.append(fid)
                    if status == 'completed':
                        completed_ids.add(fid)
                    else:
                        failed_ids.add(fid)
            for fid in finished_now:
                pending_ids.discard(fid)
            if pending_ids:
                _time.sleep(0.5)
        
        if pending_ids:
            # 有未完成任务（超时）
            # ✅ 方案1增强：返回状态信息
            result = {
                'success': False,
                'status': 'timeout',  # 新增：状态字段
                'message': '部分任务未在超时时间内完成',
                'completed_file_ids': sorted(list(completed_ids)),
                'failed_file_ids': sorted(list(failed_ids)),
                'pending_file_ids': sorted(list(pending_ids))
            }
            
            # 收集已完成和失败文件的结果
            all_finished_ids = completed_ids | failed_ids
            if all_finished_ids:
                results = []
                for fid in all_finished_ids:
                    file_info = next((f for f in files_to_process if f['id'] == fid), None)
                    if file_info:
                        file_result = {
                            'file_id': fid,
                            'filename': file_info.get('original_name', ''),
                            'status': file_info.get('status', 'completed'),
                            'progress': file_info.get('progress', 100)
                        }
                        
                        # 如果转写完成，包含 transcript（清理 words 字段）
                        if file_info.get('transcript_data'):
                            file_result['transcript'] = clean_transcript_words(file_info.get('transcript_data', []))
                        
                        # 如果转写失败，包含错误信息
                        if file_info.get('status') == 'error':
                            file_result['error_message'] = file_info.get('error_message', '转写失败')
                        
                        results.append(file_result)
                
                if results:
                    result['results'] = results
                    # 单个文件时，直接返回 transcript
                    if len(results) == 1:
                        result['file_id'] = results[0]['file_id']
                        result['filename'] = results[0]['filename']
                        result['status'] = results[0]['status']
                        result['progress'] = results[0]['progress']
                        if 'transcript' in results[0]:
                            result['transcript'] = results[0]['transcript']
                        if 'error_message' in results[0]:
                            result['error_message'] = results[0]['error_message']
            
            return result
        else:
            # 全部完成
            # ✅ 方案1增强：返回状态和转写结果
            result = {
                'success': True,
                'status': 'completed',  # 新增：状态字段
                'message': f'转写完成 {len(completed_ids)} 个文件',
                'file_ids': sorted(list(completed_ids))
            }
            
            # 收集所有文件的转写结果（包括完成和失败的）
            results = []
            all_finished_ids = completed_ids | failed_ids  # 合并完成和失败的ID
            
            for fid in all_finished_ids:
                file_info = next((f for f in files_to_process if f['id'] == fid), None)
                if file_info:
                    file_result = {
                        'file_id': fid,
                        'filename': file_info.get('original_name', ''),
                        'status': file_info.get('status', 'completed'),
                        'progress': file_info.get('progress', 100),
                        'upload_time': file_info.get('upload_time', ''),
                        'complete_time': file_info.get('complete_time', '')
                    }
                    
                    # 如果转写完成，包含 transcript（清理 words 字段）
                    if file_info.get('transcript_data'):
                        file_result['transcript'] = clean_transcript_words(file_info.get('transcript_data', []))
                    
                    # 如果转写失败，包含错误信息
                    if file_info.get('status') == 'error':
                        file_result['error_message'] = file_info.get('error_message', '转写失败')
                        result['success'] = False  # 如果有失败的文件，整体标记为失败
                    
                    results.append(file_result)
            
            result['results'] = results
            
            # ✅ 单个文件时，直接返回 transcript 和 file_id，方便 Dify 使用
            if len(results) == 1:
                result['file_id'] = results[0]['file_id']
                result['filename'] = results[0]['filename']
                result['progress'] = results[0]['progress']
                result['status'] = results[0]['status']  # 使用文件的实际状态
                if 'transcript' in results[0]:
                    result['transcript'] = results[0]['transcript']
                if 'error_message' in results[0]:
                    result['error_message'] = results[0]['error_message']
                    result['success'] = False
            
            return result
    
    # 非阻塞兼容模式：立即返回"已开始转写"
    # ✅ 方案1增强：返回状态字段
    result = {
        'success': True,
        'status': 'processing',  # 新增：状态字段，表示正在处理中
        'message': f'已开始转写 {len(files_to_process)} 个文件',
        'file_ids': [f['id'] for f in files_to_process],
        'count': len(files_to_process),
        'progress': 0  # 新增：初始进度
    }
    
    # 单个文件时，添加 file_id 字段方便使用
    if len(files_to_process) == 1:
        result['file_id'] = files_to_process[0]['id']
        result['filename'] = files_to_process[0].get('original_name', '')
    
    return result


@router.post("/stop/{file_id}")
async def stop_transcription(file_id: str):
    """
    ⏹️ 停止转写（向后兼容接口）
    
    实现真正的任务中断：取消Future并设置中断标志
    """
    file_info = next((f for f in uploaded_files_manager.get_all_files() if f['id'] == file_id), None)
    
    if not file_info:
        return {'success': False, 'message': '文件不存在'}
    
    if file_info['status'] != 'processing':
        return {'success': False, 'message': '文件未在转写中'}
    
    # 设置中断标志
    file_info['_cancelled'] = True
    logger.info(f"🛑 设置文件 {file_id} 的中断标志")
    
    # 尝试取消Future任务
    with transcription_tasks_lock:
        if file_id in transcription_tasks:
            future = transcription_tasks[file_id]
            cancelled = future.cancel()
            if cancelled:
                logger.info(f"✅ 成功取消文件 {file_id} 的Future任务")
            else:
                logger.warning(f"⚠️ 文件 {file_id} 的Future任务无法取消（可能已开始执行）")
            # 从任务字典中移除
            del transcription_tasks[file_id]
    
    # 更新文件状态
    file_info['status'] = 'uploaded'
    file_info['progress'] = 0
    file_info['error_message'] = '转写已停止'
    
    if file_id in uploaded_files_manager.get_processing_files():
        uploaded_files_manager.remove_from_processing(file_id)
    
    # 🔔 WebSocket推送：转写已停止
    send_ws_message_sync(
        file_id,
        'uploaded',
        0,
        '转写已停止'
    )
    
    # --- 发送停止转写成功事件到 Dify ---
    if DIFY_ALARM_ENABLED:
        log_stop_transcription_event(
            file_id=file_id,
            filename=file_info.get('original_name', 'unknown'),
            level="SUCCESS",
            progress=file_info.get('progress', 0)
        )
    
    logger.info(f"🛑 已停止文件 {file_id} 的转写任务")
    return {'success': True, 'message': '已停止转写'}


@router.get("/status/{file_id}")
async def get_status(file_id: str):
    """
    📊 获取转写状态（向后兼容接口）
    
    推荐使用新接口: GET /api/voice/files/{file_id}
    """
    for f in uploaded_files_manager.get_all_files():
        if f['id'] == file_id:
            return {
                'success': True,
                'status': f['status'],
                'progress': f['progress'],
                'error_message': f.get('error_message', '')
            }
    
    return {'success': False, 'message': '文件不存在'}


@router.get("/result/{file_id}")
async def get_result(file_id: str):
    """
    📄 获取转写结果（向后兼容接口）
    
    推荐使用新接口: GET /api/voice/files/{file_id}?include_transcript=true&include_summary=true
    """
    for f in uploaded_files_manager.get_all_files():
        if f['id'] == file_id:
            if f['status'] != 'completed':
                return {'success': False, 'message': '文件转写未完成'}
            
            return {
                'success': True,
                'file_info': {
                    'id': f['id'],
                    'original_name': f['original_name'],
                    'upload_time': f['upload_time']
                },
                'transcript': f.get('transcript_data', []),
                'summary': f.get('meeting_summary')
            }
    
    return {'success': False, 'message': '文件不存在'}


@router.get("/history")
async def list_history():
    """
    📜 获取历史记录（向后兼容接口）
    
    推荐使用新接口: GET /api/voice/files?status=completed&include_history=true
    """
    # 从文件加载历史记录
    load_history_from_file()
    
    history_records = []
    for f in uploaded_files_manager.get_all_files():
        if f['status'] == 'completed':
            transcript_data = f.get('transcript_data', [])
            speakers = set(t.get('speaker', '') for t in transcript_data if t.get('speaker'))
            
            details = f"{len(speakers)}位发言人, {len(transcript_data)}段对话"
            
            history_records.append({
                'file_id': f['id'],
                'filename': f['original_name'],
                'transcribe_time': f.get('complete_time', f.get('upload_time', '-')),
                'status': 'completed',
                'details': details
            })
    
    history_records.sort(key=lambda x: x['transcribe_time'], reverse=True)
    
    logger.info(f"返回 {len(history_records)} 条历史记录")
    
    return {
        'success': True,
        'records': history_records,
        'total': len(history_records)
    }


@router.delete("/files/{file_id}")
async def delete_file(file_id: str):
    """
    🗑️ 删除文件（RESTful标准接口）
    
    删除音频文件、转写结果和相关文档
    
    特殊操作：
    - file_id = "_clear_all": 清空所有历史记录，包括所有转写文件以及所有音频
    """
    # 特殊操作：清空所有历史记录
    if file_id == "_clear_all":
        try:
            deleted_count = 0
            deleted_audio_count = 0
            deleted_transcript_count = 0
            deleted_summary_count = 0
            
            # 获取所有文件
            all_files = uploaded_files_manager.get_all_files()
            
            for file_info in all_files:
                # 跳过正在处理中的文件
                if file_info['status'] == 'processing':
                    continue
                
                try:
                    # 删除音频文件
                    if 'filepath' in file_info and os.path.exists(file_info['filepath']):
                        os.remove(file_info['filepath'])
                        deleted_audio_count += 1
                        logger.info(f"已删除音频文件: {file_info['filepath']}")
                    
                    # 删除转写文档
                    if 'transcript_file' in file_info and os.path.exists(file_info['transcript_file']):
                        os.remove(file_info['transcript_file'])
                        deleted_transcript_count += 1
                        logger.info(f"已删除转写文档: {file_info['transcript_file']}")
                    
                    # 删除会议纪要文档
                    if 'summary_file' in file_info and os.path.exists(file_info['summary_file']):
                        os.remove(file_info['summary_file'])
                        deleted_summary_count += 1
                        logger.info(f"已删除会议纪要文档: {file_info['summary_file']}")
                    
                    # 从内存中删除
                    uploaded_files_manager.remove_file(file_info['id'])
                    deleted_count += 1
                except Exception as e:
                    logger.error(f"删除文件失败 {file_info.get('original_name', 'unknown')}: {e}")
            
            # 清空output_dir目录下的所有文件（包括.zip和.docx，但不包括会议纪要）
            output_dir = FILE_CONFIG['output_dir']
            if os.path.exists(output_dir):
                for filename in os.listdir(output_dir):
                    # 跳过history_records.json文件
                    if filename == 'history_records.json':
                        continue
                    file_path = os.path.join(output_dir, filename)
                    try:
                        if os.path.isfile(file_path):
                            os.remove(file_path)
                            logger.info(f"已删除输出文件: {filename}")
                    except Exception as e:
                        logger.error(f"删除输出文件失败 {filename}: {e}")
            
            # 清空会议纪要目录下的所有文件
            summary_dir = FILE_CONFIG.get('summary_dir', 'meeting_summaries')
            if os.path.exists(summary_dir):
                for filename in os.listdir(summary_dir):
                    file_path = os.path.join(summary_dir, filename)
                    try:
                        if os.path.isfile(file_path) and filename.endswith('.docx'):
                            os.remove(file_path)
                            deleted_summary_count += 1
                            logger.info(f"已删除会议纪要文档: {filename}")
                    except Exception as e:
                        logger.error(f"删除会议纪要文档失败 {filename}: {e}")
            
            # 清空历史记录文件（保留文件但清空内容）
            try:
                with open(HISTORY_FILE, 'w', encoding='utf-8') as f:
                    json.dump({'files': [], 'completed_files': []}, f, ensure_ascii=False, indent=2)
                logger.info("已清空历史记录文件")
            except Exception as e:
                logger.error(f"清空历史记录文件失败: {e}")
            
            logger.info(f"清空所有历史记录完成: 删除 {deleted_audio_count} 个音频文件, {deleted_transcript_count} 个转写文档, {deleted_summary_count} 个会议纪要文档, {deleted_count} 条历史记录")
            
            # --- 发送清空历史记录成功事件到 Dify ---
            if DIFY_ALARM_ENABLED:
                log_clear_history_event(
                    level="SUCCESS",
                    deleted_records=deleted_count,
                    deleted_audio_files=deleted_audio_count,
                    deleted_transcript_files=deleted_transcript_count
                )
            
            return {
                'success': True, 
                'message': f'清空所有历史记录成功',
                'deleted': {
                    'audio_files': deleted_audio_count,
                    'transcript_files': deleted_transcript_count,
                    'summary_files': deleted_summary_count,
                    'records': deleted_count
                }
            }
        except Exception as e:
            logger.error(f"清空所有历史记录失败: {e}")
            
            # --- 发送清空历史记录失败事件到 Dify ---
            if DIFY_ALARM_ENABLED:
                log_clear_history_event(
                    level="ERROR",
                    deleted_records=0,
                    deleted_audio_files=0,
                    deleted_transcript_files=0,
                    error=e
                )
            
            raise HTTPException(status_code=500, detail=f'清空所有历史记录失败: {str(e)}')
    
    # 正常删除单个文件
    file_info = uploaded_files_manager.get_file(file_id)
    
    if not file_info:
        raise HTTPException(status_code=404, detail='文件不存在')
    
    # ✅ 修复：如果文件正在处理中，但已设置取消标志（停止转写），允许删除
    if file_info['status'] == 'processing' and not file_info.get('_cancelled', False):
        raise HTTPException(status_code=400, detail='文件正在处理中，无法删除')
    
    try:
        # 删除音频文件
        if os.path.exists(file_info['filepath']):
            os.remove(file_info['filepath'])
            logger.info(f"已删除音频文件: {file_info['filepath']}")
        
        # 删除转写文档（如果存在）
        if 'transcript_file' in file_info and os.path.exists(file_info['transcript_file']):
            os.remove(file_info['transcript_file'])
            logger.info(f"已删除转写文档: {file_info['transcript_file']}")
        
        # 删除会议纪要文档（如果存在）
        if 'summary_file' in file_info and os.path.exists(file_info['summary_file']):
            os.remove(file_info['summary_file'])
            logger.info(f"已删除会议纪要文档: {file_info['summary_file']}")
        
        # 从内存中删除（使用线程安全方法）
        uploaded_files_manager.remove_file(file_id)
        
        # 保存更新后的历史记录到磁盘
        save_history_to_file()
        
        # --- 发送删除成功事件到 Dify ---
        if DIFY_ALARM_ENABLED:
            # 检查文件是否是被停止的转写
            was_stopped = (
                file_info.get('_cancelled', False) or 
                file_info.get('error_message') == '转写已停止'
            )
            log_delete_event(
                file_id=file_id,
                filename=file_info.get('original_name', 'unknown'),
                level="SUCCESS",
                was_stopped=was_stopped
            )
        
        # 🔔 WebSocket推送：文件已删除
        send_ws_message_sync(
            file_id,
            'deleted',
            0,
            f"文件已删除: {file_info['original_name']}"
        )
        
        logger.info(f"文件删除成功: {file_info['original_name']}, ID: {file_id}")
        
        return {'success': True, 'message': '文件删除成功'}
        
    except Exception as e:
        logger.error(f"删除文件失败: {e}")
        
        # --- 发送删除失败事件到 Dify ---
        if DIFY_ALARM_ENABLED:
            filename = file_info.get('original_name', 'unknown') if file_info else 'unknown'
            # 检查文件是否是被停止的转写
            was_stopped = False
            if file_info:
                was_stopped = (
                    file_info.get('_cancelled', False) or 
                    file_info.get('error_message') == '转写已停止'
                )
            log_delete_event(
                file_id=file_id,
                filename=filename,
                level="ERROR",
                error=e,
                was_stopped=was_stopped
            )
        
        raise HTTPException(status_code=500, detail=f'删除文件失败: {str(e)}')


@router.get("/audio/{file_id}")
async def get_audio(file_id: str, download: int = 0):
    """获取音频文件"""
    file_info = next((f for f in uploaded_files_manager.get_all_files() if f['id'] == file_id), None)
    
    if not file_info:
        raise HTTPException(status_code=404, detail="文件不存在")
    
    if not os.path.exists(file_info['filepath']):
        raise HTTPException(status_code=404, detail="音频文件不存在")
    
    if download == 1:
        return FileResponse(
            file_info['filepath'],
            media_type='application/octet-stream',
            filename=file_info['original_name']
        )
    else:
        return FileResponse(
            file_info['filepath'],
            media_type='audio/mpeg'
        )


@router.get("/download_transcript/{file_id}")
async def download_transcript(file_id: str):
    """下载转写结果"""
    file_info = next((f for f in uploaded_files_manager.get_all_files() if f['id'] == file_id), None)
    
    if not file_info:
        if DIFY_ALARM_ENABLED:
            log_download_event(
                file_id=file_id,
                filename="unknown",
                level="ERROR"
            )
        raise HTTPException(status_code=404, detail='文件不存在')
    
    if file_info['status'] != 'completed':
        if DIFY_ALARM_ENABLED:
            log_download_event(
                file_id=file_id,
                filename=file_info.get('original_name', 'unknown'),
                level="ERROR"
            )
        raise HTTPException(status_code=400, detail='文件转写未完成')
    
    try:
        if 'transcript_file' in file_info and file_info['transcript_file']:
            filepath = file_info['transcript_file']
            if os.path.exists(filepath):
                # --- 发送下载成功事件到 Dify ---
                if DIFY_ALARM_ENABLED:
                    log_download_event(
                        file_id=file_id,
                        filename=file_info.get('original_name', os.path.basename(filepath)),
                        level="SUCCESS"
                    )
                return FileResponse(
                    path=filepath,
                    filename=os.path.basename(filepath),
                    media_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document'
                )
        
        transcript_data = file_info.get('transcript_data', [])
        if not transcript_data:
            if DIFY_ALARM_ENABLED:
                log_download_event(
                    file_id=file_id,
                    filename=file_info.get('original_name', 'unknown'),
                    level="ERROR"
                )
            raise HTTPException(status_code=400, detail='没有转写结果')
        
        # ✅ 修复：传入 file_id 确保每个文件生成唯一的转写文档文件名
        filename, filepath = save_transcript_to_word(
            transcript_data,
            language=file_info.get('language', 'zh'),
            audio_filename=file_info.get('original_name'),
            file_id=file_id
        )
        
        if filename and os.path.exists(filepath):
            file_info['transcript_file'] = filepath
            # --- 发送下载成功事件到 Dify ---
            if DIFY_ALARM_ENABLED:
                log_download_event(
                    file_id=file_id,
                    filename=file_info.get('original_name', filename),
                    level="SUCCESS"
                )
            return FileResponse(
                path=filepath,
                filename=filename,
                media_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document'
            )
        else:
            if DIFY_ALARM_ENABLED:
                log_download_event(
                    file_id=file_id,
                    filename=file_info.get('original_name', 'unknown'),
                    level="ERROR"
                )
            raise HTTPException(status_code=500, detail='生成Word文档失败')
    except HTTPException:
        raise
    except Exception as e:
        # --- 发送下载失败事件到 Dify ---
        if DIFY_ALARM_ENABLED:
            log_download_event(
                file_id=file_id,
                filename=file_info.get('original_name', 'unknown') if file_info else 'unknown',
                level="ERROR",
                error=e
            )
        raise HTTPException(status_code=500, detail=f'下载失败: {str(e)}')


@router.post("/generate_summary/{file_id}")
async def generate_summary_legacy(file_id: str, request: Request = None):
    """
    📝 生成会议纪要（向后兼容接口）
    
    支持自定义提示词和模型选择：
    - prompt: 自定义提示词模板（可选，使用 {transcript} 作为占位符）
    - model: 模型名称（可选，默认使用配置的模型）
    
    推荐使用新接口: PATCH /api/voice/files/{file_id} with action=generate_summary
    """
    file_info = next((f for f in uploaded_files_manager.get_all_files() if f['id'] == file_id), None)
    
    if not file_info:
        raise HTTPException(status_code=404, detail='文件不存在')
    
    if file_info['status'] != 'completed':
        raise HTTPException(status_code=400, detail='文件转写未完成')
    
    transcript_data = file_info.get('transcript_data', [])
    if not transcript_data:
        raise HTTPException(status_code=400, detail='没有转写结果')
    
    # 获取请求参数（自定义提示词和模型）
    custom_prompt = None
    model = None
    
    if request:
        try:
            body = await request.json()
            custom_prompt = body.get('prompt')
            model = body.get('model')
        except:
            # 如果不是JSON请求，使用默认值
            pass
    
    try:
        # 使用线程池异步执行生成会议纪要（避免阻塞事件循环）
        loop = asyncio.get_event_loop()
        summary = await loop.run_in_executor(
            TRANSCRIPTION_THREAD_POOL,
            generate_meeting_summary,
            transcript_data,
            custom_prompt,
            model
        )
        
        if summary:
            file_info['meeting_summary'] = summary
            
            # 计算音频时长
            audio_duration = None
            if transcript_data:
                last_entry = transcript_data[-1] if transcript_data else None
                if last_entry and 'end_time' in last_entry:
                    audio_duration = last_entry['end_time']
            
            # 使用线程池异步执行Word文档生成（避免阻塞事件循环）
            filename, filepath = await loop.run_in_executor(
                TRANSCRIPTION_THREAD_POOL,
                save_meeting_summary_to_word,
                transcript_data, 
                summary, 
                "meeting_summary",  # filename_prefix
                file_id,
                file_info.get('original_name'),
                audio_duration
            )
            
            if filename and filepath:
                file_info['summary_file'] = filepath
                # 保存历史记录也在线程池中执行
                await loop.run_in_executor(
                    TRANSCRIPTION_THREAD_POOL,
                    save_history_to_file
                )
                return {
                    'success': True, 
                    'message': '会议纪要生成成功',
                    'summary': summary
                }
            else:
                # 即使保存文件失败，也保存摘要数据
                await loop.run_in_executor(
                    TRANSCRIPTION_THREAD_POOL,
                    save_history_to_file
                )
                return {
                    'success': True, 
                    'message': '会议纪要生成成功，但保存文件失败',
                    'summary': summary
                }
        else:
            raise HTTPException(status_code=500, detail='生成会议纪要失败')
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"生成会议纪要失败: {e}")
        raise HTTPException(status_code=500, detail=f'生成会议纪要失败: {str(e)}')


@router.get("/download_summary/{file_id}")
async def download_summary(file_id: str):
    """下载会议纪要"""
    file_info = next((f for f in uploaded_files_manager.get_all_files() if f['id'] == file_id), None)
    
    if not file_info:
        raise HTTPException(status_code=404, detail='文件不存在')
    
    if file_info['status'] != 'completed':
        raise HTTPException(status_code=400, detail='文件转写未完成')
    
    if not file_info.get('meeting_summary'):
        raise HTTPException(status_code=400, detail='请先生成会议纪要')
    
    try:
        # 如果已有保存的文件，直接返回
        if 'summary_file' in file_info and file_info['summary_file']:
            filepath = file_info['summary_file']
            if os.path.exists(filepath):
                return FileResponse(
                    path=filepath,
                    filename=os.path.basename(filepath),
                    media_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document'
                )
        
        # 否则重新生成文件
        transcript_data = file_info.get('transcript_data', [])
        summary = file_info['meeting_summary']
        
        # 计算音频时长
        audio_duration = None
        if transcript_data:
            last_entry = transcript_data[-1] if transcript_data else None
            if last_entry and 'end_time' in last_entry:
                audio_duration = last_entry['end_time']
        
        # 使用线程池异步执行Word文档生成（避免阻塞事件循环）
        loop = asyncio.get_event_loop()
        filename, filepath = await loop.run_in_executor(
            TRANSCRIPTION_THREAD_POOL,
            save_meeting_summary_to_word,
            transcript_data, 
            summary, 
            "meeting_summary",  # filename_prefix
            file_id,
            file_info.get('original_name'),
            audio_duration
        )
        
        if filename and os.path.exists(filepath):
            # 保存文件路径到 file_info
            file_info['summary_file'] = filepath
            # 保存历史记录也在线程池中执行
            await loop.run_in_executor(
                TRANSCRIPTION_THREAD_POOL,
                save_history_to_file
            )
            
            return FileResponse(
                path=filepath,
                filename=filename,
                media_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document'
            )
        else:
            raise HTTPException(status_code=500, detail='生成Word文档失败')
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"下载会议纪要失败: {e}")
        raise HTTPException(status_code=500, detail=f'下载失败: {str(e)}')


@router.delete("/summary/{file_id}")
async def delete_summary(file_id: str):
    """删除会议纪要"""
    file_info = next((f for f in uploaded_files_manager.get_all_files() if f['id'] == file_id), None)
    
    if not file_info:
        raise HTTPException(status_code=404, detail='文件不存在')
    
    if not file_info.get('meeting_summary'):
        raise HTTPException(status_code=400, detail='没有会议纪要可删除')
    
    try:
        # 删除会议纪要数据
        if 'meeting_summary' in file_info:
            del file_info['meeting_summary']
        
        # 删除该转写结果对应的所有会议纪要文件
        deleted_files = []
        summary_dir = FILE_CONFIG.get('summary_dir', 'meeting_summaries')
        
        # 生成 file_id 的短标识（与保存文件时使用的格式一致）
        file_id_short = file_id.replace('-', '')[:8]  # 移除连字符，取前8位
        
        # 扫描 summary_dir 目录，查找所有匹配该 file_id 的会议纪要文件
        if os.path.exists(summary_dir):
            for filename in os.listdir(summary_dir):
                # 匹配格式：meeting_summary_*_{file_id_short}.docx
                if filename.startswith('meeting_summary_') and filename.endswith(f'_{file_id_short}.docx'):
                    filepath = os.path.join(summary_dir, filename)
                    try:
                        if os.path.exists(filepath):
                            os.remove(filepath)
                            deleted_files.append(filename)
                            logger.info(f"已删除会议纪要文档: {filepath}")
                    except Exception as e:
                        logger.warning(f"删除会议纪要文档失败 {filepath}: {e}")
        
        # 删除 file_info 中保存的文件路径（如果存在）
        if 'summary_file' in file_info:
            del file_info['summary_file']
        
        # 保存更改
        save_history_to_file()
        
        message = f'会议纪要删除成功'
        if deleted_files:
            message += f'，共删除 {len(deleted_files)} 个文件'
        
        return {
            'success': True,
            'message': message,
            'deleted_files_count': len(deleted_files)
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"删除会议纪要失败: {e}")
        raise HTTPException(status_code=500, detail=f'删除会议纪要失败: {str(e)}')


@router.get("/languages")
async def get_languages():
    """获取支持的语言列表"""
    return {
        'success': True,
        'languages': [
            {'value': key, 'name': value['name'], 'description': value['description']}
            for key, value in LANGUAGE_CONFIG.items()
        ]
    }


@router.get("/transcript_files")
async def list_transcript_files():
    """列出所有转写文件"""
    try:
        files = audio_storage.list_output_files('.docx')
        for f in files:
            stat = os.stat(f['filepath'])
            f['modified'] = datetime.fromtimestamp(stat.st_mtime).strftime('%Y-%m-%d %H:%M:%S')
            f['type'] = 'Word文档'
        
        files.sort(key=lambda x: x['modified'], reverse=True)
        return {'success': True, 'files': files}
    except Exception as e:
        return {'success': False, 'message': str(e)}


@router.get("/download_file/{filename}")
async def download_file(filename: str):
    """
    📥 下载输出文件（Word文档、ZIP压缩包等）
    
    路径参数：
    - filename: 文件名（例如：transcript_20251101_203654.docx）
    
    用途：
    - 下载单独的 Word 转写文档
    - 下载其他输出文件
    
    返回：文件流
    """
    try:
        filepath = os.path.join(FILE_CONFIG['output_dir'], filename)
        if os.path.exists(filepath):
            # 根据文件扩展名确定 MIME 类型
            if filename.endswith('.zip'):
                media_type = 'application/zip'
            elif filename.endswith('.docx'):
                media_type = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
            else:
                media_type = 'application/octet-stream'
            
            return FileResponse(
                filepath,
                media_type=media_type,
                filename=filename
            )
        else:
            raise HTTPException(status_code=404, detail="文件不存在")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/delete_file/{filename}")
async def delete_output_file(filename: str):
    """删除输出文件"""
    try:
        filepath = os.path.join(FILE_CONFIG['output_dir'], filename)
        if os.path.exists(filepath):
            os.remove(filepath)
            return {'success': True, 'message': '文件删除成功'}
        else:
            return {'success': False, 'message': '文件不存在'}
    except Exception as e:
        return {'success': False, 'message': f'删除失败: {str(e)}'}


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """
    WebSocket端点 - 实时推送文件状态更新
    
    客户端可以通过此WebSocket连接接收：
    - 文件上传状态
    - 转写进度更新
    - 转写完成通知
    - 错误提示
    """
    await ws_manager.connect(websocket)
    
    try:
        # 发送连接成功消息
        await websocket.send_json({
            "type": "connected",
            "message": "WebSocket连接已建立"
        })
        
        # 保持连接并处理客户端消息
        while True:
            data = await websocket.receive_text()
            # 可以处理客户端发送的消息（如订阅特定文件）
            try:
                message = json.loads(data)
                if message.get('type') == 'subscribe':
                    file_id = message.get('file_id')
                    if file_id:
                        ws_manager.subscribe_file(websocket, file_id)
                        await websocket.send_json({
                            "type": "subscribed",
                            "file_id": file_id,
                            "message": f"已订阅文件 {file_id} 的状态更新"
                        })
            except json.JSONDecodeError:
                pass
            
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket)
        logger.info("WebSocket客户端断开连接")
    except Exception as e:
        logger.error(f"WebSocket错误: {e}")
        ws_manager.disconnect(websocket)


