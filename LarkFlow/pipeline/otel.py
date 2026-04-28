"""``telemetry.otel`` 的兼容转发层。

保留这个文件的原因：
1. 兼容旧分支、旧模块里仍然使用 ``pipeline.otel`` 的导入路径；
2. 降低大规模迁移时的合并冲突风险。

维护约定：
- 新代码不要再把核心实现写到这里；
- OTEL SDK 初始化、Tracer、no-op span 等真实逻辑统一维护在 ``telemetry/otel.py``。
"""

from telemetry.otel import *  # noqa: F401,F403
