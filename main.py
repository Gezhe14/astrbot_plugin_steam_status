import httpx
import asyncio
from astrbot.api.star import Context, Star, register
from astrbot.api.event import filter, AstrMessageEvent, MessageChain
import astrbot.api.message_components as Comp
from astrbot.api import logger

@register("steam_status_monitor", "Gezhe14", "显示Steam服务器目前状态", "1.2.2")
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
        
        # 创建共享的 HTTP 客户端
        self.client = httpx.AsyncClient(timeout=10.0)
        
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
            
            # 关闭 HTTP 客户端
            await self.client.aclose()
            logger.info("[SteamStatus] 监控任务已停止，资源已释放")
        except Exception as e:
            logger.error(f"[SteamStatus] 插件停止时出错: {e}")

    async def fetch_status(self, url: str) -> bool:
        """执行网络请求检测状态"""
        try:
            # 复用 self.client
            response = await self.client.get(url)
            return 200 <= response.status_code < 400
        except Exception:
            return False

    async def monitor_loop(self):
        """核心监控循环逻辑"""
        # 启动时等待 10 秒，确保 AstrBot 平台连接就绪
        await asyncio.sleep(10)

        # 输出当前配置信息
        logger.info(f"[SteamStatus] 监控任务已启动。当前加载配置：\n"
                    f"  - 自动监控开关 (auto_check): {'开启' if self.config.get('auto_check', False) else '关闭'}\n"
                    f"  - 检测间隔 (check_interval): {self.config.get('check_interval', 1)} 分钟\n"
                    f"  - 自动推送目标 (auto_push_groups): {self.config.get('auto_push_groups', [])}\n"
                    f"  - 指令权限模式 (permission_mode): {self.config.get('permission_mode', 'whitelist')}\n"
                    f"  - 指令权限列表 (allowed_groups): {self.config.get('allowed_groups', [])}")
        
        has_logged_disabled = False

        while True:
            try:
                # 直接从 self.config 获取配置
                # 获取全局按钮状态
                is_master_on = self.config.get("auto_check", False)
                # 获取推送到部分群的名单
                push_list = self.config.get("auto_push_groups", [])
                interval = self.config.get("check_interval", 1)

                # 只有全局开关开启且推送名单不为空时才执行
                if is_master_on and push_list:
                    # 如果条件满足，重置日志标志位
                    has_logged_disabled = False
                    
                    changes = []
                    names = list(self.targets.keys())
                    urls = list(self.targets.values())
                    
                    # 并发请求以提高性能
                    results = await asyncio.gather(*(self.fetch_status(url) for url in urls))
                    
                    for name, current_is_ok in zip(names, results):
                        if current_is_ok != self.last_status[name]:
                            state_msg = "✅ 已恢复正常" if current_is_ok else "❌ 出现访问故障"
                            changes.append(f"{name}: {state_msg}")
                            self.last_status[name] = current_is_ok
                    
                    if changes:
                        notice_text = "⚠️ Steam 服务状态变更通知：\n" + "\n".join(changes)
                        logger.info(f"[SteamStatus] 状态发生变更，准备推送: {changes}")
                        
                        # 构建消息组件列表
                        components = [Comp.Plain(notice_text)]
                        # 使用 AstrBot 定义的 MessageChain
                        message_obj = MessageChain(components)
                        
                        for unified_id in push_list:
                            try:
                                logger.info(f"[SteamStatus] 正在推送消息到: {unified_id}")
                                # 确保 unified_id 为字符串
                                target_id = str(unified_id).strip()
                                await self.context.send_message(target_id, message_obj)
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
        # 获取权限模式
        mode = self.config.get("permission_mode", "whitelist")
        
        # 获取群名单，并统一转换为字符串以确保类型安全
        raw_groups = self.config.get("allowed_groups", [])
        permission_groups = [str(g) for g in raw_groups]
        
        current_id = str(event.unified_msg_origin)
        
        # 权限校验
        if mode == "whitelist":
            # 白名单模式：如果名单为空，或者当前群不在名单内，则拦截
            if not permission_groups:
                 logger.warning("[SteamStatus] 白名单模式下列表为空，所有指令将被拦截。请在配置中添加允许的群组 ID。")
                 return
            if current_id not in permission_groups:
                logger.info(f"拦截到未授权群组 {current_id} 的指令请求 (不在白名单)")
                return
        else:
            # 黑名单模式：如果当前群在名单内，则拦截
            if current_id in permission_groups:
                logger.info(f"拦截到黑名单群组 {current_id} 的指令请求")
                return

        yield event.plain_result("正在检测 Steam 服务状态，请稍候...")
        
        names = list(self.targets.keys())
        urls = list(self.targets.values())
        
        # 并发请求
        statuses = await asyncio.gather(*(self.fetch_status(url) for url in urls))
        
        results = [f"{name}: {'✅ 正常' if is_ok else '❌ 异常'}" for name, is_ok in zip(names, statuses)]
        
        yield event.plain_result("📊 Steam 当前状态报告：\n" + "\n".join(results))