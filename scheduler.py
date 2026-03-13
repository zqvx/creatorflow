"""
scheduler.py — TikTok Scheduler Daemon
Verifica a queue.json periodicamente e publica os vídeos no TikTok na hora certa.
Suporta Login Kit OAuth: renova automaticamente o access_token antes que expire.
"""

import json
import os
import sys
import time
import logging
import subprocess
import requests
from datetime import datetime, timedelta
from pathlib import Path

# TikTok Login Kit OAuth helper (same directory)
try:
    import oauth as tk_oauth
    OAUTH_AVAILABLE = True
except ImportError:
    OAUTH_AVAILABLE = False

# ─── Paths ─────────────────────────────────────────────────────────────────────
BASE_DIR    = Path(__file__).parent
QUEUE_FILE  = BASE_DIR / "queue.json"
CONFIG_FILE = BASE_DIR / "config.json"
LOG_FILE    = BASE_DIR / "scheduler.log"
PID_FILE    = BASE_DIR / "scheduler.pid"
VIDEOS_DIR  = BASE_DIR / "videos"
POSTED_DIR  = BASE_DIR / "postados"
POSTED_DIR.mkdir(exist_ok=True)
MAX_VIDEO_MB = 500
ALLOWED_VIDEO_EXTS = (".mp4", ".mov", ".avi", ".webm")

# ─── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(sys.stdout)
    ]
)
log = logging.getLogger("TikTokScheduler")

# ─── Queue helpers ──────────────────────────────────────────────────────────────
def load_queue() -> list:
    if not QUEUE_FILE.exists():
        return []
    try:
        with open(QUEUE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        log.error(f"Erro ao ler queue: {e}")
        return []

def save_queue(queue: list):
    try:
        with open(QUEUE_FILE, "w", encoding="utf-8") as f:
            json.dump(queue, f, indent=2, ensure_ascii=False)
    except Exception as e:
        log.error(f"Erro ao guardar queue: {e}")

def load_config() -> dict:
    if not CONFIG_FILE.exists():
        return {}
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_config(cfg: dict):
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2, ensure_ascii=False)
    except Exception as e:
        log.error(f"Erro ao guardar config: {e}")


def validate_video_path(video_path: str) -> tuple:
    """Returns (ok, error_message)."""
    if not video_path:
        return False, "Caminho de video vazio"
    if not os.path.exists(video_path):
        return False, f"Ficheiro nao encontrado: {video_path}"
    if not os.path.isfile(video_path):
        return False, f"Caminho nao e ficheiro: {video_path}"
    if not video_path.lower().endswith(ALLOWED_VIDEO_EXTS):
        return False, "Formato invalido (usa MP4, MOV, AVI ou WEBM)"
    try:
        size = os.path.getsize(video_path)
    except Exception:
        return False, "Nao foi possivel ler o tamanho do ficheiro"
    if size <= 0:
        return False, "Ficheiro vazio (0 bytes)"
    if size > (MAX_VIDEO_MB * 1024 * 1024):
        return False, f"Ficheiro demasiado grande (> {MAX_VIDEO_MB}MB)"
    return True, ""


def get_video_duration_sec(video_path: str) -> tuple:
    """Returns (duration_sec or None, error_message or ''). Uses ffprobe if available."""
    if not video_path or not os.path.exists(video_path):
        return None, "Ficheiro nao encontrado"
    try:
        cmd = ["ffprobe", "-v", "error", "-show_entries", "format=duration",
               "-of", "default=noprint_wrappers=1:nokey=1", video_path]
        run_kwargs = {"capture_output": True, "text": True, "timeout": 10}
        if os.name == "nt":
            run_kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
            si = subprocess.STARTUPINFO()
            si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            run_kwargs["startupinfo"] = si
        res = subprocess.run(cmd, **run_kwargs)
        if res.returncode != 0:
            return None, (res.stderr or res.stdout or "ffprobe falhou")[:120]
        val = (res.stdout or "").strip()
        if not val:
            return None, "Duracao nao encontrada"
        return float(val), ""
    except FileNotFoundError:
        return None, "ffprobe nao encontrado (instala ffmpeg/ffprobe)"
    except Exception as e:
        return None, str(e)


def creator_can_post(creator_data: dict) -> bool:
    for key in ("can_post", "can_publish", "can_post_more", "can_make_more_posts"):
        if key in creator_data:
            return bool(creator_data.get(key))
    return True


