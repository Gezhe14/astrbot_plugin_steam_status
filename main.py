import httpx
import asyncio
from astrbot.api.star import Context, Star, register
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api import logger

@register("steam_status_monitor", "qiyi", "Steam服务器状态显示", "1.0.0")
class SteamMonitorPlugin(Star):
    def __init__(self, context: Context):
        super().__init__(context)
        self.targets = {
            "Steam 商店": "https://store.steampowered.com",
            "Steam 社区": "https://steamcommunity.com",
            "Steam API": "https://api.steampowered.com/ISteamWebAPIUtil/GetServerInfo/v1/"
        }
        self.last_status = {name: True for name in self.targets}
        
        # 启动后台监控协程
        asyncio.create_task(self.monitor_loop())

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
        while True:
            try:
                config = self.context.get_config()
                # 获取全局按钮状态
                is_master_on = config.get("auto_check", False)
                # 获取推送到部分群的名单
                push_list = config.get("auto_push_groups", [])
                interval = config.get("check_interval", 5)

                # 只有全局开关开启且推送名单不为空时才执行
                if is_master_on and push_list:
                    changes = []
                    for name, url in self.targets.items():
                        current_is_ok = await self.fetch_status(url)
                        if current_is_ok != self.last_status[name]:
                            state_msg = "✅ 已恢复正常" if current_is_ok else "❌ 出现访问故障"
                            changes.append(f"{name}: {state_msg}")
                            self.last_status[name] = current_is_ok
                    
                    if changes:
                        notice_text = "⚠️ Steam 服务状态变更通知：\n" + "\n".join(changes)
                        for unified_id in push_list:
                            try:
                                await self.context.send_message(
                                    event=None, 
                                    target_id=str(unified_id).strip(), 
                                    message=notice_text
                                )
                            except Exception as e:
                                logger.error(f"定时推送失败，目标: {unified_id}，错误: {e}")

            except Exception as e:
                logger.error(f"Steam 监控循环发生错误: {e}")

            await asyncio.sleep(interval * 60)

    @filter.command("steamstatus")
    async def on_steam_status(self, event: AstrMessageEvent):
        """处理手动查询指令"""
        config = self.context.get_config()
        # 获取允许使用指令的群名单
        allowed_groups = config.get("allowed_groups", [])
        current_id = event.unified_msg_origin
        
        # 权限校验：如果设置了名单且当前群不在名单内则跳过
        if allowed_groups and current_id not in allowed_groups:
            logger.info(f"拦截到未授权群组 {current_id} 的指令请求")
            return

        yield event.plain_result("正在检测 Steam 服务质量，请稍候...")
        
        results = []
        for name, url in self.targets.items():
            is_ok = await self.fetch_status(url)
            results.append(f"{name}: {'✅ 正常' if is_ok else '❌ 异常'}")
        
        yield event.plain_result("📊 Steam 当前状态报告：\n" + "\n".join(results))