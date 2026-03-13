"""
tray.py — CreatorFlow
Lanca o Streamlit em background e coloca um icone na bandeja do Windows.
"""
import sys, os, subprocess, threading, time, webbrowser

try:
    import pystray
    from PIL import Image, ImageDraw
except ImportError:
    subprocess.run([sys.executable, "-m", "pip", "install", "pystray", "pillow", "-q"])
    import pystray
    from PIL import Image, ImageDraw

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PORT     = 8501
URL      = f"http://localhost:{PORT}"

streamlit_proc = None
scheduler_proc = None
brave_proc     = None  # rastreia janela Brave

# ── Helpers ───────────────────────────────────────────────────────────────────
def _run_hidden(cmd, **kwargs):
    """Run subprocess without opening a console window on Windows."""
    if os.name == "nt":
        kwargs.setdefault("creationflags", subprocess.CREATE_NO_WINDOW)
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        kwargs.setdefault("startupinfo", si)
    return subprocess.run(cmd, **kwargs)

# ── Kill ──────────────────────────────────────────────────────────────────────
def kill_pid_tree(pid):
    """Mata PID e todos os filhos via taskkill /T (mais fiavel)."""
    if pid is None:
        return
    try:
        _run_hidden(
            ["taskkill", "/F", "/T", "/PID", str(pid)],
            capture_output=True, timeout=8
        )
    except Exception:
        pass

def kill_proc(proc):
    if proc is None:
        return
    try:
        kill_pid_tree(proc.pid)
    except Exception:
        pass
    try:
        proc.kill()
    except Exception:
        pass

def kill_port_8501():
    """Mata tudo que esteja a usar a porta 8501."""
    try:
        r = _run_hidden(
            ["cmd", "/c", "netstat -aon | findstr \":8501\""],
            capture_output=True, text=True, timeout=5
        )
        for line in r.stdout.splitlines():
            parts = line.strip().split()
            if parts:
                pid = parts[-1]
                if pid.isdigit():
                    _run_hidden(["taskkill", "/F", "/PID", pid],
                                capture_output=True, timeout=5)
    except Exception:
        pass

# ── Open external URL in Brave (app mode, separate window) ──────────────────────
def open_url_in_brave(url: str):
    """Abre um URL externo numa janela Brave limpa (não dentro da app)."""
    brave_paths = [
        os.path.expandvars(r"%LocalAppData%\BraveSoftware\Brave-Browser\Application\brave.exe"),
        r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe",
        r"C:\Program Files (x86)\BraveSoftware\Brave-Browser\Application\brave.exe",
    ]
    brave = next((p for p in brave_paths if os.path.exists(p)), None)
    if brave:
        subprocess.Popen([brave, url])
    else:
        import webbrowser
        webbrowser.open(url)

# ── Start ─────────────────────────────────────────────────────────────────────
def start_streamlit():
    global streamlit_proc
    kill_port_8501()
    time.sleep(1)
    streamlit_proc = subprocess.Popen(
        [sys.executable, "-m", "streamlit", "run", "app.py",
         "--server.port", str(PORT),
         "--server.headless", "true",
         "--browser.gatherUsageStats", "false"],
        cwd=BASE_DIR,
        creationflags=subprocess.CREATE_NO_WINDOW
    )

def start_scheduler():
    global scheduler_proc
    scheduler_proc = subprocess.Popen(
        [sys.executable, "scheduler.py"],
        cwd=BASE_DIR,
        creationflags=subprocess.CREATE_NO_WINDOW
    )

def open_browser():
    global brave_proc
    brave_paths = [
        os.path.expandvars(r"%LocalAppData%\BraveSoftware\Brave-Browser\Application\brave.exe"),
        r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe",
        r"C:\Program Files (x86)\BraveSoftware\Brave-Browser\Application\brave.exe",
    ]
    brave = next((p for p in brave_paths if os.path.exists(p)), None)
    profile_dir = os.path.join(BASE_DIR, "brave_profile")

    # Fecha janela Brave anterior se ainda estiver aberta
    if brave_proc is not None:
        try:
            if brave_proc.poll() is None:  # ainda está viva
                kill_pid_tree(brave_proc.pid)
        except Exception:
            pass
        brave_proc = None
    time.sleep(0.5)

    if brave:
        brave_proc = subprocess.Popen([brave, f"--app={URL}", "--window-size=1400,900",
                                       f"--user-data-dir={profile_dir}"])
    else:
        webbrowser.open(URL)

def wait_and_open():
    time.sleep(5)
    open_browser()

# ── Icon ──────────────────────────────────────────────────────────────────────
def make_icon():
    size = 64
    img  = Image.new("RGBA", (size, size), (10, 10, 15, 255))
    draw = ImageDraw.Draw(img)
    draw.ellipse([2, 2, size-2, size-2], fill=(26, 26, 36, 255))
    draw.rectangle([10, 14, 54, 24], fill=(255, 45, 85, 255))
    draw.rectangle([24, 14, 40, 52], fill=(0, 245, 212, 255))
    draw.rectangle([24, 14, 40, 24], fill=(255, 255, 255, 200))
    return img

# ── Actions ───────────────────────────────────────────────────────────────────
def action_open(icon, item):
    open_browser()

def action_restart(icon, item):
    global streamlit_proc
    try: icon.notify("A reiniciar...", "CreatorFlow")
    except: pass
    kill_proc(streamlit_proc)
    streamlit_proc = None
    time.sleep(2)
    threading.Thread(target=start_streamlit, daemon=True).start()
    time.sleep(5)
    open_browser()

def action_quit(icon, item):
    """Encerra TUDO. Pystray ja chama este callback numa thread propria — sem threads extra."""
    global streamlit_proc, scheduler_proc

    # 1. Esconder icone imediatamente
    try:
        icon.visible = False
    except Exception:
        pass

    # 2. Matar processos filho
    kill_proc(streamlit_proc)
    kill_proc(scheduler_proc)
    kill_proc(brave_proc)
    streamlit_proc = None
    scheduler_proc = None
    brave_proc     = None

    # 3. Libertar porta
    kill_port_8501()

    # 4. Apagar PID file
    try:
        pid_file = os.path.join(BASE_DIR, "scheduler.pid")
        if os.path.exists(pid_file):
            os.remove(pid_file)
    except Exception:
        pass

    # 5. Parar o loop do pystray (desbloqueia icon.run() na main thread)
    try:
        icon.stop()
    except Exception:
        pass

    # 6. Garantir saida mesmo que icon.stop() falhe
    os._exit(0)

# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    threading.Thread(target=start_scheduler, daemon=True).start()
    threading.Thread(target=start_streamlit, daemon=True).start()
    threading.Thread(target=wait_and_open,   daemon=True).start()

    menu = pystray.Menu(
        pystray.MenuItem("CreatorFlow", None, enabled=False),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Abrir no Brave", action_open, default=True),
        pystray.MenuItem("Reiniciar App",  action_restart),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Sair",           action_quit),
    )
    icon = pystray.Icon("CreatorFlow", make_icon(), "CreatorFlow", menu)
    icon.run()

if __name__ == "__main__":
    main()
