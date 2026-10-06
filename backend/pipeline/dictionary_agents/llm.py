from __future__ import annotations
import json, os
from pathlib import Path
from dotenv import load_dotenv, dotenv_values
from openai import OpenAI

def load_agent_environment():
    explicit=os.environ.get("FEEDIT_ENV_PATH")
    candidates=[Path(explicit)] if explicit else [Path(__file__).resolve().parents[3]/".env", Path(__file__).resolve().parents[2]/".env"]
    for path in candidates:
        if path.is_file():
            load_dotenv(path, override=False)
            vals=dotenv_values(path)
            for key in ("OPENAI_API_KEY","FEEDIT_DICTIONARY_AGENT_MODEL","OPENAI_MODEL"):
                if not os.environ.get(key, "").strip() and vals.get(key): os.environ[key]=vals[key]
            return str(path)
    return None

class DictionaryReviewer:
    def __init__(self, *, model=None, client=None, timeout=120, max_output_tokens=5000):
        self.env_path=load_agent_environment()
        self.model=model or os.environ.get("FEEDIT_DICTIONARY_AGENT_MODEL") or os.environ.get("OPENAI_MODEL") or "gpt-5.4-mini"
        if client is None and not os.environ.get("OPENAI_API_KEY", "").strip():
            raise ValueError(f"OPENAI_API_KEY is missing. Loaded .env: {self.env_path}")
        self.client=client or OpenAI(timeout=timeout, max_retries=2)
        self.max_output_tokens=max_output_tokens
    def review(self, *, prompt, payload, schema):
        r=self.client.responses.parse(model=self.model, input=[{"role":"system","content":prompt},{"role":"user","content":json.dumps(payload,ensure_ascii=False,default=str)}], text_format=schema, store=False, max_output_tokens=self.max_output_tokens)
        if r.status != "completed" or r.output_parsed is None: raise RuntimeError(f"dictionary review incomplete: {r.status}")
        return r.output_parsed
