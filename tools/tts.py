"""Generate Bulgarian voice-over lines with edge-tts (runs in GitHub Actions)."""
import asyncio, json, sys
from pathlib import Path
import edge_tts

VOICE = "bg-BG-KalinaNeural"
lines = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
out = Path(sys.argv[2]); out.mkdir(parents=True, exist_ok=True)

async def main():
    for i, text in enumerate(lines, 1):
        await edge_tts.Communicate(text, VOICE, rate="+8%").save(str(out / f"line{i}.mp3"))
        print("ok", i, text)

asyncio.run(main())
