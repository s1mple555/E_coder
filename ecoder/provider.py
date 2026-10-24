"""Chat Completions wire protocol with incremental tool-call assembly."""
import json

import httpx


class Provider:
    def __init__(self, settings):
        self.settings = settings

    async def stream(self, messages, tools):
        if not self.settings.api_key:
            raise ValueError("请先在“连接与配置”页面保存 API Key")
        buffers, text, reasoning = {}, "", ""
        payload = {"model": self.settings.model, "messages": messages, "tools": tools, "stream": True}
        async with httpx.AsyncClient(timeout=httpx.Timeout(120, connect=15), trust_env=False) as client:
            async with client.stream("POST", self.settings.base_url + "/chat/completions", headers={"Authorization": f"Bearer {self.settings.api_key}"}, json=payload) as response:
                if response.status_code >= 400:
                    # Do not echo provider response bodies: they may contain credentials.
                    raise ValueError(f"模型服务返回 HTTP {response.status_code}，请检查 API 地址、模型和密钥")
                async for line in response.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        break
                    chunk = json.loads(data)
                    if chunk.get("error"):
                        raise ValueError("模型流返回错误，请检查服务端日志")
                    if chunk.get("usage"):
                        yield {"type": "usage", **chunk["usage"]}
                    choices = chunk.get("choices", [])
                    if not choices:
                        continue
                    if choices[0].get("finish_reason") == "length":
                        raise ValueError("模型输出被截断，请缩小任务后重试")
                    delta = choices[0].get("delta", {})
                    # Step reasoning models require this field when continuing
                    # a tool turn. Preserve it for the provider, not in UI events.
                    if delta.get("reasoning_content"):
                        reasoning += delta["reasoning_content"]
                    if delta.get("content"):
                        text += delta["content"]
                        yield {"type": "text_delta", "content": delta["content"]}
                    for part in delta.get("tool_calls", []):
                        call = buffers.setdefault(part["index"], {"id": "", "type": "function", "function": {"name": "", "arguments": ""}})
                        if part.get("id"):
                            call["id"] = part["id"]
                        for key in ("name", "arguments"):
                            call["function"][key] += part.get("function", {}).get(key) or ""
                    if len(text) + len(reasoning) + sum(len(c["function"]["arguments"]) for c in buffers.values()) > 250000:
                        raise ValueError("模型单次输出超过 250 KB 限制")
        if not text and not buffers:
            raise ValueError("模型流没有返回文本或工具调用")
        message = {"role": "assistant", "content": text or None}
        if reasoning:
            message["reasoning_content"] = reasoning
        if buffers:
            message["tool_calls"] = [buffers[i] for i in sorted(buffers)]
            if any(not c["id"] or not c["function"]["name"] for c in message["tool_calls"]):
                raise ValueError("模型返回了不完整的工具调用")
        yield {"type": "response", "message": message}
