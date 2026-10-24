# 一、E_coder 数据库：一次完整操作的存储示例

用户选择 `C:\Projects\python`，发送：

> 创建 word_count.py，统计 Hello world hello 的词频，运行验证，并记录结果。

假设目录里只有已配置好的 `.venv`（目录工具会忽略它），用户批准写入和运行。Agent 先检查目录并创建任务，再写入、验证、保存备忘录，最后回复。

本次共有 **5 次模型调用、7 次工具调用、13 条 messages 记录**。一个模型回复可以同时提出多个工具调用，后端依次执行。

## 1. 会话与工作区

E_coder 使用 `uuid.uuid4().hex` 生成它，是一个 32 位的十六进制字符串。

`sessions` 中的一行：

```json
{
  "id": "11111111111111111111111111111111",
  "title": "创建 word_count.py，统计 Hello world hello 的词频，运行验证，并记录结果。",
  "created": 1792713600.0,
  "archived": 0
}
```

`session_workspaces` 中的一行：

```json
{
  "session": "11111111111111111111111111111111",
  "path": "C:\\Projects\\python"
}
```

## 2. messages：完整的 13 条记录

每行都有 `id`、`session`、`body`。下面按顺序列出每条记录的 **完整 body**；共同的 session 为上面的会话 ID，示意 id 为 1–13。数据库中的 body 实际是 JSON 字符串，此处展开方便阅读。

`arguments` 和工具消息的 `content` 本身也是 JSON 字符串，所以会出现转义符；这与当前代码的存储格式一致。

### id=1：用户提出需求

```json
{
  "role": "user",
  "content": "创建 word_count.py，统计 Hello world hello 的词频，运行验证，并记录结果。"
}
```

### id=2：AI 请求检查目录、创建任务

```json
{
  "role": "assistant",
  "content": null,
  "tool_calls": [
    {
      "id": "call_01",
      "type": "function",
      "function": {
        "name": "list_files",
        "arguments": "{\"path\": \".\"}"
      }
    },
    {
      "id": "call_02",
      "type": "function",
      "function": {
        "name": "create_task",
        "arguments": "{\"title\": \"创建并验证单词统计程序\", \"dependencies\": []}"
      }
    }
  ]
}
```

### id=3：目录工具返回结果

```json
{
  "role": "tool",
  "tool_call_id": "call_01",
  "content": "[]"
}
```

### id=4：任务创建工具返回结果

```json
{
  "role": "tool",
  "tool_call_id": "call_02",
  "content": "{\"id\": \"a1b2c3d4e5f6\", \"title\": \"创建并验证单词统计程序\", \"dependencies\": [], \"status\": \"pending\"}"
}
```

### id=5：AI 请求开始任务、写入文件

```json
{
  "role": "assistant",
  "content": null,
  "tool_calls": [
    {
      "id": "call_03",
      "type": "function",
      "function": {
        "name": "update_task",
        "arguments": "{\"id\": \"a1b2c3d4e5f6\", \"status\": \"in_progress\"}"
      }
    },
    {
      "id": "call_04",
      "type": "function",
      "function": {
        "name": "write_file",
        "arguments": "{\"path\": \"word_count.py\", \"content\": \"from collections import Counter\\nimport json\\n\\n\\ndef count_words(text):\\n    return dict(Counter(text.lower().split()))\\n\\n\\nif __name__ == \\\"__main__\\\":\\n    result = count_words(\\\"Hello world hello\\\")\\n    assert result == {\\\"hello\\\": 2, \\\"world\\\": 1}\\n    print(json.dumps(result))\\n\"}"
      }
    }
  ]
}
```

### id=6：任务状态更新结果

```json
{
  "role": "tool",
  "tool_call_id": "call_03",
  "content": "{\"id\": \"a1b2c3d4e5f6\", \"title\": \"创建并验证单词统计程序\", \"dependencies\": [], \"status\": \"in_progress\"}"
}
```

