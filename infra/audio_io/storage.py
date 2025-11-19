"""
Infra - 音频文件存储
负责音频文件的保存、加载、清理等操作
"""

import os
import shutil
from pathlib import Path
from typing import Optional


class AudioStorage:
    """音频存储管理器"""
    
    def __init__(self, upload_dir: str, temp_dir: str, output_dir: str):
        self.upload_dir = upload_dir
        self.temp_dir = temp_dir
        self.output_dir = output_dir
        
        # 确保目录存在
        os.makedirs(upload_dir, exist_ok=True)
        os.makedirs(temp_dir, exist_ok=True)
        os.makedirs(output_dir, exist_ok=True)
    
    def save_uploaded_file(self, file_content: bytes, filename: str) -> str:
        """保存上传的文件"""
        filepath = os.path.join(self.upload_dir, filename)
        with open(filepath, 'wb') as f:
            f.write(file_content)
        return filepath
    
    def get_temp_path(self, filename: str) -> str:
        """获取临时文件路径"""
        return os.path.join(self.temp_dir, filename)
    
    def get_output_path(self, filename: str) -> str:
        """获取输出文件路径"""
        return os.path.join(self.output_dir, filename)
    
    def cleanup_temp_files(self, instance_id: str = None):
        """清理临时文件"""
        try:
            if instance_id:
                # 只清理特定实例的临时文件
                for file in os.listdir(self.temp_dir):
                    if instance_id in file:
                        try:
                            os.remove(os.path.join(self.temp_dir, file))
                        except Exception as e:
                            print(f"删除文件 {file} 失败: {e}")
            else:
                # 清理所有临时文件
                for file in os.listdir(self.temp_dir):
                    try:
                        os.remove(os.path.join(self.temp_dir, file))
                    except Exception as e:
                        print(f"删除文件 {file} 失败: {e}")
        except Exception as e:
            print(f"清理临时文件失败: {e}")
    
    def file_exists(self, filepath: str) -> bool:
        """检查文件是否存在"""
        return os.path.exists(filepath)
    
    def get_file_size(self, filepath: str) -> int:
        """获取文件大小(字节)"""
        if self.file_exists(filepath):
            return os.path.getsize(filepath)
        return 0
    
    def list_output_files(self, extension: str = None) -> list:
        """列出输出目录中的文件"""
        files = []
        if os.path.exists(self.output_dir):
            for filename in os.listdir(self.output_dir):
                if extension is None or filename.endswith(extension):
                    filepath = os.path.join(self.output_dir, filename)
                    files.append({
                        'filename': filename,
                        'filepath': filepath,
                        'size': os.path.getsize(filepath)
                    })
        return files

