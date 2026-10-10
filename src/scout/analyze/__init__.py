"""分析层：把采集到的数据变成能看懂的画像结论。

原则：这里只读数据库，不做任何网络访问。
任何结论都必须能追回到具体行数（样本量写在结果里），避免在小样本上过度解读。
"""

from .report import export_csv, overview, analyze_users, render_markdown

__all__ = ["overview", "analyze_users", "render_markdown", "export_csv"]
