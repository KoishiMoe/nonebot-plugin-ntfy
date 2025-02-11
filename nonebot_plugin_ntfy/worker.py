import asyncio
import json
import os
import tempfile
import re
from pathlib import Path
from typing import Any, Dict, List, Union

import aiohttp
# from aiohttp.log import access_logger
from nonebot import get_driver, require
# from nonebot import on_message
from nonebot.adapters.onebot.v11 import (
    # Bot,
    # GroupMessageEvent,
    Message,
    # MessageEvent,
    MessageSegment,
    # PrivateMessageEvent,
)
from nonebot.log import logger

from .config import Config

require("nonebot_plugin_apscheduler")
from nonebot_plugin_apscheduler import scheduler


plugin_config = Config.load()

# Store the mappings of ntfy channels to QQ targets
NTFY_TO_QQ_MAPPING: List[Dict[str, Any]] = plugin_config.ntfy_to_qq_mapping
# QQ_TO_NTFY_MAPPING: List[Dict[str, Any]] = plugin_config.qq_to_ntfy_mapping

# Initialize logger
plugin_logger = logger.bind(name="ntfy_forward")

# An asynchronous session for HTTP requests
session: aiohttp.ClientSession

# Temporary directory for caching media files
MEDIA_CACHE_DIR = tempfile.TemporaryDirectory()

# Start tasks to listen to ntfy channels
async def start_ntfy_listeners():
    global session
    session = aiohttp.ClientSession()
    tasks = []
    for mapping in NTFY_TO_QQ_MAPPING:
        ntfy_channel = mapping["ntfy_channel"]
        qq_targets = mapping["qq_targets"]
        task = asyncio.create_task(ntfy_listener(ntfy_channel, qq_targets))
        tasks.append(task)
    await asyncio.gather(*tasks)

@get_driver().on_startup
async def on_startup():
    asyncio.create_task(start_ntfy_listeners())

@get_driver().on_shutdown
async def on_shutdown():
    await session.close()
    MEDIA_CACHE_DIR.cleanup()

# Function to listen to an ntfy channel and forward messages to QQ targets
async def ntfy_listener(ntfy_channel: str, qq_targets: List[str]):
    ntfy_url = f"{plugin_config.ntfy_server}/{ntfy_channel}/ws"
    headers = {"Authorization": f"Bearer {plugin_config.ntfy_token}"} if plugin_config.ntfy_token else {}
    while True:
        try:
            async with session.ws_connect(ntfy_url, headers=headers) as ws:
                plugin_logger.info(f"Connected to ntfy channel: {ntfy_channel}")
                async for msg in ws:
                    if msg.type == aiohttp.WSMsgType.TEXT:
                        data = json.loads(msg.data)
                        plugin_logger.debug(f"Received message from ntfy: {data}")
                        await forward_ntfy_to_qq(data, qq_targets)
        except Exception as e:
            plugin_logger.error(f"Error in ntfy listener for {ntfy_channel}: {e}")
            await asyncio.sleep(plugin_config.reconnect_interval)

# Function to forward messages from ntfy to QQ
async def forward_ntfy_to_qq(data: Dict[str, Any], qq_targets: List[str]):
    bots = get_driver().bots
    if not bots:
        plugin_logger.error("No bot instances available")
        return
    bot = list(bots.values())[0]
    content = data.get("message", "")
    attachment = data.get("attachment", {})
    segments = Message()
    if content and not re.match(r"^((\s*)|(A(n?) \w+ was shared with you))$", content):
        segments.append(MessageSegment.text(content))
    if attachment:
        url = attachment.get("url")
        mime = attachment.get("type", "")
        if url:
            if mime.startswith("image/") or mime.startswith("video/"):
                url2 = url
                for original_host, substitute_host in plugin_config.attachment_host_mapping.items():
                    if url.startswith(original_host):
                        url2 = url.replace(original_host, substitute_host)
                        break
                file = await download_media(url2)
                if file:
                    if mime.startswith("image/"):
                        segments.append(MessageSegment.image(Path(file)))
                    elif mime.startswith("video/"):
                        segments.append(MessageSegment.video(Path(file)))
                else:
                    segments.append(MessageSegment.text(f"Attachment: {url}"))
            else:
                segments.append(MessageSegment.text(f"Attachment: {url}"))

    for target in qq_targets:
        try:
            if target.startswith("group_"):
                group_id = int(target[len("group_"):])
                await bot.send_group_msg(group_id=group_id, message=segments)
            elif target.startswith("user_"):
                user_id = int(target[len("user_"):])
                await bot.send_private_msg(user_id=user_id, message=segments)
            else:
                plugin_logger.error(f"Invalid qq_target format: {target}")
            await asyncio.sleep(1)
        except Exception as e:
            plugin_logger.error(f"Error sending message to {target}: {e}")
            if plugin_config.report_error:
                for admin in bot.config.superusers:
                    try:
                        await bot.send_private_msg(
                            user_id=int(admin),
                            message=MessageSegment.text(f"Error sending message to {target}: {e}\nMessage: {content} Attachment: {attachment}"),
                        )
                    except Exception as e:
                        plugin_logger.error(f"Error sending error report to {admin}: {e}")
                    await asyncio.sleep(1)
