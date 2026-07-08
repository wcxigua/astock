from typing import Optional, Dict, Any, List
import json
import requests
from config.deepseek_config import deepseek_cfg
from utils.logger import get_logger


DEFAULT_PROMPT = """你是一个A股超短线量能交易分析师，仅依据量价数据进行独立研判。

## 研判要求
1. 解读当前量价结构：放量是否健康、量能是否可持续
2. 标记潜在风险点：放量滞涨、高位缩量、量价背离等
3. 给出最终建议：确认（量价配合良好，信号可靠）/ 排除（存在明显风险，不宜参与）/ 观望（信号不明确，需继续观察）

## 核心约束
- 仅分析量价数据，不讨论题材、消息、基本面
- 结论控制在50字以内，简明扼要
- 格式：【风险点】...【建议】确认/排除/观望"""


class DeepSeekClient:
    def __init__(self):
        self.logger = get_logger("DeepSeekAPI")
        self.api_key = deepseek_cfg.api_key
        self.api_base = deepseek_cfg.api_base
        self.model = deepseek_cfg.model
        self.max_tokens = deepseek_cfg.max_tokens
        self.temperature = deepseek_cfg.temperature
        self.timeout = deepseek_cfg.timeout
        self._ready = bool(self.api_key)
        if not self._ready:
            self.logger.warning("DeepSeek API Key 未配置，请在 .env 文件中设置 DEEPSEEK_API_KEY")

    def is_ready(self) -> bool:
        return self._ready

    def chat(self, messages: List[Dict[str, str]], **kwargs) -> Optional[Dict[str, Any]]:
        if not self._ready:
            self.logger.error("DeepSeek 未就绪：缺少 API Key")
            return None
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": kwargs.get("model", self.model),
            "messages": messages,
            "max_tokens": kwargs.get("max_tokens", self.max_tokens),
            "temperature": kwargs.get("temperature", self.temperature),
        }
        try:
            resp = requests.post(
                f"{self.api_base}/chat/completions",
                headers=headers,
                json=payload,
                timeout=self.timeout
            )
            resp.raise_for_status()
            result = resp.json()
            self.logger.info(f"DeepSeek 响应成功: token消耗 {result.get('usage', {})}")
            return result
        except Exception as e:
            self.logger.error(f"DeepSeek API 调用失败: {e}")
            return None

    def analyze_stock_volume(self, stock: Dict[str, Any]) -> Optional[str]:
        fields = {
            "代码": stock.get("代码", ""),
            "名称": stock.get("名称", ""),
            "最新价": stock.get("最新价", 0),
            "涨跌幅": stock.get("涨跌幅", 0),
            "量比": stock.get("量比", 0),
            "放量幅度": stock.get("放量幅度", 0),
            "近5日均量": stock.get("近5日均量", 0),
            "近10日均量": stock.get("近10日均量", 0),
            "信号等级": stock.get("信号等级", ""),
            "建议买入价": stock.get("建议买入价", 0),
            "目标止盈": stock.get("目标止盈", 0),
            "强制止损": stock.get("强制止损", 0),
        }
        data_str = json.dumps(fields, ensure_ascii=False, indent=2)
        messages = [
            {"role": "system", "content": DEFAULT_PROMPT},
            {"role": "user", "content": f"请研判以下个股的量价结构：\n\n{data_str}"}
        ]
        result = self.chat(messages)
        if result and "choices" in result:
            return result["choices"][0]["message"]["content"]
        return None

    def analyze_market_data(self, market_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        system_prompt = """你是一个A股超短线量能交易分析助手。
你的任务是分析提供的行情量价数据，找出量能异动、资金博弈迹象，输出分析结论。
仅分析量能数据，不给出交易建议。"""
        user_prompt = f"请分析以下A股行情量价数据，关注量能变化、资金博弈:\n\n{json.dumps(market_data, ensure_ascii=False, indent=2)}"
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]
        return self.chat(messages)

    def send_to_deepseek(self, data: Dict[str, Any], prompt_template: str = "") -> Optional[str]:
        if not prompt_template:
            prompt_template = "分析以下行情数据的量能特征:\n\n{data}"
        messages = [
            {"role": "system", "content": "你是A股超短线量能分析专家。"},
            {"role": "user", "content": prompt_template.format(data=json.dumps(data, ensure_ascii=False, indent=2))}
        ]
        result = self.chat(messages)
        if result and "choices" in result:
            return result["choices"][0]["message"]["content"]
        return None