# ─── Token auto-refresh ─────────────────────────────────────────────────────────
def ensure_valid_token(config: dict) -> dict:
    """
    If the access_token is about to expire and we have a refresh_token,
    automatically renew it via TikTok OAuth and persist to config.json.
    Returns the (possibly updated) config dict.
    """
    if not OAUTH_AVAILABLE:
        return config

    access_token  = config.get("access_token", "")
    refresh_token = config.get("refresh_token", "")
    client_key    = config.get("client_key", "")
    client_secret = config.get("client_secret", "")

    if not access_token:
        return config  # no token at all — simulation mode

    # Check if token is still valid (with 5 min buffer)
    if tk_oauth.is_token_valid(config, buffer_seconds=300):
        return config  # still good

    if not (refresh_token and client_key and client_secret):
        log.warning("⚠️ Access token expirando mas sem refresh_token/credenciais para renovar.")
        return config

    if not tk_oauth.is_refresh_token_valid(config):
        log.error("❌ Refresh token expirado — utilizador tem de fazer login novamente em 🔐 Conta TikTok")
        return config

    log.info("🔄 Access token expirando — a renovar automaticamente...")
    result = tk_oauth.refresh_access_token(client_key, client_secret, refresh_token)
    if result.get("error"):
        log.error(f"❌ Falha ao renovar token: {result.get('error_description', result['error'])}")
        return config

    # Persist refreshed tokens
    import time as _time
    config["access_token"] = result["access_token"]
    if result.get("refresh_token"):
        config["refresh_token"] = result["refresh_token"]
    config["access_token_expires_at"]  = result.get("access_token_expires_at",
                                           int(_time.time()) + result.get("expires_in", 86400))
    config["refresh_token_expires_at"] = result.get("refresh_token_expires_at",
                                           config.get("refresh_token_expires_at", 0))
    save_config(config)
    log.info("✅ Token renovado com sucesso!")
    return config

