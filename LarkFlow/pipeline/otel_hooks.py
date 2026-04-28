"""``telemetry.hooks`` 的兼容转发层。

保留这个文件的原因：
1. 兼容仍然从 ``pipeline.otel_hooks`` 导入的旧代码；
2. 让业务代码迁移到 ``telemetry/hooks.py`` 时可以渐进完成。

维护约定：
- 业务埋点命名、attributes 设计、运行时 setup 等逻辑统一维护在 ``telemetry/hooks.py``；
- 本文件仅负责向后兼容，不应继续新增核心实现。
"""

from telemetry.hooks import *  # noqa: F401,F403
