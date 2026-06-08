import os
import re
import time
import traceback
from pathlib import Path
from config.logger import setup_logging
from plugins_func.register import register_function, ToolType, ActionResponse, Action
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.connection import ConnectionHandler

TAG = __name__

logger = setup_logging()

MUSIC_CACHE = {}

'''
工作流程

  用户: "你有什么歌？"
      ↓ LLM 识别意图 → 调用 get_music_songs
      ↓ initialize_music_handler() 扫描 music_dir
      ↓ 格式化为歌曲列表文本
      ↓ ActionResponse(REQLLM, 歌曲列表)
      ↓ LLM 组织回复: "本地曲库共有12首歌：1. 两只老虎 2. 小星星 ..." → TTS 播报
 
 输出示例
  本地音乐曲库中共有3首歌曲：
  1. 两只老虎
  2. 小星星
  3. 童话

  用户想听哪首可以直接点播。

  歌词刷新
  查询时会检查 refresh_time 间隔，超时则自动重新扫描目录，保证新增歌曲能被及时发现
'''
get_music_songs_list_function_desc = {
    "type": "function",
    "function": {
        "name": "get_music_songs_list",
        "description": "查询本地音乐曲库中所有可播放的歌曲名称列表。当用户问'有什么歌'、'有哪些歌'、'你会唱什么'、'歌曲列表'、'音乐列表'等时调用此功能。",
        "parameters": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
}


@register_function("get_music_songs_list", get_music_songs_list_function_desc, ToolType.SYSTEM_CTL)
def get_music_songs_list(conn: "ConnectionHandler"):
    """
    查询本地音乐曲库中所有可播放的歌曲名称列表

    Args:
        conn: 连接处理器，用于获取配置信息
    """
    try:
        music_cache = initialize_music_handler(conn)
    except Exception as e:
        logger.bind(tag=TAG).error(f"初始化音乐处理器失败: {e}")
        return ActionResponse(
            action=Action.RESPONSE,
            result=None,
            response="获取歌曲列表失败，请稍后再试",
        )

    song_names = music_cache.get("music_file_names", [])
    music_dir = music_cache.get("music_dir", "./music")

    if not os.path.exists(music_dir):
        logger.bind(tag=TAG).error(f"音乐目录不存在: {music_dir}")
        return ActionResponse(
            action=Action.RESPONSE, result=None, response="本地音乐库目录不存在"
        )

    if not song_names:
        logger.bind(tag=TAG).info("本地音乐曲库为空")
        return ActionResponse(
            action=Action.RESPONSE,
            result=None,
            response="本地音乐库暂时没有歌曲，请先添加音乐文件",
        )

    # 刷新文件列表（如果超过刷新时间）
    if time.time() - music_cache["scan_time"] > music_cache["refresh_time"]:
        try:
            music_cache["music_files"], music_cache["music_file_names"] = get_music_files(
                music_cache["music_dir"], music_cache["music_ext"]
            )
            music_cache["scan_time"] = time.time()
            song_names = music_cache["music_file_names"]
        except Exception as e:
            logger.bind(tag=TAG).error(f"刷新音乐文件列表失败: {e}")

    logger.bind(tag=TAG).info(f"本地曲库音乐列表查询结果: {song_names}")

    # 构建结构化结果供LLM使用（REQLLM模式下LLM会自然回复，不直接走TTS）
    result_text = "本地音乐曲库中共有{}首歌曲：\n".format(len(song_names))
    song_list = []
    for i, name in enumerate(song_names, 1):
        # 移除路径前缀，只显示纯文件名
        display_name = os.path.basename(name)
        # 去除文件扩展名之外的符号，只保留中文、英文、数字
        display_name = re.sub(r'[^一-龥a-zA-Z0-9]', '', display_name)
        if display_name:
            song_list.append("{}. {}".format(i, display_name))

    if not song_list:
        return ActionResponse(
            action=Action.RESPONSE,
            result=None,
            response="本地音乐库暂时没有可播放的歌曲",
        )

    # 拼接所有歌曲名，用分号分隔以便LLM理解
    result_text += "；".join(song_list)

    return ActionResponse(
        action=Action.REQLLM,
        result=result_text,
        response=None,
    )


def initialize_music_handler(conn: "ConnectionHandler"):
    global MUSIC_CACHE
    if MUSIC_CACHE == {}:
        plugins_config = conn.config.get("plugins", {})
        if "play_music" in plugins_config:
            MUSIC_CACHE["music_config"] = plugins_config["play_music"]
            MUSIC_CACHE["music_dir"] = os.path.abspath(
                MUSIC_CACHE["music_config"].get("music_dir", "./music")
            )
            MUSIC_CACHE["music_ext"] = MUSIC_CACHE["music_config"].get(
                "music_ext", (".mp3", ".wav", ".p3")
            )
            MUSIC_CACHE["refresh_time"] = MUSIC_CACHE["music_config"].get(
                "refresh_time", 60
            )
        else:
            MUSIC_CACHE["music_dir"] = os.path.abspath("./music")
            MUSIC_CACHE["music_ext"] = (".mp3", ".wav", ".p3")
            MUSIC_CACHE["refresh_time"] = 60
        MUSIC_CACHE["music_files"], MUSIC_CACHE["music_file_names"] = get_music_files(
            MUSIC_CACHE["music_dir"], MUSIC_CACHE["music_ext"]
        )
        MUSIC_CACHE["scan_time"] = time.time()
    return MUSIC_CACHE


def get_music_files(music_dir, music_ext):
    music_dir = Path(music_dir)
    music_files = []
    music_file_names = []
    for file in music_dir.rglob("*"):
        if file.is_file():
            ext = file.suffix.lower()
            if ext in music_ext:
                try:
                    relative_path = str(file.relative_to(music_dir))
                    music_files.append(relative_path)
                    # 只保留中文、英文、数字，避免特殊字符导致TTS异常
                    clean_name = re.sub(
                        r'[^一-龥a-zA-Z0-9]',
                        '',
                        os.path.splitext(relative_path)[0],
                    )
                    if clean_name:
                        music_file_names.append(clean_name)
                except Exception as e:
                    logger.bind(tag=TAG).warning(f"跳过无法读取的音乐文件: {file}, 错误: {e}")
                    continue
    return music_files, music_file_names
