# =========================================================================
# service/call_comfy.py 的最终定制版 (完整无省略)
# 严格按照您的要求，使用 Comp.File 发送视频
# =========================================================================
import uuid
import aiohttp
import json
import os
import io
import ssl
import certifi
from astrbot.api.event import MessageChain
from astrbot.api import message_components as Comp
from astrbot import logger
from ..utils.utils import get_workflow_settings, create_workflow, get_config_section, evaluate_custom_rule
import asyncio

class Call_Comfy:
    # --- 类变量定义保持100%原始状态 ---
    CLIENT_ID = str(uuid.uuid4())
    SERVER_URL = get_config_section('comfy').get('url_header') + "://" + get_config_section('comfy').get('server_domain')
    WS_HEADER = "ws" if get_config_section('comfy').get('url_header') == "http" else "wss"
    SERVER_WS_URL = WS_HEADER + "://" + get_config_section('comfy').get('server_domain')
    OUTPUT_IMAGE_FILE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data/output")
    DEFAULT_WORKFLOW = get_config_section('comfy').get('default_workflow')

    # --- generate_image 函数被最终定制 ---
    async def generate_image(self, info, astr_self, unified_msg_origin):
        # 准备和提交工作流的逻辑，与原始版本完全一致
        image_url = info.get("send_image")
        if image_url:
            image_filename = info.get("send_image_key") + ".png"
            await self.upload_image(image_url, image_filename)
            del info["send_image_key"]
            info["send_image"] = image_filename
        workflow_setting = get_workflow_settings(self.get_workflow(info))
        model_name = info.get("model")
        if model_name:
            info["model"] = model_name + "." + self.get_model_fullname(model_name)
        promptWorkflow = create_workflow(workflow_setting, info)
        queued_prompt_info = await self.queue_prompt(promptWorkflow)
        prompt_id = queued_prompt_info["prompt_id"]
        
        # 调用我们升级过的文件查找函数
        output_file_path = await self.track_progress_and_get_images(prompt_id)

        # 如果没有找到任何文件，直接返回
        if not output_file_path:
            logger.error("任务执行完毕，但未找到任何输出文件。")
            error_chain = MessageChain([Comp.Plain(text="任务执行完毕，但未找到任何输出文件。")])
            await astr_self.context.send_message(unified_msg_origin, error_chain)
            return

        # 构建文本消息的逻辑，与原始版本完全一致
        complete_msg_setting = get_config_section('messages').get('complete_message')
        complete_msg = " 作品好了喵 \n"
        if complete_msg_setting:
            complete_msg_base = complete_msg_setting.get("base_string")
            if complete_msg_base:
                complete_msg = complete_msg_base + "\n"
                addition = complete_msg_setting.get("addtion")
                if addition:
                    for key, value in addition.items():
                        info_value = info.get(key)
                        if info_value:
                            complete_msg = complete_msg + value + str(info_value) + "\n"
        video_complete_msg_setting = get_config_section('messages').get('video_complete_message')
        video_complete_msg = " 视频好了喵 \n" # 提供一个默认值
        if video_complete_msg_setting:
            video_complete_msg_base = video_complete_msg_setting.get("base_string")
            if video_complete_msg_base:
                video_complete_msg = video_complete_msg_base + "\n"
                addition = video_complete_msg_setting.get("video_addtion")
                if addition:
                    for key, value in addition.items():
                        info_value = info.get(key)
                        if info_value:
                            video_complete_msg = video_complete_msg + value + str(info_value) + "\n"                    
        
        # --- 核心定制：新的、区分文件类型的发送逻辑 ---
        file_extension = os.path.splitext(output_file_path)[1].lower()

        # 如果是图片，就使用原始的、带信息框的发送方式
        if file_extension in ['.png', '.jpg', '.jpeg', '.gif', '.webp']:
            logger.info(f"检测到图片文件，将以富媒体消息形式发送: {output_file_path}")
            message_chain = MessageChain().message(complete_msg).file_image(output_file_path)
            await astr_self.context.send_message(unified_msg_origin, message_chain)

        # 如果是视频，就先发文字，再用 Comp.File 单独发送文件
        elif file_extension == '.mp4':
            logger.info(f"检测到视频文件，将根据您的要求以 Comp.File 形式发送: {output_file_path}")
            # 1. 先发送文本消息
            text_chain = MessageChain([Comp.Plain(text=video_complete_msg)])
            await astr_self.context.send_message(unified_msg_origin, text_chain)
            await asyncio.sleep(0.5)

            # 2. 再单独发送视频文件
            # --- 关键修改：使用 Comp.File ---
            filename = os.path.basename(output_file_path) # 从路径中提取文件名
            file_component = Comp.File(file=output_file_path, name=filename)
            file_chain = MessageChain([file_component])
            await astr_self.context.send_message(unified_msg_origin, file_chain)
        else:
            logger.warning(f"检测到不支持的文件类型，无法发送: {output_file_path}")

    # --- 其他辅助函数保持100%原始状态 ---
    async def upload_image(self, image_url, filename):
        image_content = None
        content_type = 'image/png'
        image_url = image_url.replace("https://", "http://")
        try:
            #下载图片
            ssl_context_download = ssl.create_default_context(cafile=certifi.where())
            connector_download = aiohttp.TCPConnector(ssl=ssl_context_download)
            async with aiohttp.ClientSession(connector=connector_download, trust_env=True) as session_download:
                async with session_download.get(image_url) as resp_download:
                    resp_download.raise_for_status()
                    image_content = await resp_download.read()
                    content_type = resp_download.headers.get('Content-Type', 'image/png')

        except (aiohttp.ClientConnectorSSLError, aiohttp.ClientConnectorCertificateError) as ssl_error:
            async with aiohttp.ClientSession(trust_env=True) as session_download_fallback:
                async with session_download_fallback.get(image_url, ssl=False) as resp_download_fallback: # ssl=False 禁用SSL验证
                    resp_download_fallback.raise_for_status()
                    image_content = await resp_download_fallback.read()
                    content_type = resp_download_fallback.headers.get('Content-Type', 'image/png')
        except aiohttp.ClientResponseError as http_error: # 处理下载时的HTTP错误
            print(f"图片下载失败 (HTTP错误): {http_error.status} {http_error.message} 从 {image_url}")
            raise http_error
        except Exception as e: # 其他下载错误
            print(f"图片下载时发生未知错误: {e} 从 {image_url}")
            raise e
        
        if image_content is None:
            raise ValueError(f"无法从 {image_url} 下载图片内容")
        
        #上传到comfy
        try:
            upload_url = f"{self.SERVER_URL}/upload/image"
            form_data = aiohttp.FormData()
            form_data.add_field(
                'image',
                io.BytesIO(image_content), # 将bytes包装在BytesIO中
                filename=filename,
                content_type=content_type
            )
            form_data.add_field('overwrite', 'true')

            async with aiohttp.ClientSession(trust_env=True) as session_upload:
                async with session_upload.post(upload_url, data=form_data) as resp_upload:
                    resp_upload.raise_for_status()

        except Exception as error:
            print(f'图片上传失败: {error}')
            raise error

    def get_workflow(self, info):
        workflow = self.DEFAULT_WORKFLOW

        #取得工作流设定
        workflow_settings = get_config_section("switch_workflow")
        if workflow_settings:
            for workflow_setting in workflow_settings:
                workflow_name = workflow_setting.get("workflow_name")
                if not workflow_name:
                    pass
                check = False
                workflow_models = workflow_setting.get("model")
                model_name = info.get("model")
                if workflow_models and model_name:
                    workflow_models_split = workflow_models.split(",")
                    if model_name in workflow_models_split:
                        check = True
                workflow_param_rule = workflow_setting.get("param_rule")
                if workflow_param_rule:
                    try:
                        check = evaluate_custom_rule(workflow_param_rule, info)
                    except Exception as e:
                        print(f"规则判断发生错误: {e}")
                        check = False
                
                if check:
                    workflow = workflow_name

        return workflow
    
    def get_model_fullname(self, model: str):
        config_models = get_config_section("comfy_models")
        for config_model in config_models:
            if config_model["name"] == model:
                type = config_model.get("type") if config_model.get("type") else "safetensors"
                return type
        return "safetensors"

    async def queue_prompt(self, workflow):
        payload = {
            "prompt": workflow,
            "client_id": self.CLIENT_ID
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(f"{self.SERVER_URL}/prompt", json=payload) as response:
                response_data = await response.json()
                status_code = response.status
                if response_data:
                    if "prompt_id" in response_data:
                        print(f"工作流程已成功提交! Prompt ID: {response_data['prompt_id']}")
                        return response_data
    
    async def get_history(self, prompt_id):
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{self.SERVER_URL}/history/{prompt_id}") as response:
                if response.status == 200:
                    history_data = await response.json()
                    return history_data
                
    async def get_image(self, filename, subfolder, folder_type):
        params = {"filename": filename, "subfolder": subfolder, "type": folder_type}
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{self.SERVER_URL}/view", params=params) as response:
                if response.status == 200:
                    return await response.read()

    async def check_status(self):
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(f"{self.SERVER_URL}/system_stats", timeout=5) as response:
                    if response.status == 200:
                        return True
                    else:
                        return False
        except Exception as e:
            return False

    # --- track_progress_and_get_images 函数保持我们升级后的“双重查找”版本 ---
    async def track_progress_and_get_images(self, prompt_id):
        ws_url = f"{self.SERVER_WS_URL}/ws?clientId={self.CLIENT_ID}"
        
        async with aiohttp.ClientSession() as session:
            async with session.ws_connect(ws_url) as ws:
                async for msg in ws:
                    if msg.type == aiohttp.WSMsgType.TEXT:
                        message_data = json.loads(msg.data)
                        if message_data.get("type") == "executing":
                            data = message_data.get("data", {})
                            if data.get("prompt_id") == prompt_id and data.get("node") is None:
                                break
                    elif msg.type in [aiohttp.WSMsgType.ERROR, aiohttp.WSMsgType.CLOSED]:
                        break

        history = await self.get_history(prompt_id)
        if not (history and prompt_id in history):
            return None
        
        prompt_outputs = history[prompt_id].get("outputs", {})
        final_files_to_fetch = []
        
        # 核心补丁：在查找 "images" 的基础上，增加查找 "gifs"
        for node_id, node_output in prompt_outputs.items():
            if "images" in node_output:
                for item in node_output["images"]:
                    if isinstance(item, dict) and 'filename' in item:
                        if item not in final_files_to_fetch:
                            logger.info(f"找到图片文件: {item.get('filename')}")
                            final_files_to_fetch.append(item)
            
            if "gifs" in node_output:
                for item in node_output["gifs"]:
                    if isinstance(item, dict) and 'filename' in item and item['filename'].endswith('.mp4'):
                        if item not in final_files_to_fetch:
                            logger.info(f"找到视频(.mp4)文件: {item.get('filename')}")
                            final_files_to_fetch.append(item)
        
        if not final_files_to_fetch:
            return None

        first_file_detail = final_files_to_fetch[0]
        try:
            file_data = await self.get_image(
                first_file_detail["filename"],
                first_file_detail.get("subfolder", ""),
                first_file_detail.get("type", "output")
            )
            if file_data:
                os.makedirs(self.OUTPUT_IMAGE_FILE_PATH, exist_ok=True)
                file_path = os.path.join(self.OUTPUT_IMAGE_FILE_PATH, first_file_detail["filename"])
                with open(file_path, "wb") as f:
                    f.write(file_data)
                logger.info(f"文件已成功保存到: {file_path}")
                return file_path
        except Exception as e:
            logger.error(f"下载或保存最终文件时出错: {e}")
            return None
        
        return None