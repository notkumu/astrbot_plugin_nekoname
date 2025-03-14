import os
import psutil
import yaml
import logging
import datetime
from astrbot.api.event import filter, AstrMessageEvent, MessageEventResult
from astrbot.api.star import Context, Star, register
from astrbot.api.all import *

logger = logging.getLogger(__name__)

# 插件目录
PLUGIN_DIR = os.path.join('data', 'plugins', 'astrbot_plugin_botName')
# 确保插件目录存在
if not os.path.exists(PLUGIN_DIR):
    os.makedirs(PLUGIN_DIR)

# 系统信息文件路径
SYSTEM_INFO_FILE = os.path.join(PLUGIN_DIR, 'system_info.yml')
# 名片模板文件路径
NAME_TEMPLATE_FILE = os.path.join(PLUGIN_DIR, 'name.yml')

def read_yaml_file(file_path):
    encodings = ['utf-8', 'gbk', 'iso-8859-1']
    for encoding in encodings:
        try:
            with open(file_path, 'r', encoding=encoding) as file:
                return yaml.safe_load(file)
        except UnicodeDecodeError:
            logger.warning(f"使用 {encoding} 编码读取文件 {file_path} 失败，尝试下一个编码。")
        except FileNotFoundError:
            return None
        except Exception as e:
            logger.error(f"读取 YAML 文件 {file_path} 时出错: {e}")
            return None
    logger.error(f"无法使用可用编码读取文件 {file_path}。")
    return None

class SystemInfoRecorder:
    def __init__(self, file_path):
        self.file_path = file_path

    def record_system_info(self):
        try:
            template = read_yaml_file(NAME_TEMPLATE_FILE)
            time_format = template.get('time_format', '%H:%M') if template else '%H:%M'
        except Exception as e:
            logger.error(f"读取时间格式配置失败: {e}")
            time_format = '%H:%M'

        cpu_percent = psutil.cpu_percent(interval=1)
        memory_percent = psutil.virtual_memory().percent
        current_time = datetime.datetime.now().strftime(time_format)
        
        # 新增网络状态检测
        try:
            latency = self.get_network_latency()
            packet_loss = self.get_packet_loss()
        except Exception as e:
            logger.warning(f"网络状态检测失败: {e}")
            latency = "未知"
            packet_loss = "未知"

        system_info = {
            "cpu_usage": cpu_percent,
            "memory_usage": memory_percent,
            "current_time": current_time,
            "network_latency": latency,
            "packet_loss": packet_loss
        }

        try:
            with open(self.file_path, 'w', encoding='utf-8') as f:
                yaml.safe_dump(system_info, f, allow_unicode=True)
        except Exception as e:
            logger.error(f"保存系统信息失败: {e}")

    def get_network_latency(self):
        # 实现网络延迟检测逻辑
        return "50ms"  # 示例值

    def get_packet_loss(self):
        # 实现丢包率检测逻辑
        return "0%"  # 示例值

@register("dynamic_group_card", "Your Name", "动态群名片插件", "1.0.0", "repo url")
class DynamicGroupCardPlugin(Star):
    def __init__(self, context: Context):
        super().__init__(context)
        self.info_recorder = SystemInfoRecorder(SYSTEM_INFO_FILE)
        # 用于存储每个群聊的最后修改时间
        self.group_last_modify_time = {}

    @filter.on_decorating_result()
    async def modify_card_before_send(self, event: AstrMessageEvent):
        if event.get_platform_name() == "aiocqhttp":
            from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event import AiocqhttpMessageEvent
            assert isinstance(event, AiocqhttpMessageEvent)
            client = event.bot
            group_id = event.message_obj.group_id

            if group_id:
                now = datetime.datetime.now()
                # 获取该群聊的最后修改时间，如果不存在则为 None
                last_modify_time = self.group_last_modify_time.get(group_id)

                # 检查距离上一次修改是否已经过了一分钟
                if last_modify_time is None or (now - last_modify_time).total_seconds() >= 60:
                    # 每次发消息时记录系统信息
                    self.info_recorder.record_system_info()

                    system_info = read_yaml_file(SYSTEM_INFO_FILE)
                    if system_info is None:
                        cpu_usage = "未知"
                        memory_usage = "未知"
                        current_time = "未知"
                    else:
                        cpu_usage = system_info.get("cpu_usage", "未知")
                        memory_usage = system_info.get("memory_usage", "未知")
                        current_time = system_info.get("current_time", "未知")

                    template = read_yaml_file(NAME_TEMPLATE_FILE)
                    if template is None:
                        card_format = "Neko - {current_time}"
                    else:
                        card_format = template.get('card_format', "Neko0v0-脑容量{memory_usage}%-{current_time}")

                    new_card = card_format.format(cpu_usage=cpu_usage, memory_usage=memory_usage, current_time=current_time)

                    payload = {
                        "group_id": group_id,
                        "user_id": event.message_obj.self_id,
                        "card": new_card
                    }

                    max_retries = 3
                    retry_count = 0
                    base_delay = 2  # 初始延迟2秒
                    
                    while retry_count < max_retries:
                        try:
                            result = await client.api.call_action('set_group_card', **payload)
                            logger.info(f"成功修改群 {group_id} 中Bot的群名片为 {new_card}，API返回: {result}")
                            self.group_last_modify_time[group_id] = now
                            break
                        except Exception as e:
                            delay = base_delay ** retry_count
                            logger.warning(f"修改群名片失败，第 {retry_count + 1} 次重试 ({delay}秒后): {e}")
                            await asyncio.sleep(delay)
                            retry_count += 1
                    else:
                        logger.error(f"修改群 {group_id} 名片失败，已达最大重试次数 {max_retries}")
                        self.group_last_modify_time[group_id] = now  # 防止持续失败时频繁重试
