"""
Vision LLM — fallback 视觉感知后端。

当 DOM 不可用、本地 OCR 不可用时，把屏幕截图发给一个 vision 语言模型，
让它描述屏幕内容。这是"眼"的最后一道 fallback：不依赖本地渲染能力，
只要有网络和一个支持图片输入的模型就能"看"。

设计原则：
- provider 完全可配置（endpoint / model / key），不写死任何一家。
- 默认指向 opencode zen 网关，模型可随时换。
- 错误分层返回（401 认证 / 429 限流 / 400 不支持图片），
  让调用方知道该降级还是该重试，而不是笼统报错。

配置（环境变量，均可省略）：
  HAND_VISION_ENDPOINT  # 默认 https://opencode.ai/zen/v1
  HAND_VISION_MODEL     # 默认 mimo-v2.5-free（免费 omni 模型）
  HAND_VISION_KEY       # 默认从 opencode auth.json 读取

用法：
  from hand.perception.vision_llm import describe_screenshot
  result = describe_screenshot(image_b64="<png base64>", prompt="这个屏幕显示什么？")
  # result: {"ok": True, "text": "...", "model": "...", "error": None}
"""

import json
import os
import urllib.request

DEFAULT_ENDPOINT = "https://openrouter.ai/api/v1"
DEFAULT_MODEL = "qwen/qwen3-vl-8b-instruct"


def _default_key() -> str:
    """从 opencode auth.json 读 key（key 不写死在代码里）。

    根据 endpoint 选 provider：OpenRouter 用 openrouter key，zen 网关用 opencode key。
    """
    endpoint = os.environ.get("HAND_VISION_ENDPOINT", DEFAULT_ENDPOINT)
    preferred = ("openrouter", "opencode") if "openrouter" in endpoint else ("opencode", "openrouter")
    candidates = [
        os.path.expanduser("~/.local/share/opencode/auth.json"),
        os.path.expanduser("~/.config/opencode/auth.json"),
    ]
    for path in candidates:
        try:
            with open(path) as f:
                data = json.load(f)
            for provider in preferred:
                entry = data.get(provider, {})
                if isinstance(entry, dict) and entry.get("key"):
                    return entry["key"]
        except (OSError, json.JSONDecodeError):
            continue
    return ""


def _config():
    return {
        "endpoint": os.environ.get("HAND_VISION_ENDPOINT", DEFAULT_ENDPOINT).rstrip("/"),
        "model": os.environ.get("HAND_VISION_MODEL", DEFAULT_MODEL),
        "key": os.environ.get("HAND_VISION_KEY", _default_key()),
    }


def describe_screenshot(image_b64: str, prompt: str = None, model: str = None,
                        max_tokens: int = 400) -> dict:
    """
    把一张截图（base64 PNG）发给 vision 模型，返回对屏幕的文本描述。

    image_b64: 纯 base64 字符串（不带 data: 前缀）
    prompt:    问模型的问题，默认问"屏幕显示什么内容"
    model:     覆盖配置里的模型（临时换模型用）
    """
    if not image_b64:
        return {"ok": False, "text": None, "model": None, "error": "empty image"}

    cfg = _config()
    model = model or cfg["model"]
    if not cfg["key"]:
        return {"ok": False, "text": None, "model": model, "error": "no api key"}

    if prompt is None:
        prompt = ("描述这个屏幕截图：整体布局、主要颜色、页面在展示什么内容、"
                  "有没有明显的图片、图标或文字。用简洁的中文回答，150 字以内。")

    body = {
        "model": model,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url",
                 "image_url": {"url": f"data:image/png;base64,{image_b64}"}},
            ],
        }],
        "max_tokens": max_tokens,
    }

    url = f"{cfg['endpoint']}/chat/completions"
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {cfg['key']}",
            "Content-Type": "application/json",
            # Cloudflare 会拦 Python-urllib 的默认 UA（403 error code: 1010）
            "User-Agent": "hand-vision/1.0",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return _http_error(e, model)
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "text": None, "model": model, "error": str(e)}

    if "choices" not in data:
        return {"ok": False, "text": None, "model": model,
                "error": data.get("error", {}).get("message", "bad response")}

    choice = data["choices"][0]
    text = choice["message"].get("content", "")
    # S1 (0.9): an LLM completion can be cut at `max_tokens`. The char/token
    # total of what was *not* produced is unknowable, so we do NOT fabricate a
    # numeric truncation block — we surface the provider's own verdict
    # (`finish_reason == "length"` means the description was cut).
    return {"ok": True, "text": text, "model": data.get("model", model),
            "error": None,
            "finish_reason": choice.get("finish_reason"),
            "usage": data.get("usage")}


def _http_error(e: urllib.error.HTTPError, model: str) -> dict:
    """
    把 HTTP 错误分层，让调用方知道怎么处理。

    注意：HTTP/2 下 urllib 的 e.code 可能不可靠（实测响应头是 429、
    e.code 却是 403）。所以优先以响应体里的 error.type 字段为准，
    状态码只作为兜底。
    """
    code = e.code
    try:
        payload = json.loads(e.read().decode("utf-8"))
        err = payload.get("error", {})
        err_type = err.get("type", "")
        err_msg = err.get("message", "")
    except (json.JSONDecodeError, AttributeError):
        err_type, err_msg = "", ""

    # 以响应体的 error.type 为准（跨 provider 的通用约定）
    type_map = {
        "FreeUsageLimitError": "rate_limited",
        "CreditsError": "no_balance",
        "ModelError": "model_not_supported",
        "server_error": "server_error",
    }
    if err_type in type_map:
        kind = type_map[err_type]
        # server_error 里再细分：不支持图片输入
        if kind == "server_error" and "image input" in err_msg:
            kind = "no_image_input"
        return {"ok": False, "text": None, "model": model, "error": kind,
                "detail": err_msg[:200]}

    # 兜底：按状态码分
    if code == 401:
        kind = "auth_failed"
    elif code == 429:
        kind = "rate_limited"
    elif code == 400:
        kind = "bad_request"
    else:
        kind = f"http_{code}"

    return {"ok": False, "text": None, "model": model, "error": kind,
            "detail": err_msg[:200]}


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("usage: python -m hand.perception.vision_llm <image_b64_file> [model]")
        sys.exit(1)
    b64 = open(sys.argv[1]).read().strip()
    m = sys.argv[2] if len(sys.argv) > 2 else None
    print(json.dumps(describe_screenshot(b64, model=m), ensure_ascii=False, indent=2))