# ─── TikTok API ─────────────────────────────────────────────────────────────────
class TikTokUploader:
    """
    Integração com TikTok Content Posting API v2
    Docs: https://developers.tiktok.com/doc/content-posting-api-get-started
    """

    BASE_URL   = "https://open.tiktokapis.com/v2"
    CHUNK_SIZE = 10 * 1024 * 1024  # 10 MB por chunk
    MIN_CHUNK  = 5 * 1024 * 1024   # 5 MB minimo
    MAX_CHUNK  = 64 * 1024 * 1024  # 64 MB maximo

    def __init__(self, access_token: str, open_id: str):
        self.access_token = access_token
        self.open_id      = open_id
        self.headers      = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type":  "application/json; charset=UTF-8"
        }

    def query_creator_info(self) -> dict:
        """OBRIGATÓRIO pela API antes de qualquer post."""
        url  = f"{self.BASE_URL}/post/publish/creator_info/query/"
        resp = requests.post(url, headers=self.headers, json={}, timeout=15)
        resp.raise_for_status()
        return resp.json()

    def init_upload(self, video_path: str, post_info: dict) -> tuple:
        """Returns (api_response_dict, chunk_size_bytes) so the caller uses the exact same value."""
        import math
        file_size    = os.path.getsize(video_path)
        MAX_CHUNK    = 64 * 1024 * 1024  # 64MB máximo por chunk
        # TikTok valida o total_chunk_count com base no chunk_size enviado.
        total_chunks = max(1, math.ceil(file_size / MAX_CHUNK))
        chunk_size   = math.ceil(file_size / total_chunks)  # divisão igual
        if file_size <= self.MIN_CHUNK:
            chunk_size   = file_size
            total_chunks = 1
        else:
            chunk_size   = min(max(self.CHUNK_SIZE, self.MIN_CHUNK), self.MAX_CHUNK, file_size)
            total_chunks = max(1, math.ceil(file_size / chunk_size))
        # TikTok exige total_chunk_count consistente com chunk_size (divisao exata).
        min_total = max(1, math.ceil(file_size / self.MAX_CHUNK))
        max_total = max(1, file_size // self.MIN_CHUNK)
        total_chunks = None
        for total in range(min_total, max_total + 1):
            if file_size % total == 0:
                total_chunks = total
                break
        if not total_chunks:
            total_chunks = min_total
            chunk_size = math.ceil(file_size / total_chunks)
            log.warning("Chunking nao e divisivel; a tentar mesmo assim.")
        else:
            chunk_size = file_size // total_chunks
        url     = f"{self.BASE_URL}/post/publish/video/init/"
        payload = {
            "post_info": post_info,
            "source_info": {
                "source":            "FILE_UPLOAD",
                "video_size":        file_size,
                "chunk_size":        chunk_size,
                "total_chunk_count": total_chunks
            }
        }
        log.info(f"Init upload: {file_size} bytes, {total_chunks} chunk(s) de {chunk_size//1024//1024}MB cada (chunk_size={chunk_size})")
        resp = requests.post(url, headers=self.headers, json=payload, timeout=30)
        resp.raise_for_status()
        return resp.json(), chunk_size  # ← devolve chunk_size para evitar recalcular

    def upload_video_chunks(self, upload_url: str, video_path: str, chunk_size: int) -> bool:
        """Upload em chunks iguais de chunk_size bytes."""
        import math
        file_size    = os.path.getsize(video_path)
        total_chunks = math.ceil(file_size / chunk_size)
        with open(video_path, "rb") as f:
            for chunk_n in range(total_chunks):
                offset = chunk_n * chunk_size
                # último chunk pode ser menor
                actual_size = min(chunk_size, file_size - offset)
                chunk = f.read(actual_size)
                end = offset + len(chunk) - 1
                headers = {
                    "Content-Type":   "video/mp4",
                    "Content-Range":  f"bytes {offset}-{end}/{file_size}",
                    "Content-Length": str(len(chunk))
                }
                log.info(f"Chunk {chunk_n+1}/{total_chunks}: bytes {offset}-{end} ({len(chunk)//1024//1024}MB)")
                resp = requests.put(upload_url, headers=headers, data=chunk, timeout=600)
                log.info(f"  → HTTP {resp.status_code}")
                if resp.status_code not in (200, 201, 204, 206):
                    log.error(f"Chunk {chunk_n+1} falhou: HTTP {resp.status_code} — {resp.text[:200]}")
                    return False
        return True

    def check_post_status(self, publish_id: str) -> dict:
        """Verifica o estado do post após upload."""
        url  = f"{self.BASE_URL}/post/publish/status/fetch/"
        resp = requests.post(url, headers=self.headers,
                             json={"publish_id": publish_id}, timeout=15)
        resp.raise_for_status()
        return resp.json()

    def upload_video(self, video_path: str, caption: str, post_meta=None) -> tuple:
        """
        Processo completo: creator_info → init → upload chunks → status check
        Retorna (sucesso, mensagem)
        """
        post_meta = post_meta or {}
        if not (self.access_token and self.open_id):
            return False, "Credenciais TikTok não configuradas"
        ok, err_msg = validate_video_path(video_path)
        if not ok:
            return False, err_msg
        if not os.path.exists(video_path):
            return False, f"Ficheiro não encontrado: {video_path}"

        try:
            # 1. Query Creator Info (obrigatório pela API)
            log.info("A verificar info do criador...")
            creator_resp = self.query_creator_info()
            creator_err  = creator_resp.get("error", {})
            if creator_err.get("code") != "ok":
                return False, f"Erro creator_info: {creator_err.get('message', 'Erro desconhecido')}"

            creator_data    = creator_resp.get("data", {})
            if not creator_can_post(creator_data):
                return False, "Criador nao pode publicar agora (limite atingido). Tenta mais tarde."

            privacy_options = creator_data.get("privacy_level_options", ["PUBLIC_TO_EVERYONE", "SELF_ONLY"])
            log.info(f"Privacy options disponíveis: {privacy_options}")
            requested_privacy = post_meta.get("privacy_level")
            if requested_privacy:
                if requested_privacy not in privacy_options:
                    return False, f"Privacidade invalida: {requested_privacy}"
                privacy_level = requested_privacy
            else:
                # Apps não auditadas pelo TikTok só podem publicar como SELF_ONLY (privado)
                # Após aprovação da auditoria, mudar para PUBLIC_TO_EVERYONE automaticamente
                config_loaded = load_config()
                audited = config_loaded.get("app_audited", False)
                if audited and "PUBLIC_TO_EVERYONE" in privacy_options:
                    privacy_level = "PUBLIC_TO_EVERYONE"
                else:
                    privacy_level = "SELF_ONLY"

            if post_meta.get("commercial_branded_content") and privacy_level == "SELF_ONLY":
                return False, "Branded content nao pode ser privado."
            if post_meta.get("commercial_toggle") and not (post_meta.get("commercial_your_brand") or post_meta.get("commercial_branded_content")):
                return False, "Declaracao de conteudo comercial incompleta."

            # Duracao max do TikTok (creator_info)
            max_dur = creator_data.get("max_video_post_duration_sec")
            if max_dur:
                dsec, derr = get_video_duration_sec(video_path)
                if dsec is None:
                    return False, f"Nao foi possivel validar duracao: {derr}"
                if dsec > max_dur:
                    return False, f"Duracao {int(dsec)}s excede max {int(max_dur)}s"

            # Interacoes
            allow_comment = bool(post_meta.get("allow_comment", True))
            allow_duet = bool(post_meta.get("allow_duet", True))
            allow_stitch = bool(post_meta.get("allow_stitch", True))
            if creator_data.get("comment_disabled") or creator_data.get("comment_disabled_in_app"):
                allow_comment = False
            if creator_data.get("duet_disabled") or creator_data.get("duet_disabled_in_app"):
                allow_duet = False
            if creator_data.get("stitch_disabled") or creator_data.get("stitch_disabled_in_app"):
                allow_stitch = False

            post_info = {
                "title": caption[:150],
                "privacy_level": privacy_level,
                "disable_duet": not allow_duet,
                "disable_comment": not allow_comment,
                "disable_stitch": not allow_stitch,
                "video_cover_timestamp_ms": 1000
            }
            log.info(f"Criador OK — privacy: {privacy_level} (auditada: {load_config().get('app_audited', False)})")

            # 2. Inicializar upload
            log.info(f"A inicializar upload: {os.path.basename(video_path)}")
            init_resp, chunk_size = self.init_upload(video_path, post_info)
            init_err  = init_resp.get("error", {})
            if init_err.get("code") != "ok":
                return False, f"Erro ao iniciar upload: {init_err.get('message', 'Erro desconhecido')}"

            upload_url = init_resp["data"]["upload_url"]
            publish_id = init_resp["data"]["publish_id"]

            # 3. Upload em chunks — usa o MESMO chunk_size do init para evitar HTTP 416
            import math
            file_size    = os.path.getsize(video_path)
            total_chunks = math.ceil(file_size / chunk_size)
            log.info(f"A fazer upload: {total_chunks} chunk(s) de {chunk_size//1024//1024}MB cada")
            if not self.upload_video_chunks(upload_url, video_path, chunk_size):
                return False, "Falha no upload do ficheiro"

            # 4. Verificar status (aguarda processamento assíncrono)
            log.info("A verificar status do post...")
            final_status = ""
            for attempt in range(20):  # até 60 segundos
                time.sleep(3)
                status_resp = self.check_post_status(publish_id)
                status_data = status_resp.get("data", {})
                final_status = status_data.get("status", "")
                log.info(f"   Status ({attempt+1}/20): {final_status}")
                if final_status in ("PUBLISH_COMPLETE", "SUCCESS"):
                    break
                if final_status in ("FAILED", "PUBLISH_FAILED"):
                    fail_reason = status_data.get("fail_reason", "Desconhecido")
                    return False, f"Publicação falhou: {fail_reason}"
                # PROCESSING_UPLOAD / PROCESSING_DOWNLOAD — continua a aguardar

            if final_status not in ("PUBLISH_COMPLETE", "SUCCESS"):
                log.warning(f"⚠️ TikTok ainda a processar após 60s (status: {final_status}) — a considerar como publicado")

            log.info(f"Upload concluído! publish_id: {publish_id}")
            return True, publish_id

        except requests.exceptions.ConnectionError:
            return False, "Sem ligação à internet"
        except requests.exceptions.Timeout:
            return False, "Timeout na ligação ao TikTok"
        except requests.exceptions.HTTPError as e:
            try:
                body = e.response.json()
                err  = body.get("error", {})
                msg  = err.get("message", e.response.text[:200])
                code = err.get("code", e.response.status_code)
                return False, f"Erro HTTP {e.response.status_code}: {code} — {msg}"
            except Exception:
                return False, f"Erro HTTP: {e.response.status_code} — {e.response.text[:200]}"
        except Exception as e:
            return False, f"Erro inesperado: {str(e)}"

# ─── Simulate mode ────────────────────────────────────────────────────────────
def simulate_post(post: dict) -> tuple:
    video_name = os.path.basename(post.get("video_path", ""))
    log.info(f"[SIMULAÇÃO] Publicar: {video_name}")
    log.info(f"[SIMULAÇÃO] Legenda: {post.get('caption','')[:60]}")
    log.info(f"[SIMULAÇÃO] Hashtags: {post.get('hashtags','')}")
    time.sleep(1)
    return True, "simulated_post_id_12345"


# ─── Retry schedule ───────────────────────────────────────────────────────────
RETRY_DELAYS = [5, 15, 60]  # minutes — escalating backoff

def get_retry_delay(post: dict) -> int:
    retries = post.get("retry_count", 0)
    idx = min(retries, len(RETRY_DELAYS) - 1)
    return RETRY_DELAYS[idx]


# ─── Core scheduler loop ────────────────────────────────────────────────────────
def recover_stuck_pending(queue: list) -> bool:
    """
    Recupera posts presos em 'pending' (scheduler reiniciado a meio de um upload).
    Repõe para 'scheduled' com a hora actual para serem re-processados imediatamente.
    Retorna True se houve alguma alteração.
    """
    changed = False
    for post in queue:
        if post.get("status") == "pending":
            log.warning(f"⚠️ Post {post.get('id')} estava em 'pending' (upload interrompido) — a repor para 'scheduled'")
            post["status"] = "scheduled"
            post["scheduled_at"] = datetime.now().isoformat()
            changed = True
    return changed


def build_caption(post: dict) -> str:
    caption_full = post.get("caption", "")
    if post.get("hashtags"):
        caption_full += " " + post["hashtags"]
    return caption_full.strip()


def execute_post(post: dict, config: dict, now: datetime, retry_on_fail: bool) -> tuple:
    access_token = config.get("access_token", "")
    open_id = config.get("open_id", "")
    simulate_mode = not (access_token and open_id)

    if not post.get("user_consent", False):
        return False, "Consentimento ausente"

    ok, err_msg = validate_video_path(post.get("video_path", ""))
    if not ok:
        return False, err_msg

    if simulate_mode:
        success, result = simulate_post(post)
    else:
        uploader = TikTokUploader(access_token, open_id)
        caption_full = build_caption(post)
        post_meta = {
            "privacy_level": post.get("privacy_level"),
            "allow_comment": post.get("allow_comment", True),
            "allow_duet": post.get("allow_duet", True),
            "allow_stitch": post.get("allow_stitch", True),
            "commercial_toggle": post.get("commercial_toggle", False),
            "commercial_your_brand": post.get("commercial_your_brand", False),
            "commercial_branded_content": post.get("commercial_branded_content", False)
        }
        success, result = uploader.upload_video(post["video_path"], caption_full, post_meta=post_meta)

    if success:
        post["status"] = "posted"
        post["posted_at"] = datetime.now().isoformat()
        post["publish_id"] = result
        post.pop("retry_count", None)
        log.info(f"âœ… Post {post['id']} publicado! (publish_id: {result})")

        # Mover video para pasta postados/
        try:
            src = Path(post["video_path"])
            if src.exists():
                dst = POSTED_DIR / src.name
                # Se ja existe um ficheiro com o mesmo nome, adiciona sufixo
                if dst.exists():
                    stem = src.stem
                    suffix = src.suffix
                    dst = POSTED_DIR / f"{stem}_{post['id']}{suffix}"
                src.rename(dst)
                post["video_path"] = str(dst)
                log.info(f"ðŸ“ Video movido para postados/: {dst.name}")
        except Exception as e:
            log.warning(f"âš ï¸ Nao foi possivel mover video: {e}")
    else:
        retry_count = post.get("retry_count", 0)
        max_retries = 3

        if retry_on_fail and retry_count < max_retries:
            delay_min = get_retry_delay(post)
            post["status"] = "scheduled"
            post["scheduled_at"] = (now + timedelta(minutes=delay_min)).isoformat()
            post["retry_count"] = retry_count + 1
            post["error"] = result
            log.warning(f"ðŸ”„ Post {post['id']} falhou (tentativa {retry_count+1}/{max_retries}): {result}")
            log.info(f"   PrÃ³xima tentativa em {delay_min} min")
        else:
            post["status"] = "failed"
            post["error"] = result
            log.error(f"âŒ Post {post['id']} falhou definitivamente: {result}")

    return success, result


def process_queue(config: dict):
    queue = load_queue()
    now = datetime.now()

    # Recuperar posts presos em "pending" por crash/reinício do scheduler
    if recover_stuck_pending(queue):
        save_queue(queue)

    # Auto-refresh token if expiring soon (Login Kit OAuth)
    config = ensure_valid_token(config)

    access_token = config.get("access_token", "")
    open_id = config.get("open_id", "")
    simulate_mode = not (access_token and open_id)
    retry_on_fail = config.get("retry_failed", True)

    if simulate_mode:
        log.debug("Modo simulação ativo (sem credenciais TikTok)")

    updated = False

    for post in queue:
        if post.get("status") != "scheduled":
            continue

        try:
            scheduled_at = datetime.fromisoformat(post["scheduled_at"])
        except (KeyError, ValueError):
            log.warning(f"Post {post.get('id')}: data inválida, a ignorar")
            continue

        if now < scheduled_at:
            continue

        log.info(f"⏰ Post {post['id']} — agendado para {scheduled_at.strftime('%H:%M %d/%m')}")
        post["status"] = "pending"
        updated = True

        execute_post(post, config, now, retry_on_fail)
        continue

        if simulate_mode:
            success, result = simulate_post(post)
        else:
            uploader = TikTokUploader(access_token, open_id)
            caption_full = post.get("caption", "")
            if post.get("hashtags"):
                caption_full += " " + post["hashtags"]
            success, result = uploader.upload_video(post["video_path"], caption_full)

        if success:
            post["status"] = "posted"
            post["posted_at"] = datetime.now().isoformat()
            post["publish_id"] = result
            post.pop("retry_count", None)
            log.info(f"✅ Post {post['id']} publicado! (publish_id: {result})")

            # Mover video para pasta postados/
            try:
                src = Path(post["video_path"])
                if src.exists():
                    dst = POSTED_DIR / src.name
                    # Se ja existe um ficheiro com o mesmo nome, adiciona sufixo
                    if dst.exists():
                        stem = src.stem
                        suffix = src.suffix
                        dst = POSTED_DIR / f"{stem}_{post['id']}{suffix}"
                    src.rename(dst)
                    post["video_path"] = str(dst)
                    log.info(f"📁 Video movido para postados/: {dst.name}")
            except Exception as e:
                log.warning(f"⚠️ Nao foi possivel mover video: {e}")
        else:
            retry_count = post.get("retry_count", 0)
            max_retries = 3

            if retry_on_fail and retry_count < max_retries:
                delay_min = get_retry_delay(post)
                post["status"] = "scheduled"
                post["scheduled_at"] = (now + timedelta(minutes=delay_min)).isoformat()
                post["retry_count"] = retry_count + 1
                post["error"] = result
                log.warning(f"🔄 Post {post['id']} falhou (tentativa {retry_count+1}/{max_retries}): {result}")
                log.info(f"   Próxima tentativa em {delay_min} min")
            else:
                post["status"] = "failed"
                post["error"] = result
                log.error(f"❌ Post {post['id']} falhou definitivamente: {result}")

    if updated:
        save_queue(queue)

    return updated


def post_now(post_id: str) -> tuple:
    """Forca a publicacao imediata de um post especifico."""
    config = load_config()
    config = ensure_valid_token(config)
    queue = load_queue()
    post = next((p for p in queue if p.get("id") == post_id), None)
    if not post:
        return False, "Post nao encontrado"
    if post.get("status") == "posted":
        return False, "Post ja publicado"
    if post.get("status") == "pending":
        return False, "Post ja em envio"

    now = datetime.now()
    post["status"] = "pending"
    post["scheduled_at"] = now.isoformat()
    post["error"] = None
    post["retry_count"] = 0
    save_queue(queue)

    retry_on_fail = config.get("retry_failed", True)
    success, result = execute_post(post, config, now, retry_on_fail)
    save_queue(queue)
    return success, result


def run_scheduler(interval: int = 30):
    with open(PID_FILE, "w") as f:
        f.write(str(os.getpid()))

    log.info("=" * 60)
    log.info("🎬 TikTok Scheduler iniciado!")
    log.info(f"📁 Queue: {QUEUE_FILE}")
    log.info(f"⏱️  Intervalo: {interval}s")
    log.info("=" * 60)

    try:
        while True:
            config = load_config()  # Reload config each cycle to pick up changes
            interval = config.get("check_interval", 30)

            queue = load_queue()
            pending = [p for p in queue if p.get("status") == "scheduled"]

            if pending:
                log.info(f"📋 Posts na fila: {len(pending)}")
                process_queue(config)
            else:
                log.debug("Fila vazia, a aguardar...")

            time.sleep(interval)

    except KeyboardInterrupt:
        log.info("⏹️  Scheduler parado pelo utilizador")
    finally:
        if PID_FILE.exists():
            PID_FILE.unlink()
        log.info("👋 Scheduler terminado")


if __name__ == "__main__":
    config = load_config()
    interval = config.get("check_interval", 30)
    run_scheduler(interval)
