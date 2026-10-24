"""Native folder selection runs in a short-lived process, separate from FastAPI."""
import asyncio
import json
import os
import sys
from pathlib import Path


async def pick_folder():
    process = await asyncio.create_subprocess_exec(
        sys.executable, '-m', 'ecoder.folder_picker',
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        cwd=Path(__file__).resolve().parent.parent,
        creationflags=0x08000000 if os.name=='nt' else 0,
    )
    try:
        output, _ = await asyncio.wait_for(process.communicate(), timeout=180)
        if process.returncode:
            raise ValueError("无法打开本机目录选择器，请直接粘贴文件夹路径")
        return json.loads(output.decode('utf-8'))['path']
    finally:
        if process.returncode is None:
            process.kill()
            await process.wait()


if __name__=='__main__':
    import tkinter as tk
    from tkinter import filedialog
    window=tk.Tk()
    window.withdraw()
    window.attributes('-topmost',True)
    try:
        path=filedialog.askdirectory(parent=window,title='选择 E_coder 工作文件夹',mustexist=True)
        sys.stdout.reconfigure(encoding='utf-8')
        print(json.dumps({'path':path},ensure_ascii=False))
    finally:
        window.destroy()
