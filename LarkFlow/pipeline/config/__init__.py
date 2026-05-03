"""LarkFlow pipeline 配置读取入口。

首次 `import pipeline.config` 时会调用 `load_dotenv()` 把 `.env` 加载进
`os.environ`。`load_dotenv` 默认不会覆盖进程里已有的变量，重复调用安全。
所有配置访问最终都会 `import` 到这个包（llm/lark/runtime 都是子模块），
因此原先分散在 app.py / engine.py / lark/interaction.py 里的 `load_dotenv`
调用被本模块一次性接管，不再需要各自保留。
"""

from dotenv import load_dotenv

# 注意：此处不应捕获异常——.env 不存在时 load_dotenv 返回 False，不会抛。
load_dotenv()

from pipeline.config import lark, llm, phases, runtime  # noqa: E402  load_dotenv 必须先跑

__all__ = ["lark", "llm", "phases", "runtime"]
