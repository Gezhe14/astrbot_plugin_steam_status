import httpx
import asyncio
from astrbot.api.star import Context, Star, register
from astrbot.api.event import filter, AstrMessageEvent
import astrbot.api.message_components as Comp
from astrbot.api import logger, AstrBotConfig

# 自定义包装类，用于满足 Context.send_message 对参数对象必须有 .chain 属性的要求
class MessageChainWrapper:
    def __init__(self, components=None):
        self.chain = components or []

@register("steam_status_monitor", "Gezhe14", "显示Steam服务器目前状态", "1.1.1")
class SteamStatusMonitorPlugin(Star):
    def __init__(self, context: Context, config: dict):
        super().__init__(context)
        self.config = config
        self.targets = {
            "Steam 商店": "https://store.steampowered.com",
            "Steam 社区": "https://steamcommunity.com",
            "Steam API": "https://api.steampowered.com/ISteamWebAPIUtil/GetServerInfo/v1/"
        }
        self.last_status = {name: True for name in self.targets}
        
        # 启动后台监控协程，并保存句柄以便销毁
        self.monitor_task = asyncio.create_task(self.monitor_loop())

    async def terminate(self):
        """插件卸载时调用，清理资源"""
        try:
            logger.info("[SteamStatus] 正在停止监控任务...")
            if self.monitor_task:
                self.monitor_task.cancel()
                try:
                    await self.monitor_task
                except asyncio.CancelledError:
                    pass
            logger.info("[SteamStatus] 监控任务已停止")
        except Exception as e:
            logger.error(f"[SteamStatus] 插件停止时出错: {e}")

    async def fetch_status(self, url: str) -> bool:
        """执行网络请求检测状态"""
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(url)
                return 200 <= response.status_code < 400
        except Exception:
            return False

    async def monitor_loop(self):
        """核心监控循环逻辑"""
        # 启动时等待 10 秒，确保 AstrBot 平台连接就绪
        await asyncio.sleep(10)
        
        has_logged_disabled = False

        while True:
            try:
                # 直接从 self.config 获取配置
                # 获取全局按钮状态
                is_master_on = self.config.get("auto_check", False)
                # 获取推送到部分群的名单
                push_list = self.config.get("auto_push_groups", [])
                interval = self.config.get("check_interval", 5)

                # 只有全局开关开启且推送名单不为空时才执行
                if is_master_on and push_list:
                    # 如果条件满足，重置日志标志位
                    has_logged_disabled = False
                    
                    changes = []
                    for name, url in self.targets.items():
                        current_is_ok = await self.fetch_status(url)
                        if current_is_ok != self.last_status[name]:
                            state_msg = "✅ 已恢复正常" if current_is_ok else "❌ 出现访问故障"
                            changes.append(f"{name}: {state_msg}")
                            self.last_status[name] = current_is_ok
                    
                    if changes:
                        notice_text = "⚠️ Steam 服务状态变更通知：\n" + "\n".join(changes)
                        logger.info(f"[SteamStatus] 状态发生变更，准备推送: {changes}")
                        
                        # 构建消息组件列表
                        components = [Comp.Plain(notice_text)]
                        # 使用包装类封装
                        message_obj = MessageChainWrapper(components)
                        
                        for unified_id in push_list:
                            try:
                                logger.info(f"[SteamStatus] 正在推送消息到: {unified_id}")
                                await self.context.send_message(str(unified_id).strip(), message_obj)
                            except Exception as e:
                                logger.error(f"定时推送失败，目标: {unified_id}，错误: {e}")
                else:
                    # 仅在从未记录过时打印，避免刷屏
                    if not has_logged_disabled:
                        logger.info("[SteamStatus] 自动监控未满足执行条件（开关关闭或无推送目标）")
                        has_logged_disabled = True

            except Exception as e:
                logger.error(f"Steam 监控循环发生错误: {e}")

            await asyncio.sleep(interval * 60)

    @filter.command("steamstatus")
    async def on_steam_status(self, event: AstrMessageEvent):
        """处理手动查询指令"""
        # 获取允许使用指令的群名单
        allowed_groups = self.config.get("allowed_groups", [])
        current_id = event.unified_msg_origin
        
        # 权限校验：如果名单为空，或者当前群不在名单内，则全部拦截
        if not allowed_groups or current_id not in allowed_groups:
            logger.info(f"拦截到未授权群组 {current_id} 的指令请求")
            return

        yield event.plain_result("正在检测 Steam 服务状态，请稍候...")
        
        results = []
        for name, url in self.targets.items():
            is_ok = await self.fetch_status(url)
            results.append(f"{name}: {'✅ 正常' if is_ok else '❌ 异常'}")
        
        yield event.plain_result("📊 Steam 当前状态报告：\n" + "\n".join(results))