### id=7：用户批准后，文件写入结果

```json
{
  "role": "tool",
  "tool_call_id": "call_04",
  "content": "{\"path\": \"word_count.py\", \"bytes\": 267, \"diff\": \"--- a/word_count.py\\n+++ b/word_count.py\\n@@ -0,0 +1,12 @@\\n+from collections import Counter\\n+import json\\n+\\n+\\n+def count_words(text):\\n+    return dict(Counter(text.lower().split()))\\n+\\n+\\n+if __name__ == \\\"__main__\\\":\\n+    result = count_words(\\\"Hello world hello\\\")\\n+    assert result == {\\\"hello\\\": 2, \\\"world\\\": 1}\\n+    print(json.dumps(result))\\n\"}"
}
```

### id=8：AI 请求运行程序

```json
{
  "role": "assistant",
  "content": null,
  "tool_calls": [
    {
      "id": "call_05",
      "type": "function",
      "function": {
        "name": "run_command",
        "arguments": "{\"argv\": [\"C:\\\\Projects\\\\python\\\\.venv\\\\Scripts\\\\python.exe\", \"word_count.py\"], \"timeout\": 30}"
      }
    }
  ]
}
```

### id=9：用户批准后，命令运行结果

```json
{
  "role": "tool",
  "tool_call_id": "call_05",
  "content": "{\"exit_code\": 0, \"output\": \"{\\\"hello\\\": 2, \\\"world\\\": 1}\\r\\n\", \"output_limit\": 24000}"
}
```

### id=10：AI 请求保存备忘录、完成任务

```json
{
  "role": "assistant",
  "content": null,
  "tool_calls": [
    {
      "id": "call_06",
      "type": "function",
      "function": {
        "name": "save_memory",
        "arguments": "{\"content\": \"word_count.py 已创建；使用当前目录 .venv 的 Python 运行，断言通过，输出 hello=2、world=1。\"}"
      }
    },
    {
      "id": "call_07",
      "type": "function",
      "function": {
        "name": "update_task",
        "arguments": "{\"id\": \"a1b2c3d4e5f6\", \"status\": \"completed\"}"
      }
    }
  ]
}
```

### id=11：备忘录保存结果

```json
{
  "role": "tool",
  "tool_call_id": "call_06",
  "content": "{\"saved\": true}"
}
```

### id=12：任务完成结果

```json
{
  "role": "tool",
  "tool_call_id": "call_07",
  "content": "{\"id\": \"a1b2c3d4e5f6\", \"title\": \"创建并验证单词统计程序\", \"dependencies\": [], \"status\": \"completed\"}"
}
```

### id=13：AI 最终回复

```json
{
  "role": "assistant",
  "content": "已创建 word_count.py，并使用当前目录的虚拟环境运行验证。断言通过，输出为 {\"hello\": 2, \"world\": 1}。"
}
```

**配对关系：** AI 发出的 `tool_calls[].id`，必须对应后续工具消息的 `tool_call_id`。例如 `call_05` 请求运行程序，第 9 条消息返回其退出码和输出。AI 的工具调用消息与最终自然语言回复都保存在 messages 中。

**审批点：** 第 5 条消息提出写文件，批准后才有第 7 条结果；第 8 条请求运行，批准后才有第 9 条结果。点击批准走独立接口，审批过程记入 events，不会额外插入一条 user 消息。

## 3. events：这次操作的完整事件顺序

为控制篇幅，表中展示每条事件的类型与含义，正文不重复抄写上面已有的代码和工具结果。实际每条记录都有 `id`、`session`、JSON `body`；body 包含 `type`、`time`、`run_id` 及事件专属字段。事件 id 返回前端时叫 `seq`。

