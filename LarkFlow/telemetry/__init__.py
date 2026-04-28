"""LarkFlow 的可观测性实现目录。

本目录是 OpenTelemetry 相关代码的唯一实现层，负责：
1. 初始化 / 关闭 OTEL SDK；
2. 提供统一的手工 span 封装；
3. 收口业务埋点 hook，避免业务文件散落 OTEL 细节。

约定：
- 新代码优先从 ``telemetry.*`` 导入；
- ``pipeline/otel.py`` 与 ``pipeline/otel_hooks.py`` 仅保留兼容转发，不再承载核心实现。
"""
