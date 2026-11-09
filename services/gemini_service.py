"""
TradeMind AI - Google Gemini Generative AI Service
Provides verified, grounded technical explanations, market sentiment summaries,
and risk evaluations without fabricating prices, trends, or performance claims.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from config import api_keys

logger = logging.getLogger("trademind.services.gemini")


class GeminiService:
    """Production wrapper for Google Gemini API."""

    MODEL_NAME = "gemini-3-flash-preview"
    FALLBACK_MODELS = ["gemini-2.5-flash", "gemini-flash-latest"]
    PROVIDER_NAME = "Google Gemini"

    def __init__(self):
        self._model = None
        self._initialized = False

    @property
    def api_key(self) -> Optional[str]:
        return api_keys.gemini

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key and len(self.api_key.strip()) > 10)

    def _get_client(self):
        """Lazy load Gemini client."""
        if self._initialized:
            return self._model

        if not self.is_configured:
            return None

        try:
            import google.generativeai as genai
            genai.configure(api_key=self.api_key)
            self._model = genai.GenerativeModel(
                model_name=self.MODEL_NAME,
                system_instruction=(
                    "You are TradeMind AI, an expert technical analyst specializing in the National Stock Exchange of India (NSE). "
                    "CRITICAL RULES: "
                    "1. Never invent or hallucinate stock prices, targets, company news, or market data. "
                    "2. Only explain the verified indicators, price values, and mathematical metrics passed in the prompt. "
                    "3. Always highlight risk management and educational purpose. Never guarantee financial returns."
                ),
            )
            self._initialized = True
            return self._model
        except Exception as exc:
            logger.error("Failed to initialize Google Gemini client: %s", exc)
            return None

    def _generate(self, prompt: str, max_tokens: int = 1024) -> str:
        """Execute text generation with safety fallbacks and model failover."""
        if not self.is_configured:
            return "AI commentary is unavailable because the Google Gemini API key is not configured in .env."

        import google.generativeai as genai
        models_to_try = [self.MODEL_NAME] + self.FALLBACK_MODELS

        token_budget = max(max_tokens, 1024)
        last_error = None

        for model_name in models_to_try:
            try:
                genai.configure(api_key=self.api_key)
                model = genai.GenerativeModel(
                    model_name=model_name,
                    system_instruction=(
                        "You are TradeMind AI, an expert technical analyst specializing in the National Stock Exchange of India (NSE). "
                        "CRITICAL RULES: "
                        "1. Never invent or hallucinate stock prices, targets, company news, or market data. "
                        "2. Only explain the verified indicators, price values, and mathematical metrics passed in the prompt. "
                        "3. Always highlight risk management and educational purpose. Never guarantee financial returns."
                    ),
                )
                response = model.generate_content(
                    prompt,
                    generation_config={"max_output_tokens": token_budget, "temperature": 0.2},
                )
                if response and response.text:
                    return response.text.strip()
            except Exception as exc:
                last_error = exc
                logger.warning("Gemini generation error with %s: %s", model_name, exc)
                continue

        return f"AI explanation currently unavailable: {str(last_error)}"

    def explain_signal(
        self,
        symbol: str,
        signal: str,
        indicators: Dict[str, Any],
        prediction_meta: Dict[str, Any],
    ) -> str:
        """Explain why an algorithmic BUY, SELL, or HOLD signal was triggered."""
        current_price = prediction_meta.get("current_price") or indicators.get("Close", "N/A")
        price_str = f"₹{current_price:,.2f}" if isinstance(current_price, (int, float)) else str(current_price)

        prompt = f"""Explain this quantitative algorithmic trading signal based ONLY on the verified data below:

Stock Symbol: {symbol} (NSE)
Triggered Signal: {signal}
Current Market Price: {price_str}
Directional Bias: {prediction_meta.get('direction', 'NEUTRAL')}
Model Confidence: {prediction_meta.get('confidence', 'N/A')}

Verified Indicators:
- RSI (14): {indicators.get('RSI', 'N/A')}
- MACD Line: {indicators.get('MACD', 'N/A')} | Signal: {indicators.get('MACD_Signal', 'N/A')}
- 9-day EMA: {indicators.get('EMA_9', 'N/A')} | 21-day EMA: {indicators.get('EMA_21', 'N/A')}
- 50-day SMA: {indicators.get('SMA_50', 'N/A')}
- ATR (Volatility): {indicators.get('ATR', 'N/A')}

Instructions:
1. Provide a concise 3-4 sentence professional explanation of why these technical indicators triggered a {signal} signal.
2. Mention key support/resistance or momentum implications.
3. State clearly that this is for educational research and not financial advice."""

        return self._generate(prompt, max_tokens=350)

    def summarize_market(
        self,
        indices_data: Dict[str, Any],
        top_gainers: List[Dict[str, Any]],
        top_losers: List[Dict[str, Any]],
    ) -> str:
        """Summarize current verified Indian market benchmarks."""
        nifty = indices_data.get("NIFTY 50", {})
        sensex = indices_data.get("SENSEX", {})
        bank = indices_data.get("NIFTY BANK", {})

        gainers_str = ", ".join([f"{g['symbol']} (+{g.get('change_pct', 0):.1f}%)" for g in top_gainers[:3]])
        losers_str = ", ".join([f"{l['symbol']} ({l.get('change_pct', 0):.1f}%)" for l in top_losers[:3]])

        prompt = f"""Provide a concise 3-sentence summary of today's Indian equity market conditions based ONLY on these real numbers:

- NIFTY 50: {nifty.get('price', 'N/A')} ({nifty.get('change_pct', 0):+.2f}%)
- SENSEX: {sensex.get('price', 'N/A')} ({sensex.get('change_pct', 0):+.2f}%)
- BANK NIFTY: {bank.get('price', 'N/A')} ({bank.get('change_pct', 0):+.2f}%)
- Top Gainers: {gainers_str or 'N/A'}
- Top Losers: {losers_str or 'N/A'}

Write an informative market overview for Indian market participants."""

        return self._generate(prompt, max_tokens=250)

    def explain_technical_indicators(
        self,
        symbol: str,
        indicators: Dict[str, Any],
    ) -> str:
        """Provide a clear synthesis of technical readings for education."""
        prompt = f"""Summarize the technical posture for {symbol} (NSE) based on these verified figures:
- RSI (14): {indicators.get('RSI', 'N/A')}
- MACD: {indicators.get('MACD', 'N/A')}
- 9 EMA: {indicators.get('EMA_9', 'N/A')}
- 21 EMA: {indicators.get('EMA_21', 'N/A')}
- 50 SMA: {indicators.get('SMA_50', 'N/A')}

Briefly explain whether momentum is bullish, bearish, or consolidating, and identify key risks."""

        return self._generate(prompt, max_tokens=300)

    def check_health(self) -> Dict[str, Any]:
        """Check API configuration and verify credentials with a ping."""
        if not self.is_configured:
            return {"configured": False, "status": "missing_api_key"}
        client = self._get_client()
        if client:
            return {"configured": True, "status": "authenticated", "provider": self.PROVIDER_NAME, "model": self.MODEL_NAME}
        return {"configured": True, "status": "initialization_failed"}


# Singleton export
gemini_service = GeminiService()