#
# # Listener for QQ messages to forward to ntfy
# @on_message()
# async def qq_message_listener(event: MessageEvent, bot: Bot):
#     if isinstance(event, GroupMessageEvent):
#         source = f"group_{event.group_id}"
#     elif isinstance(event, PrivateMessageEvent):
#         source = f"user_{event.user_id}"
#     else:
#         return
#
#     for mapping in QQ_TO_NTFY_MAPPING:
#         qq_sources = mapping["qq_sources"]
#         ntfy_channel = mapping["ntfy_channel"]
#         if source in qq_sources or "all" in qq_sources:
#             await forward_qq_to_ntfy(event, ntfy_channel)
#             break
#
# # Function to forward messages from QQ to ntfy
# async def forward_qq_to_ntfy(event: Union[GroupMessageEvent, PrivateMessageEvent], ntfy_channel: str):
#     ntfy_url = f"{plugin_config.ntfy_server}/{ntfy_channel}"
#     headers = {}
#     if plugin_config.ntfy_token:
#         headers["Authorization"] = f"Bearer {plugin_config.ntfy_token}"
#     data = {
#         "topic": ntfy_channel,
#         "message": event.get_plaintext(),
#     }
#     files = []
#     for segment in event.message:
#         if segment.type in ["image", "video"]:
#             url = segment.data.get("url")
#             if not url:
#                 continue
#             size = await get_content_length(url)
#             if size > plugin_config.max_attachment_size:
#                 # If size exceeds limit, include URL in message
#                 data["message"] += f"\nAttachment too large ({size} bytes): {url}"
#                 continue
#             file_path = await download_media(url)
#             if file_path:
#                 file_name = os.path.basename(file_path)
#                 file_mime = await get_mime_type(file_path)
#                 files.append(("file", (file_name, open(file_path, "rb"), file_mime)))
#         elif segment.type == "record":
#             # Handle audio files (recordings)
#             url = segment.data.get("url")
#             if not url:
#                 continue
#             size = await get_content_length(url)
#             if size > plugin_config.max_attachment_size:
#                 data["message"] += f"\nAudio too large ({size} bytes): {url}"
#                 continue
#             file_path = await download_media(url)
#             if file_path:
#                 file_name = os.path.basename(file_path)
#                 file_mime = await get_mime_type(file_path)
#                 files.append(("file", (file_name, open(file_path, "rb"), file_mime)))
#         elif segment.type == "face":
#             # Handle emojis and stickers as images
#             face_id = segment.data.get("id")
#             face_url = f"https://qq-web-emoticon-url/{face_id}"  # Replace with actual URL
#             file_path = await download_media(face_url)
#             if file_path:
#                 file_name = f"face_{face_id}.png"
#                 file_mime = "image/png"
#                 files.append(("file", (file_name, open(file_path, "rb"), file_mime)))
#         else:
#             continue
#     try:
#         async with session.post(ntfy_url, data=data, headers=headers, files=files) as resp:
#             if resp.status != 200:
#                 plugin_logger.error(f"Failed to forward message to ntfy: {resp.status}")
#     except Exception as e:
#         plugin_logger.error(f"Error forwarding message to ntfy: {e}")
#     finally:
#         # Clean up temporary files
#         for file_tuple in files:
#             file_obj = file_tuple[1][1]
#             file_obj.close()
#             try:
#                 os.remove(file_obj.name)
#             except Exception as e:
#                 plugin_logger.error(f"Error removing temporary file: {e}")

# Helper function to download media content
async def download_media(url: str) -> Union[str, None]:
    try:
        file_name = os.path.basename(url)
        temp_dir = Path(MEDIA_CACHE_DIR.name)
        file_path = temp_dir / file_name
        async with session.get(url) as resp:
            if resp.status == 200:
                with open(file_path, "wb") as f:
                    while True:
                        chunk = await resp.content.read(1024)
                        if not chunk:
                            break
                        f.write(chunk)
                return str(file_path)
            else:
                plugin_logger.error(f"Failed to download media from {url}: {resp.status}")
                return None
    except Exception as e:
        plugin_logger.error(f"Error downloading media from {url}: {e}")
        return None

# # Helper function to get content length of a URL
# async def get_content_length(url: str) -> int:
#     try:
#         async with session.head(url) as resp:
#             if resp.status == 200:
#                 return int(resp.headers.get('Content-Length', 0))
#             else:
#                 plugin_logger.error(f"Failed to get content length for {url}: {resp.status}")
#                 return 0
#     except Exception as e:
#         plugin_logger.error(f"Error getting content length for {url}: {e}")
#         return 0

# # Helper function to get MIME type of a file
# async def get_mime_type(file_path: str) -> str:
#     import mimetypes
#
#     mime_type, _ = mimetypes.guess_type(file_path)
#     if not mime_type:
#         mime_type = "application/octet-stream"
#     return mime_type

# Scheduler to clean up cache periodically
@scheduler.scheduled_job("interval", minutes=plugin_config.cache_clean_interval)
async def clean_media_cache():
    temp_dir = Path(MEDIA_CACHE_DIR.name)
    for item in temp_dir.iterdir():
        try:
            if item.is_file():
                item.unlink()
        except Exception as e:
            plugin_logger.error(f"Error cleaning media cache: {e}")
    plugin_logger.info("Cleaned media cache")
