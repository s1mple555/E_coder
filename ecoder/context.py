import copy
import json


def build_context(history, budget):
    """Trim at user-turn boundaries so tool_calls and tool results stay paired.

    Full records are never deleted. Oversized earlier tool results are replaced
    in the request copy only; the current turn is never compacted midway.
    """
    turns = []
    for message in history:
        if message["role"] == "user" or not turns:
            turns.append([])
        turns[-1].append(copy.deepcopy(message))
    original = len(json.dumps(turns, ensure_ascii=False))
    if original <= budget:
        return history, None
    for turn in turns[:-1]:
        for message in turn:
            if message["role"] == "tool" and len(message.get("content", "")) > 1200:
                message["content"] = message["content"][:1200] + "\n[历史工具结果已截断；完整结果在执行记录中，需要时重新读取文件]"
    removed = 0
    while len(turns) > 1 and len(json.dumps(turns, ensure_ascii=False)) > budget:
        turns.pop(0)
        removed += 1
    messages = [message for turn in turns for message in turn]
    return messages, {"before_chars": original, "after_chars": len(json.dumps(messages, ensure_ascii=False)), "removed_turns": removed}
