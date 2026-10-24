"""Shared system-prompt policies. Command execution remains approval based."""

DEPENDENCY_POLICY = (
    "【依赖安装规则】"
    "Python 依赖必须安装在经过核实的项目专用虚拟环境中，优先复用当前项目的 .venv；"
    "没有虚拟环境时，先通过 uv venv 或 python -m venv 创建当前项目的 .venv，再安装依赖。"
    "安装前先确认目标虚拟环境的绝对路径，并用其 Python 检查 sys.executable、sys.prefix 和 sys.base_prefix，"
    "确认 sys.prefix != sys.base_prefix 且解释器确实属于目标虚拟环境；不得把 E_coder 宿主环境自动当作所有用户项目的环境。"
    "每次命令都是独立子进程，不能依赖上一条命令中的 activate 激活状态。"
    "安装时使用虚拟环境 Python 的绝对路径执行 -m pip install，或使用 uv pip install --python 明确指定该虚拟环境解释器；"
    "安装后的运行与验证也必须使用同一个解释器。"
    "禁止裸 pip install、未确认解释器的 python -m pip install，以及 --user、uv pip install --system、--break-system-packages、"
    "指向环境外的 --target/--prefix 等绕过隔离的安装方式。虚拟环境安装失败时不得回退到全局或用户级安装。"
    "非 Python 依赖也必须使用项目本地的隔离依赖目录，例如 Node.js 的 node_modules；禁止 npm install -g、"
    "向 conda base 或通过系统包管理器全局安装依赖。无法在项目内隔离时，先停止并说明原因。"
    "安装前向用户说明目标环境、待安装的包和用途，通过 run_command 申请批准；不能绕过审批，也不能仅凭安装命令退出成功就声称项目验证通过。"
)
