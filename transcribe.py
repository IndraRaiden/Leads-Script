"""Transcribe un audio (de un lead) con la API de Whisper de OpenAI.

Lee la API key de OPENAI_API_KEY (env) o del primer .env del repo que la tenga.
No imprime la key. Uso:
    python transcribe.py whatsapp-validator/media/<archivo>.ogg
"""

import os
import sys
from pathlib import Path


def find_key() -> str:
    key = os.environ.get("OPENAI_API_KEY")
    if key:
        return key.strip().strip('"')
    repo = Path(__file__).resolve().parent.parent  # .../beco
    for rel in ("Core/.env", "stronghold-apps/cloudstronghold/.env.local",
                "aicore/.env", "aicore/packages/api/.env"):
        p = repo / rel
        if p.exists():
            for line in p.read_text(encoding="utf-8", errors="ignore").splitlines():
                if line.startswith("OPENAI_API_KEY="):
                    return line.split("=", 1)[1].strip().strip('"')
    raise SystemExit("No encontré OPENAI_API_KEY en env ni en los .env del repo.")


def main():
    if len(sys.argv) < 2:
        raise SystemExit("Uso: python transcribe.py <audio.ogg>")
    audio = Path(sys.argv[1])
    if not audio.exists():
        raise SystemExit(f"No existe: {audio}")

    try:
        from openai import OpenAI
    except ImportError:
        os.system(f"{sys.executable} -m pip install -q openai")
        from openai import OpenAI

    client = OpenAI(api_key=find_key())
    with audio.open("rb") as f:
        # gpt-4o-transcribe es el modelo de transcripción más reciente; whisper-1 de respaldo.
        try:
            tr = client.audio.transcriptions.create(model="gpt-4o-transcribe", file=f, language="es")
        except Exception:
            f.seek(0)
            tr = client.audio.transcriptions.create(model="whisper-1", file=f, language="es")
    print("TRANSCRIPCIÓN:")
    print(tr.text)


if __name__ == "__main__":
    main()
