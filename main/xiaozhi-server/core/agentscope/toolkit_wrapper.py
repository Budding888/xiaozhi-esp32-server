"""
xiaozhi 插件系统 → AgentScope Toolkit 适配器 (2.0.2)

将现有 @register_function 注册的插件函数包装为 AgentScope 2.0.2
FunctionTool，使 Agent 可以调用现有插件系统。

使用方式:
    toolkit = XiaozhiToolkitWrapper(conn)
    toolkit = XiaozhiToolkitWrapper(conn, function_names=["get_weather", "get_time"])
"""

from agentscope.tool import Toolkit, FunctionTool, ToolChunk
from plugins_func.register import all_function_registry, Action
from config.logger import setup_logging

TAG = __name__
logger = setup_logging()


class XiaozhiToolkitWrapper(Toolkit):
    """
    将 xiaozhi 现有插件系统包装为 AgentScope 2.0.2 Toolkit。

    从 all_function_registry 全局函数注册表中加载指定的插件函数，
    注册到 AgentScope Toolkit 中，使 Agent 可以调用。

    属性:
        conn: ConnectionHandler 实例
        registered_count: 已注册的工具数量
    """

    def __init__(self, conn, function_names: list = None):
        """
        初始化工具包包装器。

        Args:
            conn: ConnectionHandler 实例（传递给插件函数的 conn 参数）
            function_names: 要注册的函数名列表
                           None = 注册全部可用函数
                           ["name1", "name2"] = 仅注册指定函数
        """
        tools = []
        self.conn = conn
        self.registered_count = 0

        # 从全局注册表中加载工具
        registry = all_function_registry
        if not registry:
            logger.bind(tag=TAG).warning("全局函数注册表为空，请确认插件已加载")
            super().__init__(tools=[])
            return

        names = function_names if function_names is not None else list(registry.keys())

        for name in names:
            func_item = registry.get(name)
            if not func_item:
                logger.bind(tag=TAG).warning(f"函数 '{name}' 未在注册表中找到，跳过")
                continue

            try:
                func_desc = func_item.description
                desc_text = ""
                if isinstance(func_desc, dict):
                    inner = func_desc.get("function", func_desc)
                    desc_text = inner.get("description", "") if isinstance(inner, dict) else str(inner)
                else:
                    desc_text = str(func_desc)

                # 创建 FunctionTool（2.0.2 API）
                ft = FunctionTool(
                    func=self._make_tool_func(name),
                    name=name,
                    description=desc_text,
                )
                tools.append(ft)
                self.registered_count += 1
                logger.bind(tag=TAG).debug(f"AgentScope 工具已注册: {name}")

            except Exception as e:
                logger.bind(tag=TAG).error(f"注册 AgentScope 工具失败 [{name}]: {e}")

        # 调用 Toolkit.__init__ 传入 tools 列表
        super().__init__(tools=tools)

        logger.bind(tag=TAG).info(
            f"AgentScope 工具包初始化完成: 注册 {self.registered_count}/{len(names)} 个工具"
        )

    def _make_tool_func(self, name):
        """
        创建包装后的工具函数。

        Args:
            name: 插件函数名称

        Returns:
            function: 返回 ToolChunk 的函数
        """
        func_item = all_function_registry.get(name)

        def tool_func(**kwargs) -> ToolChunk:
            """包装后的工具函数，被 AgentScope 调用"""
            try:
                result = func_item.func(self.conn, **kwargs)
                content_text = ""

                if hasattr(result, "action"):
                    if result.result:
                        content_text = str(result.result)
                    elif result.response:
                        content_text = str(result.response)

                    return ToolChunk(
                        content=[{"type": "text", "text": content_text}],
                        metadata={"action": result.action.name},
                        is_last=True,
                    )
                else:
                    return ToolChunk(
                        content=[{"type": "text", "text": str(result)}],
                        is_last=True,
                    )
            except Exception as e:
                logger.bind(tag=TAG).error(f"AgentScope 工具调用失败 [{name}]: {e}")
                return ToolChunk(
                    content=[{"type": "text", "text": f"工具调用失败: {e}"}],
                    metadata={"error": str(e)},
                    is_last=True,
                )

        return tool_func

    def has_tool(self, name: str) -> bool:
        """检查指定名称的工具是否已注册"""
        if not self.tool_groups:
            return False
        basic = self.tool_groups[0]
        return any(t.name == name for t in basic.tools)
