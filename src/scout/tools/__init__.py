"""内置工具包：导入即注册。

新增工具时：在对应模块里 register(ToolSpec(...))，然后在下面加一行 import。
"""
from . import registry  # noqa: F401
from . import web  # noqa: F401
from . import hot  # noqa: F401
from . import data  # noqa: F401

__all__ = ["registry", "web", "hot", "data"]
