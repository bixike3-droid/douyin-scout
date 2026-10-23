"""内置工具包：导入即注册。

新增工具时：在对应模块里 register(ToolSpec(...))，然后在下面加一行 import。
"""
from . import registry  # noqa: F401
from . import web  # noqa: F401
from . import hot  # noqa: F401
from . import data  # noqa: F401
from . import collect  # noqa: F401
from . import delegate  # noqa: F401
from . import insight  # noqa: F401
from . import enterprise_tools  # noqa: F401
from . import attachments  # noqa: F401
from . import attachment_workspace  # noqa: F401
from . import workspace  # noqa: F401

__all__ = ["registry", "web", "hot", "data", "collect", "delegate", "insight", "enterprise_tools", "attachments"]