| 示例 seq | type | 内容 |
| --- | --- | --- |
| 1 | `user_message` | 用户原文，attachments=[] |
| 2 | `run_start` | 本次运行开始，mode=live |
| 3 | `step_start` | 第 1 次模型调用 |
| 4 | `tool_start` | call_01：list_files 的参数 |
| 5 | `tool_end` | call_01：list_files 的结果 |
| 6 | `tool_start` | call_02：create_task 的参数 |
| 7 | `tool_end` | call_02：create_task 的结果 |
| 8 | `tasks_update` | 任务完整列表，状态为 pending |
| 9 | `step_start` | 第 2 次模型调用 |
| 10 | `tool_start` | call_03：update_task 的参数 |
| 11 | `tool_end` | call_03：update_task 的结果 |
| 12 | `tasks_update` | 任务完整列表，状态为 in_progress |
| 13 | `tool_start` | call_04：write_file 的参数 |
| 14 | `approval_request` | approval_01：审批 write_file，包含参数、预览、有效期 |
| 15 | `approval_result` | approval_01：allowed=true |
| 16 | `tool_end` | call_04：write_file 的结果 |
| 17 | `step_start` | 第 3 次模型调用 |
| 18 | `tool_start` | call_05：run_command 的参数 |
| 19 | `approval_request` | approval_02：审批 run_command，包含参数、预览、有效期 |
| 20 | `approval_result` | approval_02：allowed=true |
| 21 | `tool_end` | call_05：run_command 的结果 |
| 22 | `step_start` | 第 4 次模型调用 |
| 23 | `tool_start` | call_06：save_memory 的参数 |
| 24 | `tool_end` | call_06：save_memory 的结果 |
| 25 | `tool_start` | call_07：update_task 的参数 |
| 26 | `tool_end` | call_07：update_task 的结果 |
| 27 | `tasks_update` | 任务完整列表，状态为 completed |
| 28 | `step_start` | 第 5 次模型调用 |
| 29 | `text_delta` | 最终回复的文字；本例假设以一个增量返回 |
| 30 | `run_end` | 本次运行结束，status=completed |

这里 `tool_end.result` 对应 messages 中该工具返回的 content；`tool_start.arguments` 对应 AI 工具调用参数。两处保存部分相同内容：messages 用于模型对话，events 用于前端实时展示和回放。

本例假设模型接口未返回 usage，因此没有 usage 事件；真实接口返回时会额外保存，可能一次模型调用产生多条。真实文字流也通常拆成多个 text_delta，所以事件数不是模型调用次数。

## 4. tasks：最终只有一行当前状态

同一个任务先后更新为 pending → in_progress → completed；tasks 表更新原记录，不会因此新增三行。状态变化过程在 events 中保留。

```json
{
  "id": "a1b2c3d4e5f6",
  "session": "11111111111111111111111111111111",
  "body": {
    "id": "a1b2c3d4e5f6",
    "title": "创建并验证单词统计程序",
    "dependencies": [],
    "status": "completed"
  }
}
```

上面将 body 展开显示；实际该列存 JSON 字符串。completed 表示 Agent 更新的状态，当前后端不强制检查测试证据；本例中 Agent 先看到了断言通过和 exit_code=0，才提交完成。

## 5. memories：最终一行备忘录

```json
{
  "session": "11111111111111111111111111111111",
  "content": "word_count.py 已创建；使用当前目录 .venv 的 Python 运行，断言通过，输出 hello=2、world=1。"
}
```

后续同一会话再调用 save_memory 会覆盖这段内容，不会自动追加一条历史备忘录。

## 6. uploads：没有新增记录

本例没有上传文件，因此 uploads 表没有本次会话的附件记录。**Agent 新建的 word_count.py 不是上传附件，不会自动登记到 uploads。**

程序文件实际保存在：

`C:\Projects\python\word_count.py`

数据库没有保存一个文件 BLOB；但文件代码确实以文本形式存在于第 5 条消息的工具参数、第 7 条消息的 diff，以及对应事件中。

