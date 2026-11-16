"""Diagnóstico 2: testa a geração de resposta do jeito que o app faz. Não mostra a sua chave."""
import os

import requests
from dotenv import load_dotenv

load_dotenv()
API = "https://generativelanguage.googleapis.com/v1beta"
H = {"x-goog-api-key": os.environ.get("GEMINI_API_KEY", "").strip(), "Content-Type": "application/json"}

simples = {"contents": [{"role": "user", "parts": [{"text": "Responda só: ok"}]}]}
como_app = {
    "systemInstruction": {"parts": [{"text": "Responda usando só os trechos. Cite [1]."}]},
    "contents": [{"role": "user", "parts": [{"text": "Trechos:\n[1] Home office até 2 dias por semana.\n\nPergunta: quantos dias de home office?"}]}],
    "generationConfig": {"temperature": 0.2, "maxOutputTokens": 2048},
}

for modelo in ("gemini-3.5-flash-lite", "gemini-3.1-flash-lite", "gemini-flash-lite-latest"):
    for nome, corpo in (("como o app", como_app),):
        try:
            r = requests.post(f"{API}/models/{modelo}:generateContent", headers=H, json=corpo, timeout=40)
        except requests.Timeout:
            print(f"--- {modelo} ({nome}): demorou mais de 40s (sobrecarregado)")
            continue
        print(f"--- {modelo} ({nome}): HTTP {r.status_code}")
        if r.ok:
            partes = r.json()["candidates"][0].get("content", {}).get("parts", [])
            print("   resposta:", "".join(p.get("text", "") for p in partes if not p.get("thought")).strip()[:200])
        else:
            print(r.text[:500])
