import streamlit as st
import streamlit.components.v1 as components
import json, os, uuid, subprocess, sys, time, secrets
import scheduler as tk_scheduler
from datetime import datetime, timedelta

# TikTok Login Kit OAuth module (same directory)
try:
    import oauth as tk_oauth
    OAUTH_AVAILABLE = True
except ImportError:
    OAUTH_AVAILABLE = False

st.set_page_config(page_title="CreatorFlow", page_icon="🎬",
                   layout="wide", initial_sidebar_state="expanded")

BASE_DIR    = os.path.dirname(os.path.abspath(__file__))
QUEUE_FILE  = os.path.join(BASE_DIR, "queue.json")
VIDEOS_DIR  = os.path.join(BASE_DIR, "videos")
CONFIG_FILE         = os.path.join(BASE_DIR, "config.json")
OAUTH_PENDING_FILE  = os.path.join(BASE_DIR, "oauth_pending.json")  # persiste state/verifier entre sessões
os.makedirs(VIDEOS_DIR, exist_ok=True)

# OAuth redirect URI — tem de estar EXATAMENTE igual no TikTok Developer Portal
# developers.tiktok.com → App → Edit → Redirect URIs → adiciona: http://localhost:8501/
OAUTH_REDIRECT_URI = "http://localhost:8501/"

MAX_VIDEO_MB = 500  # TikTok limit

BEST_TIMES = [
    {"hour":20,"minute": 0,"score":95,"label":"20:00","why":"Prime Time 🏆"},
    {"hour":17,"minute": 0,"score":92,"label":"17:00","why":"Saida escola ⚡"},
    {"hour":22,"minute":30,"score":83,"label":"22:30","why":"Noite 🌙"},
    {"hour": 7,"minute":30,"score":81,"label":"07:30","why":"Commute 🌅"},
    {"hour":12,"minute":15,"score":76,"label":"12:15","why":"Almoco ☀️"},
]
HOUR_OPTIONS = ["07:00","07:30","08:00","09:00","10:00","11:00","12:00","12:15",
                "13:00","14:00","15:00","16:00","17:00","18:00","19:00",
                "20:00","21:00","22:00","22:30","23:00","23:30"]

PRIVACY_LABELS = {
    "PUBLIC_TO_EVERYONE": "Publico (Todos)",
    "MUTUAL_FOLLOW_FRIENDS": "Amigos (mutuos)",
    "FOLLOWER_OF_CREATOR": "Seguidores",
    "SELF_ONLY": "Privado (so eu)"
}

# ── CSS ──────────────────────────────────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@300;400;500;600;700&family=Syne:wght@700;800&display=swap');
:root{--bg:#0a0a0f;--card:#111118;--hover:#16161f;--border:#1e1e2e;
      --pink:#ff2d55;--cyan:#00f5d4;--purple:#7c3aed;--text:#f0f0f8;--muted:#6b7280;
      --grad:linear-gradient(135deg,#ff2d55 0%,#7c3aed 50%,#00f5d4 100%);}
html,body,[class*="css"]{font-family:'Space Grotesk',sans-serif;color:var(--text);}
.stApp{background:var(--bg);background-image:
  radial-gradient(ellipse at 10% 10%,rgba(124,58,237,.07) 0%,transparent 60%),
  radial-gradient(ellipse at 90% 90%,rgba(255,45,85,.05) 0%,transparent 60%);}
[data-testid="stSidebar"]{background:var(--card)!important;border-right:1px solid var(--border);}
.stButton>button{background:var(--grad)!important;color:white!important;border:none!important;
  border-radius:10px!important;font-family:'Space Grotesk',sans-serif!important;
  font-weight:600!important;transition:all .3s!important;}
.stButton>button:hover{transform:translateY(-2px)!important;box-shadow:0 8px 25px rgba(255,45,85,.35)!important;}
.stTextInput>div>div>input,.stTextArea>div>div>textarea{background:var(--hover)!important;
  border:1px solid var(--border)!important;border-radius:10px!important;color:var(--text)!important;}
.stTextInput label,.stTextArea label,.stSelectbox label,.stDateInput label,
.stFileUploader label,.stMultiSelect label,.stTimeInput label{
  color:var(--muted)!important;font-size:.78rem!important;font-weight:500!important;
  text-transform:uppercase!important;letter-spacing:1px!important;}
[data-testid="stFileUploader"]{background:var(--hover)!important;
  border:2px dashed var(--border)!important;border-radius:14px!important;}
[data-testid="stFileUploader"]:hover{border-color:var(--pink)!important;}
.stTabs [data-baseweb="tab-list"]{background:var(--card)!important;border-radius:12px!important;
  padding:4px!important;gap:4px!important;border:1px solid var(--border)!important;}
.stTabs [data-baseweb="tab"]{background:transparent!important;color:var(--muted)!important;border-radius:8px!important;}
.stTabs [aria-selected="true"]{background:var(--grad)!important;color:white!important;}
.stTabs [data-baseweb="tab-panel"]{padding-top:1.5rem!important;}
[data-baseweb="select"]>div{background:var(--hover)!important;border-color:var(--border)!important;}
hr{border-color:var(--border)!important;}
::-webkit-scrollbar{width:5px}::-webkit-scrollbar-track{background:var(--bg)}
::-webkit-scrollbar-thumb{background:var(--border);border-radius:3px}
.pt{font-family:'Syne',sans-serif;font-size:2rem;font-weight:800;
  background:var(--grad);-webkit-background-clip:text;-webkit-text-fill-color:transparent;
  margin-bottom:.15rem;line-height:1.2;}
.ps{color:var(--muted);font-size:.88rem;margin-bottom:1.8rem;}
.sh{font-family:'Syne',sans-serif;font-size:1rem;font-weight:700;
  color:var(--text);margin-bottom:.8rem;}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.4}}
.stProgress > div > div{background:var(--grad)!important;}
</style>""", unsafe_allow_html=True)

# ── Helpers ──────────────────────────────────────────────────────────────────
def load_queue() -> list:
    if not os.path.exists(QUEUE_FILE): return []
    try:
        with open(QUEUE_FILE,"r",encoding="utf-8") as f: return json.load(f)
    except: return []

def save_queue(q: list):
    with open(QUEUE_FILE,"w",encoding="utf-8") as f:
        json.dump(q, f, indent=2, ensure_ascii=False)

def load_config() -> dict:
    if not os.path.exists(CONFIG_FILE): return {}
    try:
        with open(CONFIG_FILE) as f: return json.load(f)
    except: return {}

def save_config(c: dict):
    with open(CONFIG_FILE,"w") as f: json.dump(c, f, indent=2)

def add_post(video_path, caption, hashtags, scheduled_dt, meta=None) -> dict:
    post = {
        "id": str(uuid.uuid4())[:8],
        "video_path": video_path,
        "caption": caption,
        "hashtags": hashtags,
        "scheduled_at": scheduled_dt,
        "status": "scheduled",
        "created_at": datetime.now().isoformat(),
        "posted_at": None,
        "error": None
    }
    if meta:
        post.update(meta)
    q = load_queue(); q.append(post); save_queue(q)
    return post

def taken_days_from_queue() -> set:
    taken = set()
    for p in load_queue():
        if p["status"] == "scheduled":
            try: taken.add(datetime.fromisoformat(p["scheduled_at"]).date())
            except: pass
    return taken

def suggest_dates(n: int, start=None) -> list:
    taken = taken_days_from_queue()
    start = start or (datetime.now().date() + timedelta(days=1))
    result, used, d = [], set(), start
    while len(result) < n and d < start + timedelta(days=180):
        if d not in taken and d not in used:
            result.append(d); used.add(d)
        d += timedelta(days=1)
    return result

def hour_str_to_time(s: str):
    import datetime as dtm
    h, m = int(s.split(":")[0]), int(s.split(":")[1])
    return dtm.time(h, m)

def validate_video(f) -> tuple:
    """Returns (ok, error_message)"""
    if f is None: return False, "Nenhum ficheiro selecionado"
    size_mb = len(f.getbuffer()) / (1024 * 1024)
    if size_mb > MAX_VIDEO_MB:
        return False, f"Ficheiro demasiado grande ({size_mb:.0f}MB). Limite: {MAX_VIDEO_MB}MB"
    return True, ""

def get_video_duration_sec(video_path: str) -> tuple:
    """Returns (duration_sec or None, error_message or ''). Uses ffprobe if available."""
    if not video_path or not os.path.exists(video_path):
        return None, "Ficheiro nao encontrado"
    try:
        # ffprobe -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 <file>
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

def fetch_creator_info(config: dict, cache_seconds: int = 60) -> tuple:
    """Returns (creator_info_dict or None, error_message or '')."""
    token = config.get("access_token", "")
    if not token:
        return None, "Sem access_token"

    cache_key = "creator_info_cache"
    cache_ts_key = "creator_info_cache_ts"
    now_ts = time.time()
    cached = st.session_state.get(cache_key)
    cached_ts = st.session_state.get(cache_ts_key, 0)
    if cached and (now_ts - cached_ts) < cache_seconds:
        return cached, ""

    try:
        import requests as req
        resp = req.post(
            "https://open.tiktokapis.com/v2/post/publish/creator_info/query/",
            headers={"Authorization": f"Bearer {token}",
                     "Content-Type": "application/json; charset=UTF-8"},
            json={}, timeout=10
        )
        data = resp.json()
        if data.get("error", {}).get("code") == "ok":
            st.session_state[cache_key] = data
            st.session_state[cache_ts_key] = now_ts
            return data, ""
        return None, data.get("error", {}).get("message", "Erro creator_info")
    except Exception as e:
        return None, str(e)

def parse_creator_info(creator_data: dict) -> dict:
    privacy_options = creator_data.get("privacy_level_options") or ["PUBLIC_TO_EVERYONE", "SELF_ONLY"]
    max_dur = creator_data.get("max_video_post_duration_sec")
    comment_disabled = bool(creator_data.get("comment_disabled") or
                            creator_data.get("comment_disabled_in_app") or
                            creator_data.get("comment_disabled_in_setting"))
    duet_disabled = bool(creator_data.get("duet_disabled") or
                         creator_data.get("duet_disabled_in_app") or
                         creator_data.get("duet_disabled_in_setting"))
    stitch_disabled = bool(creator_data.get("stitch_disabled") or
                           creator_data.get("stitch_disabled_in_app") or
                           creator_data.get("stitch_disabled_in_setting"))
    can_post = creator_data.get("can_post")
    if can_post is None:
        can_post = creator_data.get("can_publish")
    if can_post is None:
        can_post = creator_data.get("can_post_more")
    if can_post is None:
        can_post = creator_data.get("can_make_more_posts")
    if can_post is None:
        can_post = True
    nickname = creator_data.get("creator_nickname") or creator_data.get("creator_username") or ""
    return {
        "privacy_options": list(dict.fromkeys(privacy_options)),
        "max_duration": max_dur,
        "comment_disabled": comment_disabled,
        "duet_disabled": duet_disabled,
        "stitch_disabled": stitch_disabled,
        "can_post": bool(can_post),
        "nickname": nickname
    }

def score_for_hour(hour_str: str) -> tuple:
    for t in BEST_TIMES:
        if t["label"] == hour_str:
            c = "#ff2d55" if t["score"]>=90 else "#7c3aed" if t["score"]>=80 else "#00f5d4"
            return t["score"], c
    return 70, "#6b7280"

def run_api_test(config: dict) -> tuple:
    import requests as req
    try:
        headers = {
            "Authorization": f"Bearer {config.get('access_token','')}",
            "Content-Type": "application/json; charset=UTF-8"
        }
        resp = req.post(
            "https://open.tiktokapis.com/v2/post/publish/creator_info/query/",
            headers=headers, json={}, timeout=10
        )
        data = resp.json()
        err_code = data.get("error", {}).get("code", "")
        err_msg  = data.get("error", {}).get("message", "")

        if err_code == "ok":
            creator = data.get("data", {})
            nickname = creator.get("creator_nickname", "â€”")
            return ("ok", f"Ligado como: {nickname}")
        if err_code == "access_token_invalid":
            return ("fail", "Access Token invalido ou expirado. Gera um novo em developers.tiktok.com")
        if err_code == "scope_not_authorized":
            return ("fail", "Token sem permissao video.upload. Regenera com o scope correto.")
        if resp.status_code == 401:
            return ("fail", "Autenticacao rejeitada (401). Verifica o Access Token.")
        return ("warn", f"Resposta inesperada: {err_code} â€” {err_msg}")
    except req.exceptions.ConnectionError:
        return ("fail", "Sem ligacao a internet.")
    except req.exceptions.Timeout:
        return ("fail", "Timeout â€” TikTok nao respondeu em 10s.")
    except Exception as e:
        return ("fail", f"Erro: {str(e)}")

def auto_test_api_on_start(config: dict):
    if not (config.get("access_token") and config.get("open_id")):
        return
    token_sig = (config.get("access_token") or "")[-8:]
    if st.session_state.get("api_test_auto_ran") and st.session_state.get("api_test_token_sig") == token_sig:
        return
    st.session_state["api_test_auto_ran"] = True
    st.session_state["api_test_token_sig"] = token_sig
    with st.spinner("A testar conexao ao TikTok..."):
        st.session_state["api_test_result"] = run_api_test(config)

# ── Handle calendar actions via query params ──────────────────────────────────
query_params = st.query_params
if "reschedule_id" in query_params and "reschedule_start" in query_params:
    pid       = query_params["reschedule_id"]
    new_start = query_params["reschedule_start"]
    q = load_queue()
    saved = False
    for p in q:
        if p["id"] == pid and p["status"] == "scheduled":
            try:
                # FullCalendar envia ISO 8601 com T e Z (UTC) — converter para local naive
                clean = new_start.replace("Z", "").replace("z", "")
                if "T" in clean:
                    clean = clean[:19]  # "2026-03-12T14:30:00"
                dt = datetime.fromisoformat(clean)
                p["scheduled_at"] = dt.isoformat()
                p["error"] = None
                p["retry_count"] = 0
                saved = True
            except Exception as _e:
                pass
    if saved:
        save_queue(q)
    st.query_params.clear()
    st.rerun()

if "delete_id" in query_params:
    del_id = query_params["delete_id"]
    save_queue([p for p in load_queue() if p["id"] != del_id])
    st.query_params.clear()
    st.rerun()

# ── TikTok OAuth callback — TikTok redirects back here with ?code=&state= ──────
if OAUTH_AVAILABLE and "code" in query_params and "state" in query_params:
    code  = query_params["code"]
    state = query_params["state"]

    # Tenta session_state primeiro; fallback para ficheiro (caso a sessão tenha mudado)
    stored_state    = st.session_state.get("oauth_state", "")
    code_verifier   = st.session_state.get("oauth_code_verifier", "")
    oauth_initiated = st.session_state.get("oauth_initiated", False)

    # ── Fallback: ler do ficheiro se session_state estiver vazio ──────────────
    if not code_verifier or not stored_state:
        try:
            with open(OAUTH_PENDING_FILE, "r", encoding="utf-8") as _f:
                _pending = json.load(_f)
            stored_state  = _pending.get("state", stored_state)
            code_verifier = _pending.get("code_verifier", code_verifier)
            oauth_initiated = True
        except Exception:
            pass

    # Limpa URL imediatamente
    st.query_params.clear()

    # Apaga ficheiro de pending
    try:
        if os.path.exists(OAUTH_PENDING_FILE):
            os.remove(OAUTH_PENDING_FILE)
    except Exception:
        pass

    if not oauth_initiated or state != stored_state:
        st.session_state["oauth_error"] = "Estado OAuth inválido. Tenta iniciar o login novamente."
    elif not code_verifier:
        st.session_state["oauth_error"] = "code_verifier não encontrado. Reinicia o browser e tenta de novo."
    else:
        cfg = load_config()
        with st.spinner("🔐 A trocar código por tokens TikTok..."):
            token_data = tk_oauth.exchange_code_for_tokens(
                client_key    = cfg.get("client_key", ""),
                client_secret = cfg.get("client_secret", ""),
                code          = code,
                redirect_uri  = OAUTH_REDIRECT_URI,
                code_verifier = code_verifier,
            )
        if token_data.get("error"):
            st.session_state["oauth_error"] = f"Erro ao obter token: {token_data.get('error_description', token_data['error'])}"
        else:
            user_info = tk_oauth.get_user_info(token_data["access_token"])
            updated_cfg = tk_oauth.save_tokens_to_config(CONFIG_FILE, token_data, user_info if user_info.get("ok") else {})
            for key in ["oauth_state","oauth_code_verifier","oauth_initiated","oauth_error"]:
                st.session_state.pop(key, None)
            st.session_state["oauth_success"] = updated_cfg.get("connected_display_name") or "Conta conectada"
    st.rerun()

# ── Sidebar ──────────────────────────────────────────────────────────────────
# Auto-teste de conexao ao abrir a app (uma vez por sessao)
auto_test_api_on_start(load_config())

with st.sidebar:
    st.markdown("""
    <div style='padding:1.2rem 0 .8rem;'>
      <div style='font-family:Syne,sans-serif;font-size:1.8rem;font-weight:800;
        background:linear-gradient(135deg,#ff2d55,#7c3aed,#00f5d4);
        -webkit-background-clip:text;-webkit-text-fill-color:transparent;line-height:1.2;'>CreatorFlow</div>
    </div>""", unsafe_allow_html=True)
    st.divider()

    page = st.radio("Nav", [
        "🎬 Agendar 1 Video",
        "🚀 Agendar Lote",
        "📅 Calendario",
        "📋 Fila de Posts",
        "📱 Ver no TikTok",
        "🔍 Verificacao",
        "🔐 Conta TikTok",
        "⚙️ Configuracoes"
    ], label_visibility="collapsed")
    st.divider()

    q = load_queue()
    s_ct = len([p for p in q if p["status"]=="scheduled"])
    p_ct = len([p for p in q if p["status"]=="posted"])
    f_ct = len([p for p in q if p["status"]=="failed"])
    st.markdown(f"""
    <div style='display:flex;flex-direction:column;gap:4px;'>
      <div style='display:flex;justify-content:space-between;padding:.5rem .8rem;
        background:#111118;border-radius:9px;border:1px solid #1e1e2e;'>
        <span style='color:#6b7280;font-size:.78rem;'>⏳ Agendados</span>
        <span style='color:#00f5d4;font-weight:700;'>{s_ct}</span></div>
      <div style='display:flex;justify-content:space-between;padding:.5rem .8rem;
        background:#111118;border-radius:9px;border:1px solid #1e1e2e;'>
        <span style='color:#6b7280;font-size:.78rem;'>✅ Publicados</span>
        <span style='color:#22c55e;font-weight:700;'>{p_ct}</span></div>
      <div style='display:flex;justify-content:space-between;padding:.5rem .8rem;
        background:#111118;border-radius:9px;border:1px solid #1e1e2e;'>
        <span style='color:#6b7280;font-size:.78rem;'>❌ Falhados</span>
        <span style='color:#ff2d55;font-weight:700;'>{f_ct}</span></div>
    </div>""", unsafe_allow_html=True)
    st.divider()

    scheduler_on = os.path.exists(os.path.join(BASE_DIR,"scheduler.pid"))
    dot_color = "#22c55e" if scheduler_on else "#f59e0b"
    dot_label = "Scheduler Ativo" if scheduler_on else "Scheduler Offline"
    anim = "animation:pulse 1.5s infinite;" if scheduler_on else ""
    st.markdown(f"""
    <div style='display:flex;align-items:center;gap:.5rem;padding:.5rem .8rem;
      background:rgba(0,0,0,.2);border:1px solid {dot_color}33;border-radius:9px;'>
      <div style='width:7px;height:7px;border-radius:50%;background:{dot_color};{anim}'></div>
      <span style='font-size:.78rem;color:{dot_color};font-weight:500;'>{dot_label}</span>
    </div>
    <style>@keyframes pulse{{0%,100%{{opacity:1}}50%{{opacity:.4}}}}</style>""",
    unsafe_allow_html=True)

    # Auto-teste API silencioso na primeira carga
    _cfg_sb = load_config()
    if _cfg_sb.get("access_token") and _cfg_sb.get("open_id"):
        if "api_auto_tested" not in st.session_state:
            st.session_state["api_auto_tested"] = True
            try:
                import requests as _rq
                _r = _rq.post(
                    "https://open.tiktokapis.com/v2/post/publish/creator_info/query/",
                    headers={"Authorization": f"Bearer {_cfg_sb['access_token']}",
                             "Content-Type": "application/json; charset=UTF-8"},
                    json={}, timeout=8
                )
                _d = _r.json()
                if _d.get("error", {}).get("code") == "ok":
                    st.session_state["api_status"] = ("ok", "API OK")
                else:
                    st.session_state["api_status"] = ("fail", _d.get("error", {}).get("message", "Erro"))
            except Exception as _e:
                st.session_state["api_status"] = ("fail", str(_e)[:60])

    # TikTok connection badge
    _cfg_sb = load_config()
    _is_auth = bool(_cfg_sb.get("access_token") and _cfg_sb.get("open_id"))
    _auth_method = _cfg_sb.get("auth_method", "")
    _display_name = _cfg_sb.get("connected_display_name", "")
    if _is_auth:
        _bc = "#22c55e"; _bi = "🔗"
        _bl = f"@{_display_name}" if _display_name else "TikTok conectado"
        _bs = "Login Kit OAuth ✓" if _auth_method == "oauth_login_kit" else "Token manual"
    else:
        _bc = "#f59e0b"; _bi = "🔓"; _bl = "TikTok desconectado"; _bs = "Vai a 🔐 Conta TikTok"
    st.markdown(f"""
    <div style='margin-top:.4rem;display:flex;align-items:center;gap:.5rem;padding:.45rem .8rem;
      background:rgba(0,0,0,.2);border:1px solid {_bc}33;border-radius:9px;'>
      <span style='font-size:.85rem;'>{_bi}</span>
      <div>
        <div style='font-size:.72rem;color:{_bc};font-weight:600;'>{_bl}</div>
        <div style='font-size:.63rem;color:#6b7280;'>{_bs}</div>
      </div>
    </div>""", unsafe_allow_html=True)

    # API status badge
    _api_st = st.session_state.get("api_status")
    if _api_st:
        _acolor = "#22c55e" if _api_st[0] == "ok" else "#ff2d55"
        _aicon  = "✅" if _api_st[0] == "ok" else "❌"
        st.markdown(f"""
        <div style='margin-top:.4rem;display:flex;align-items:center;gap:.5rem;padding:.45rem .8rem;
          background:rgba(0,0,0,.2);border:1px solid {_acolor}33;border-radius:9px;'>
          <span style='font-size:.85rem;'>{_aicon}</span>
          <div style='font-size:.68rem;color:{_acolor};font-weight:600;'>API TikTok {_api_st[1]}</div>
        </div>""", unsafe_allow_html=True)

    sched_posts = sorted([p for p in q if p["status"]=="scheduled"],
                          key=lambda x: x.get("scheduled_at",""))
    if sched_posts:
        try:
            nxt = datetime.fromisoformat(sched_posts[0]["scheduled_at"])
            delta = nxt - datetime.now()
            if delta.total_seconds() > 0:
                h = int(delta.total_seconds()//3600)
                m = int((delta.total_seconds()%3600)//60)
                st.markdown(f"""<br><div style='text-align:center;padding:.8rem;
                  background:rgba(255,45,85,.06);border:1px solid rgba(255,45,85,.15);
                  border-radius:10px;'>
                  <div style='color:#6b7280;font-size:.68rem;text-transform:uppercase;
                    letter-spacing:1px;margin-bottom:.2rem;'>Proximo post em</div>
                  <div style='font-family:Syne,sans-serif;font-size:1.4rem;
                    font-weight:800;color:#ff2d55;'>{h}h {m}m</div>
                  <div style='color:#6b7280;font-size:.7rem;'>
                    {nxt.strftime("%d/%m as %H:%M")}</div></div>""",
                unsafe_allow_html=True)
        except: pass


# ════════════════════════════════════════════════════════════════════════════════
# PAGE: AGENDAR 1 VIDEO
# ════════════════════════════════════════════════════════════════════════════════
if page == "🎬 Agendar 1 Video":
    st.markdown("<div class='pt'>🎬 Agendar 1 Video</div>", unsafe_allow_html=True)
    st.markdown("<div class='ps'>Upload de um video, define legenda, data e hora — pronto</div>", unsafe_allow_html=True)

    _cfg_pg = load_config()
    _creator_info, _creator_err = fetch_creator_info(_cfg_pg, cache_seconds=60)
    _creator_data = _creator_info.get("data", {}) if _creator_info else {}
    _creator_flags = parse_creator_info(_creator_data) if _creator_info else {
        "privacy_options": ["PUBLIC_TO_EVERYONE", "SELF_ONLY"],
        "max_duration": None,
        "comment_disabled": False,
        "duet_disabled": False,
        "stitch_disabled": False,
        "can_post": True,
        "nickname": ""
    }

    if _creator_info:
        _nn = _creator_flags.get("nickname") or "—"
        st.markdown(f"<div style='font-size:.82rem;color:#6b7280;margin-bottom:.6rem;'>Conta TikTok: <b style='color:#f0f0f8;'>@{_nn}</b></div>", unsafe_allow_html=True)
    else:
        st.markdown(f"<div style='font-size:.78rem;color:#f59e0b;margin-bottom:.6rem;'>Nao foi possivel carregar creator_info: {_creator_err or 'erro'}</div>", unsafe_allow_html=True)
    if not _creator_flags.get("can_post", True):
        st.warning("O criador nao pode publicar agora. Tenta mais tarde.")
    if not _creator_flags.get("can_post", True):
        st.warning("O criador nao pode publicar agora. Tenta mais tarde.")

    col_form, col_prev = st.columns([1.2, 0.8], gap="large")

    with col_form:
        dest = None
        duration_sec = None
        duration_err = ""

        st.markdown("<div class='sh'>🎬 Video</div>", unsafe_allow_html=True)
        uploaded = st.file_uploader("Escolhe o video", type=["mp4","mov","avi","webm"])
        if uploaded:
            ok, err_msg = validate_video(uploaded)
            if not ok:
                st.error(f"❌ {err_msg}")
                uploaded = None
            else:
                size_mb = len(uploaded.getbuffer()) / (1024*1024)
                dest = os.path.join(VIDEOS_DIR, uploaded.name)
                with open(dest,"wb") as fout: fout.write(uploaded.getbuffer())
                st.success(f"✅ Guardado: {uploaded.name} ({size_mb:.1f}MB)")

        # Duracao max do TikTok (creator_info)
        max_dur = _creator_flags.get("max_duration")
        if uploaded and max_dur:
            duration_sec, duration_err = get_video_duration_sec(dest)
            if duration_sec is None:
                st.error(f"⚠️ Nao foi possivel verificar duracao: {duration_err}")
            else:
                if duration_sec > max_dur:
                    st.error(f"❌ Duracao {int(duration_sec)}s excede o maximo permitido ({int(max_dur)}s)")
                else:
                    st.info(f"Duracao: {int(duration_sec)}s (max {int(max_dur)}s)")

        st.markdown("---")
        st.markdown("<div class='sh'>✏️ Titulo</div>", unsafe_allow_html=True)
        caption = st.text_area("Titulo", height=90,
            placeholder="Escreve o titulo do post...")
        char_c = len(caption)
        cc = "#22c55e" if char_c<2000 else "#f59e0b" if char_c<2200 else "#ff2d55"
        st.markdown(f"<div style='text-align:right;font-size:.72rem;color:{cc};'>{char_c}/2200</div>", unsafe_allow_html=True)
        hashtags = st.text_input("Hashtags", value="#fyp #musica #portugal")

        st.markdown("---")
        st.markdown("<div class='sh'>💼 Conteudo Comercial</div>", unsafe_allow_html=True)
        commercial_toggle = st.checkbox("Este conteudo promove a ti, um produto ou servico?", value=False, key="commercial_single")
        your_brand = False
        branded_content = False
        commercial_valid = True
        if commercial_toggle:
            ccb1, ccb2 = st.columns(2)
            with ccb1:
                your_brand = st.checkbox("Your brand", value=False, key="commercial_your_single")
            with ccb2:
                branded_content = st.checkbox("Branded content", value=False, key="commercial_branded_single")

            if your_brand and branded_content:
                st.info("Your photo/video will be labeled as 'Paid partnership'")
            elif your_brand:
                st.info("Your photo/video will be labeled as 'Promotional content'")
            elif branded_content:
                st.info("Your photo/video will be labeled as 'Paid partnership'")
            else:
                commercial_valid = False
                st.warning("Seleciona 'Your brand', 'Branded content', ou ambos.")

        st.markdown("---")
        st.markdown("<div class='sh'>🔒 Privacidade e Interacoes</div>", unsafe_allow_html=True)
        privacy_options = list(_creator_flags.get("privacy_options") or [])
        if commercial_toggle and branded_content:
            privacy_options = [p for p in privacy_options if p != "SELF_ONLY"]
        if not privacy_options:
            st.warning("Nao foi possivel carregar opcoes de privacidade do creator_info.")
        privacy_key = "privacy_single"
        if privacy_key in st.session_state and st.session_state[privacy_key] not in privacy_options:
            del st.session_state[privacy_key]
        privacy_choice = st.selectbox(
            "Privacidade",
            privacy_options,
            index=None,
            placeholder="Seleciona...",
            key=privacy_key,
            format_func=lambda x: PRIVACY_LABELS.get(x, x)
        )

        allow_comment = st.checkbox("Permitir comentarios", value=False,
                                    disabled=_creator_flags.get("comment_disabled", False),
                                    help="Desativado nas definicoes do criador" if _creator_flags.get("comment_disabled", False) else "")
        allow_duet = st.checkbox("Permitir duet", value=False,
                                 disabled=_creator_flags.get("duet_disabled", False),
                                 help="Desativado nas definicoes do criador" if _creator_flags.get("duet_disabled", False) else "")
        allow_stitch = st.checkbox("Permitir stitch", value=False,
                                   disabled=_creator_flags.get("stitch_disabled", False),
                                   help="Desativado nas definicoes do criador" if _creator_flags.get("stitch_disabled", False) else "")

        st.markdown("---")
        st.markdown("<div class='sh'>📅 Data e Hora</div>", unsafe_allow_html=True)
        col_d, col_h = st.columns(2)
        with col_d:
            sug = suggest_dates(1)
            default_d = sug[0] if sug else datetime.now().date() + timedelta(days=1)
            chosen_date = st.date_input("Data", value=default_d,
                                         min_value=datetime.now().date())
        with col_h:
            import datetime as _dt
            _default_time = _dt.time(20, 0)
            if "quick_hour_single" in st.session_state:
                try:
                    _ph, _pm = st.session_state["quick_hour_single"].split(":")
                    _default_time = _dt.time(int(_ph), int(_pm))
                except: pass
            chosen_time = st.time_input("Hora", value=_default_time, step=300)
            chosen_hour = chosen_time.strftime("%H:%M")

        st.markdown("<div style='font-size:.75rem;color:#6b7280;margin:.5rem 0 .3rem;'>⚡ Atalhos</div>", unsafe_allow_html=True)
        qc = st.columns(5)
        quick_hours = ["07:30","12:00","17:00","20:00","22:30"]
        for qi, (qcol, qh) in enumerate(zip(qc, quick_hours)):
            with qcol:
                if st.button(qh, key=f"q_{qi}"):
                    st.session_state["quick_hour_single"] = qh
                    st.rerun()
        if "quick_hour_single" in st.session_state:
            chosen_hour = st.session_state["quick_hour_single"]

        final_dt = datetime.combine(chosen_date, hour_str_to_time(chosen_hour))
        is_future = final_dt > datetime.now()
        if not is_future:
            st.warning("⚠️ A data/hora esta no passado!")

        consent_text = "By posting, you agree to TikTok's Music Usage Confirmation."
        if commercial_toggle and branded_content:
            consent_text = "By posting, you agree to TikTok's Branded Content Policy and Music Usage Confirmation."
        st.markdown(f"<div style='font-size:.75rem;color:#6b7280;margin:.4rem 0 .2rem;'>{consent_text}</div>", unsafe_allow_html=True)
        user_consent = st.checkbox("Concordo com a declaracao acima", value=False, key="consent_single")
        st.markdown("<div style='font-size:.7rem;color:#6b7280;margin-top:.2rem;'>Apos publicar, pode demorar alguns minutos a aparecer no perfil.</div>", unsafe_allow_html=True)

        st.markdown("<br>", unsafe_allow_html=True)
        if st.button("🚀 AGENDAR ESTE VIDEO", use_container_width=True):
            errs = []
            if not _creator_info:
                errs.append("Nao foi possivel obter creator_info. Conecta a conta TikTok.")
            if not _creator_flags.get("can_post", True):
                errs.append("O criador nao pode publicar agora. Tenta mais tarde.")
            if not uploaded:
                errs.append("Seleciona um video valido!")
            if max_dur and duration_sec is None:
                errs.append("Nao foi possivel validar a duracao do video.")
            if max_dur and duration_sec is not None and duration_sec > max_dur:
                errs.append("Duracao do video excede o maximo permitido.")
            if not caption.strip():
                errs.append("Escreve o titulo do post!")
            if not is_future:
                errs.append("Escolhe uma hora no futuro!")
            if privacy_choice is None:
                errs.append("Seleciona a privacidade (sem valor por defeito).")
            if commercial_toggle and not commercial_valid:
                errs.append("Seleciona o tipo de conteudo comercial.")
            if commercial_toggle and branded_content and privacy_choice == "SELF_ONLY":
                errs.append("Branded content nao pode ser privado.")
            if not user_consent:
                errs.append("Confirma o consentimento antes de publicar.")

            if errs:
                for e in errs:
                    st.error(f"❌ {e}")
            else:
                meta = {
                    "privacy_level": privacy_choice,
                    "allow_comment": bool(allow_comment),
                    "allow_duet": bool(allow_duet),
                    "allow_stitch": bool(allow_stitch),
                    "commercial_toggle": bool(commercial_toggle),
                    "commercial_your_brand": bool(your_brand),
                    "commercial_branded_content": bool(branded_content),
                    "user_consent": bool(user_consent),
                    "consent_text": consent_text,
                    "creator_nickname": _creator_flags.get("nickname", "")
                }
                add_post(os.path.join(VIDEOS_DIR, uploaded.name),
                         caption, hashtags, final_dt.isoformat(), meta=meta)
                st.success(f"✅ Agendado para {final_dt.strftime('%d/%m/%Y as %H:%M')}!")
                st.balloons()

    with col_prev:
        st.markdown("<div class='sh'>👁️ Preview</div>", unsafe_allow_html=True)
        if uploaded:
            st.video(uploaded)
        score, bar_c = score_for_hour(chosen_hour)
        st.markdown(f"""
        <div style='background:#111118;border:1px solid #1e1e2e;border-radius:16px;padding:1.4rem;'>
          <div style='background:#000;border-radius:10px;min-height:120px;
            display:flex;align-items:center;justify-content:center;margin-bottom:1rem;'>
            <div style='color:#6b7280;font-size:.82rem;text-align:center;'>
              🎬<br>{"<b style='color:#f0f0f8;'>" + (uploaded.name[:30] if uploaded else "sem video") + "</b>"}</div>
          </div>
          <div style='font-size:.84rem;color:#f0f0f8;margin-bottom:.4rem;line-height:1.4;'>
            {caption[:120] + "..." if len(caption)>120 else caption or "<span style='color:#6b7280;'>sem legenda</span>"}</div>
          <div style='font-size:.75rem;color:#7c3aed;margin-bottom:.8rem;'>{hashtags}</div>
          <div style='background:#16161f;border-radius:8px;padding:.6rem .8rem;'>
            <div style='font-size:.75rem;color:#6b7280;'>📅 {final_dt.strftime("%d/%m/%Y")}</div>
            <div style='font-family:Syne,sans-serif;font-size:1.3rem;font-weight:800;color:{bar_c};'>{chosen_hour}</div>
            <div style='background:#1e1e2e;border-radius:3px;height:4px;margin-top:.3rem;overflow:hidden;'>
              <div style='height:100%;width:{score}%;background:{bar_c};border-radius:3px;'></div></div>
            <div style='font-size:.7rem;color:{bar_c};margin-top:.2rem;'>{score}% engagement PT</div>
          </div>
        </div>""", unsafe_allow_html=True)

        st.markdown("<br><div class='sh'>⏰ Melhores horas</div>", unsafe_allow_html=True)
        for t in BEST_TIMES:
            bc = "#ff2d55" if t["score"]>=90 else "#7c3aed" if t["score"]>=80 else "#00f5d4"
            active = "border-color:" + bc + ";" if t["label"]==chosen_hour else ""
            st.markdown(f"""
            <div style='display:flex;justify-content:space-between;align-items:center;
              padding:.45rem .8rem;background:#111118;border-radius:8px;margin-bottom:3px;
              border:1px solid #1e1e2e;{active}'>
              <span style='font-size:.8rem;color:#f0f0f8;font-weight:600;'>{t["label"]}</span>
              <span style='font-size:.75rem;color:#6b7280;'>{t["why"]}</span>
              <span style='font-size:.72rem;color:{bc};font-weight:700;'>{t["score"]}%</span>
            </div>""", unsafe_allow_html=True)


# ════════════════════════════════════════════════════════════════════════════════
# PAGE: AGENDAR LOTE
# ════════════════════════════════════════════════════════════════════════════════
elif page == "🚀 Agendar Lote":
    st.markdown("<div class='pt'>🚀 Agendar Lote</div>", unsafe_allow_html=True)
    st.markdown("<div class='ps'>Arrasta os videos para qualquer parte da pagina — o autopilot distribui as datas</div>", unsafe_allow_html=True)

    _cfg_pg = load_config()
    _creator_info, _creator_err = fetch_creator_info(_cfg_pg, cache_seconds=60)
    _creator_data = _creator_info.get("data", {}) if _creator_info else {}
    _creator_flags = parse_creator_info(_creator_data) if _creator_info else {
        "privacy_options": ["PUBLIC_TO_EVERYONE", "SELF_ONLY"],
        "max_duration": None,
        "comment_disabled": False,
        "duet_disabled": False,
        "stitch_disabled": False,
        "can_post": True,
        "nickname": ""
    }

    if _creator_info:
        _nn = _creator_flags.get("nickname") or "—"
        st.markdown(f"<div style='font-size:.82rem;color:#6b7280;margin-bottom:.6rem;'>Conta TikTok: <b style='color:#f0f0f8;'>@{_nn}</b></div>", unsafe_allow_html=True)
    else:
        st.markdown(f"<div style='font-size:.78rem;color:#f59e0b;margin-bottom:.6rem;'>Nao foi possivel carregar creator_info: {_creator_err or 'erro'}</div>", unsafe_allow_html=True)

    # ── CSS: zona de drop ENORME que cobre toda a pagina ─────────────────────
    st.markdown("""
    <style>
    /* Uploader ocupa a largura toda e fica com altura generosa */
    [data-testid="stFileUploaderDropzone"]{
      min-height:200px!important;
      display:flex!important;align-items:center!important;justify-content:center!important;
      flex-direction:column!important;gap:.5rem!important;
      font-size:1.1rem!important;
      border:3px dashed #7c3aed!important;
      border-radius:20px!important;
      background:rgba(124,58,237,.04)!important;
      transition:all .25s!important;
      cursor:pointer!important;}
    [data-testid="stFileUploaderDropzone"]:hover,
    [data-testid="stFileUploaderDropzone"]:focus-within{
      border-color:#ff2d55!important;
      background:rgba(255,45,85,.07)!important;
      box-shadow:0 0 40px rgba(255,45,85,.12)!important;}
    /* Esconde o label redundante */
    [data-testid="stFileUploaderDropzoneInstructions"] small{display:none!important;}
    [data-testid="stFileUploaderDropzoneInstructions"] span{
      font-size:1rem!important;font-weight:600!important;color:#f0f0f8!important;}
    /* Botao browse */
    [data-testid="stFileUploaderDropzone"] button{
      background:linear-gradient(135deg,#ff2d55,#7c3aed)!important;
      border:none!important;border-radius:10px!important;
      color:white!important;font-weight:700!important;
      padding:.5rem 1.5rem!important;font-size:.9rem!important;
      margin-top:.5rem!important;}
    /* Ficheiros listados */
    [data-testid="stFileUploader"] [data-testid="stFileUploaderFileData"]{
      background:#111118!important;border-radius:10px!important;
      border:1px solid #1e1e2e!important;margin-top:.4rem!important;
      padding:.4rem .8rem!important;}
    </style>""", unsafe_allow_html=True)

    # Texto personalizado ACIMA do uploader
    st.markdown("""
    <div style='text-align:center;padding:1rem 0 .5rem;'>
      <div style='font-size:2.5rem;margin-bottom:.3rem;'>🎬</div>
      <div style='font-size:1.05rem;font-weight:700;color:#f0f0f8;margin-bottom:.2rem;'>
        Arrasta os teus videos para aqui ou clica em Browse</div>
      <div style='font-size:.82rem;color:#6b7280;'>
        MP4 · MOV · AVI · WEBM &nbsp;|&nbsp; até 500 MB por video &nbsp;|&nbsp; máx 20 videos</div>
    </div>""", unsafe_allow_html=True)

    files = st.file_uploader(
        "videos",
        type=["mp4","mov","avi","webm"],
        accept_multiple_files=True,
        label_visibility="collapsed",
        key="lote_uploader"
    )

    if files and len(files) > 20:
        st.warning(f"Selecionaste {len(files)} — so os primeiros 20 serao usados.")
        files = files[:20]
    if files:
        valid_files = []
        for f in files:
            ok, err_msg = validate_video(f)
            if ok: valid_files.append(f)
            else:  st.error(f"❌ {f.name}: {err_msg}")
        files = valid_files

    if not files:
        st.stop()

    n = len(files)
    total_mb = sum(len(f.getbuffer()) for f in files) / (1024*1024)
    names_str = " · ".join([f.name[:22]+"…" if len(f.name)>22 else f.name for f in files[:4]])
    st.markdown(f"""
    <div style='display:flex;align-items:center;gap:.9rem;padding:.65rem 1rem;
      background:rgba(34,197,94,.07);border:1px solid rgba(34,197,94,.3);
      border-radius:11px;margin:.4rem 0;flex-wrap:wrap;'>
      <span style='font-size:1.2rem;'>✅</span>
      <span style='font-weight:700;color:#22c55e;font-size:.88rem;'>{n} video{"s" if n>1 else ""} prontos</span>
      <span style='color:#6b7280;font-size:.78rem;'>{total_mb:.1f} MB</span>
      <span style='color:#6b7280;font-size:.78rem;flex:1;text-align:right;'>{names_str}{"…" if n>4 else ""}</span>
    </div>""", unsafe_allow_html=True)

    # ── Smart Shuffle ─────────────────────────────────────────────────────────
    import re as _re

    def base_name(fname: str) -> str:
        """Extrai o nome base do ficheiro ignorando (N) e extensão.
        Ex: 'oi(2).mp4' → 'oi', 'ola(1).mov' → 'ola', 'dance.mp4' → 'dance'"""
        stem = fname.rsplit(".", 1)[0] if "." in fname else fname
        return _re.sub(r"\s*\(\d+\)\s*$", "", stem).strip().lower()

    def smart_shuffle(file_list):
        """Interleave por grupo de nome-base para nunca repetir a mesma musica 2x seguido."""
        import random
        groups: dict = {}
        for i, f in enumerate(file_list):
            key = base_name(f.name)
            groups.setdefault(key, []).append(i)
        # Embaralha dentro de cada grupo
        for v in groups.values():
            random.shuffle(v)
        # Round-robin entre grupos (ordem dos grupos também aleatória)
        group_lists = list(groups.values())
        random.shuffle(group_lists)
        result = []
        while any(group_lists):
            for grp in group_lists:
                if grp:
                    result.append(grp.pop(0))
            group_lists = [g for g in group_lists if g]
        return result

    # Paleta de cores para grupos
    GROUP_COLORS = [
        "#ff2d55","#00f5d4","#7c3aed","#f59e0b","#22c55e",
        "#06b6d4","#f97316","#a78bfa","#34d399","#fb7185",
    ]

    # Calcular grupos e cores sempre (independente do shuffle)
    all_bases = [base_name(f.name) for f in files]
    unique_bases = list(dict.fromkeys(all_bases))  # ordem de aparição, sem duplicados
    base_color = {b: GROUP_COLORS[i % len(GROUP_COLORS)] for i, b in enumerate(unique_bases)}
    has_groups = len(unique_bases) < n  # só mostra se há pelo menos um grupo com >1 video

    # Estado do shuffle
    file_key = "_".join(sorted(f.name for f in files))
    if "lote_shuffle_key" not in st.session_state or st.session_state["lote_shuffle_key"] != file_key:
        st.session_state["lote_shuffle_key"] = file_key
        st.session_state["lote_order"] = list(range(n))

    order = st.session_state["lote_order"]
    files_ordered = [files[i] for i in order]

    # Botão de shuffle + info de grupos
    st.markdown("<div style='margin:.4rem 0 .2rem;'>", unsafe_allow_html=True)
    sh_col1, sh_col2, sh_col3 = st.columns([2, 1.2, 1.2])
    with sh_col1:
        if has_groups:
            groups_info = ", ".join([
                f"<span style='color:{base_color[b]};font-weight:700;'>&ldquo;{b}&rdquo;&times;{all_bases.count(b)}</span>"
                for b in unique_bases if all_bases.count(b) > 1
            ])
            st.markdown(
                f"<div style='font-size:.78rem;color:#6b7280;padding:.4rem 0;'>"
                f"🎵 Grupos detectados: {groups_info}</div>",
                unsafe_allow_html=True)
        else:
            st.markdown(
                "<div style='font-size:.78rem;color:#6b7280;padding:.4rem 0;'>"
                "🎵 Cada video tem nome único — shuffle aleatório simples</div>",
                unsafe_allow_html=True)
    with sh_col2:
        if st.button("🎲 Distribuir Inteligente", use_container_width=True,
                     help="Embaralha e espaça videos com o mesmo nome para nunca postar a mesma musica dois dias seguidos"):
            st.session_state["lote_order"] = smart_shuffle(files)
            st.rerun()
    with sh_col3:
        if st.button("↺ Ordem Original", use_container_width=True,
                     help="Volta à ordem em que carregaste os ficheiros"):
            st.session_state["lote_order"] = list(range(n))
            st.rerun()
    st.markdown("</div>", unsafe_allow_html=True)

    st.markdown("---")

    # ── Titulo e hashtags ─────────────────────────────────────────────────────
    lc1, lc2 = st.columns([1.8, 1.2])
    with lc1:
        legenda_global = st.text_area("✏️ Titulo base", height=78,
            placeholder="Titulo aplicado a todos os videos…")
        cg = "#22c55e" if len(legenda_global)<2000 else "#f59e0b" if len(legenda_global)<2200 else "#ff2d55"
        st.markdown(f"<div style='text-align:right;font-size:.7rem;color:{cg};'>{len(legenda_global)}/2200</div>", unsafe_allow_html=True)
    with lc2:
        hashtags = st.text_input("# Hashtags", value="#fyp #musica #portugal")
        legenda_individual = st.toggle("Titulo individual por video", value=False)

    st.markdown("---")
    autopilot = st.toggle("🤖 Autopilot — distribui datas automaticamente", value=True)

    # A partir daqui usa SEMPRE files_ordered (com o shuffle aplicado)
    files = files_ordered
    n = len(files)

    # ═══════════════════════════════════════════════════════════════════════════
    # AUTOPILOT
    # ═══════════════════════════════════════════════════════════════════════════
    if autopilot:
        st.markdown("<div class='sh'>🤖 Estrategia</div>", unsafe_allow_html=True)
        ac1, ac2, ac3 = st.columns(3)
        with ac1:
            posts_per_week = st.selectbox("Posts / semana", [1,2,3,4,5,6,7], index=6,
                help="7 = todos os dias seguidos (default)")
        with ac2:
            preferred_hour = st.selectbox("Hora preferida", HOUR_OPTIONS,
                index=HOUR_OPTIONS.index("20:00"))
        with ac3:
            today = datetime.now().date()
            start_from = st.date_input("A partir de",
                value=today + timedelta(days=1),
                min_value=today + timedelta(days=1),
                key="ap_start_from")

        # Semana de referencia visual (mantida para compatibilidade com a chave do session_state)
        week_start = start_from - timedelta(days=start_from.weekday())

        day_names_pt = ["Seg","Ter","Qua","Qui","Sex","Sáb","Dom"]

        # Calcula a proxima ocorrencia de cada dia da semana a partir de amanha
        tomorrow = today + timedelta(days=1)
        def next_occurrence(weekday_idx):
            d = tomorrow
            while d.weekday() != weekday_idx:
                d += timedelta(days=1)
            return d

        st.markdown(
            f"<div style='font-size:.78rem;color:#6b7280;margin:.7rem 0 .4rem;'>"
            f"📅 Escolhe os dias da semana — o scheduler usa a <b>proxima ocorrencia disponivel</b> de cada dia. "
            f"A partir de <b style='color:#00f5d4;'>{start_from.strftime('%d/%m/%Y')}</b>."
            f"</div>",
            unsafe_allow_html=True)

        day_cols = st.columns(7)
        preferred_days = []

        for di in range(7):
            # Data de referencia visual = proxima ocorrencia deste dia da semana
            ref_date = next_occurrence(di)
            is_today_flag = ref_date == today  # nunca True pois ref_date >= amanha

            # Esta semana: o dia pode estar no passado — mas o dia da SEMANA é válido
            this_week_date = week_start + timedelta(days=di)
            was_this_week_past = this_week_date <= today

            # Cores: dias de semana normais vs fim-de-semana
            if di in [5, 6]:
                bg = "rgba(124,58,237,.08)"; border = "#7c3aed55"; lc_day = "#a78bfa"; dc = "#7c3aed"
            else:
                bg = "rgba(0,245,212,.06)"; border = "#00f5d455"; lc_day = "#00f5d4"; dc = "#6b7280"

            # Se o dia desta semana já passou, mostra cinza com nota "prox semana"
            if was_this_week_past:
                bg = "rgba(30,30,46,.5)"; border = "#2a2a3a"; lc_day = "#4a4a6a"; dc = "#3a3a5a"
                label_extra = f"prox. {ref_date.strftime('%d/%m')}"
                lce = "#4a4a6a"
            else:
                label_extra = ref_date.strftime("%d/%m")
                lce = dc

            # Default de checkbox
            if posts_per_week == 7:   default_on = True
            elif posts_per_week >= 5: default_on = di < 5
            elif posts_per_week >= 3: default_on = di in [1, 3, 5]
            else:                     default_on = di in [1, 4]

            with day_cols[di]:
                checked = st.checkbox(
                    day_names_pt[di],
                    value=default_on,
                    disabled=False,  # NUNCA desativa — o dia da semana e sempre valido
                    key=f"day_{di}_{start_from.isoformat()}_{posts_per_week}"
                )
                st.markdown(f"""
                <div style='margin-top:-6px;padding:.45rem .3rem;background:{bg};
                  border:1px solid {border};border-radius:9px;text-align:center;'>
                  <div style='font-size:.78rem;font-weight:800;color:{lc_day};'>{day_names_pt[di]}</div>
                  <div style='font-size:.75rem;font-weight:700;color:{lce};margin-top:2px;'>{label_extra}</div>
                </div>""", unsafe_allow_html=True)
                if checked:
                    preferred_days.append(di)

        if not preferred_days:
            preferred_days = list(range(7))

        # Gerar slots — sem gap entre posts, usa dias consecutivos permitidos
        def autopilot_dates(n_vids, ppw, hour_str, from_date, allowed_days):
            taken = taken_days_from_queue()
            slots, d = [], from_date
            while len(slots) < n_vids and d < from_date + timedelta(days=730):
                if d <= today:                          d += timedelta(days=1); continue
                if d in taken:                          d += timedelta(days=1); continue
                if d.weekday() not in allowed_days:     d += timedelta(days=1); continue
                slots.append(datetime.combine(d, hour_str_to_time(hour_str)))
                d += timedelta(days=1)
            return slots

        auto_slots = autopilot_dates(n, posts_per_week, preferred_hour, start_from, preferred_days)

        if auto_slots:
            span_days = (auto_slots[-1].date() - auto_slots[0].date()).days + 1
            weeks = max(1, round(span_days / 7))
            st.markdown(f"""
            <div style='display:flex;gap:.8rem;margin:.6rem 0;padding:.8rem 1rem;
              background:rgba(0,245,212,.05);border:1px solid rgba(0,245,212,.2);
              border-radius:12px;flex-wrap:wrap;align-items:center;'>
              <div style='text-align:center;min-width:46px;'>
                <div style='font-family:Syne,sans-serif;font-size:1.5rem;font-weight:800;color:#ff2d55;line-height:1;'>{n}</div>
                <div style='color:#6b7280;font-size:.65rem;'>videos</div></div>
              <div style='text-align:center;min-width:46px;'>
                <div style='font-family:Syne,sans-serif;font-size:1.5rem;font-weight:800;color:#00f5d4;line-height:1;'>{span_days}</div>
                <div style='color:#6b7280;font-size:.65rem;'>dias</div></div>
              <div style='text-align:center;min-width:46px;'>
                <div style='font-family:Syne,sans-serif;font-size:1.5rem;font-weight:800;color:#7c3aed;line-height:1;'>{weeks}</div>
                <div style='color:#6b7280;font-size:.65rem;'>semanas</div></div>
              <div style='flex:1;font-size:.82rem;color:#f0f0f8;'>
                📅 <b>{auto_slots[0].strftime("%d/%m")}</b> → <b>{auto_slots[-1].strftime("%d/%m/%Y")}</b>
                &nbsp;·&nbsp; ⏰ <b style='color:#00f5d4;'>{preferred_hour}</b>
              </div>
            </div>""", unsafe_allow_html=True)

            # Grid de datas — nome do video + engagement do DIA especifico do slot
            day_pt = ["Seg","Ter","Qua","Qui","Sex","Sáb","Dom"]

            # Scores base para cada hora (usa score_for_hour já definida)
            live_scores = {h: score_for_hour(h)[0] for h in HOUR_OPTIONS}

            # Scores de engagement calculados para cada dia da semana
            # Fator por dia: Seg-Qui normal, Sex +5%, Sab/Dom padrao fds
            day_eng_factor = {0:1.0, 1:1.0, 2:0.95, 3:1.0, 4:1.08, 5:1.12, 6:1.10}

            def slot_scores(slot_dt):
                """Scores para a hora+dia especificos deste slot."""
                factor = day_eng_factor.get(slot_dt.weekday(), 1.0)
                return {h: min(99, int(s * factor)) for h, s in live_scores.items()}

            cols_n = min(n, 7)
            gc = st.columns(cols_n)
            for i, (slot, fv) in enumerate(zip(auto_slots, files)):
                with gc[i % cols_n]:
                    wknd = slot.weekday() in [5,6]
                    # Engagement especifico para a hora e dia deste slot
                    day_scores = slot_scores(slot)
                    hour_label = slot.strftime("%H:%M")
                    eng = day_scores.get(hour_label, live_scores.get(hour_label, 50))
                    if eng >= 80:
                        bc = "#ff2d55"; bg2 = "rgba(255,45,85,.09)"; br2 = "#ff2d5566"
                        eng_color = "#ff2d55"; eng_icon = "🔥"
                    elif eng >= 65:
                        bc = "#a78bfa"; bg2 = "rgba(124,58,237,.09)"; br2 = "#7c3aed55"
                        eng_color = "#a78bfa"; eng_icon = "⚡"
                    else:
                        bc = "#00f5d4"; bg2 = "rgba(0,245,212,.06)"; br2 = "#00f5d444"
                        eng_color = "#00f5d4"; eng_icon = "✓"
                    # Nome do video — aparece no topo do card como label principal
                    vname = fv.name
                    vname_short = (vname[:18] + "…") if len(vname) > 18 else vname
                    vname_noext = vname_short.rsplit(".", 1)[0] if "." in vname_short else vname_short
                    grp_color = base_color.get(base_name(vname), "#6b7280")
                    st.markdown(f"""
                    <div style='background:{bg2};border:1px solid {br2};border-radius:11px;
                      padding:.55rem .4rem;margin-bottom:5px;text-align:center;
                      transition:all .2s;'>
                      <div style='font-size:.62rem;color:#f0f0f8;font-weight:700;
                        margin-bottom:2px;line-height:1.3;white-space:normal;word-break:break-word;
                        background:rgba(0,0,0,.3);border-radius:5px;padding:2px 5px;
                        border-left:3px solid {grp_color};'
                        title='{vname}'>{vname_noext}</div>
                      <div style='font-size:.55rem;color:#6b7280;font-weight:600;
                        text-transform:uppercase;letter-spacing:.4px;'>{day_pt[slot.weekday()]} · #{i+1}</div>
                      <div style='font-family:Syne,sans-serif;font-size:1.0rem;font-weight:800;
                        color:{bc};line-height:1.15;'>{slot.strftime("%d/%m")}</div>
                      <div style='font-size:.6rem;color:#7c3aed;font-weight:700;
                        margin-top:1px;'>{hour_label}</div>
                      <div style='font-size:.6rem;color:{eng_color};font-weight:600;
                        margin:.2rem 0;'>{eng_icon} {eng}%</div>
                    </div>""", unsafe_allow_html=True)
        else:
            st.warning("⚠️ Sem datas disponíveis com esses parâmetros. Seleciona mais dias ou ajusta o período.")
            auto_slots = []

        slots    = auto_slots
        captions = [legenda_global] * len(slots)
        if legenda_individual and slots:
            st.markdown("---")
            st.markdown("<div class='sh'>✏️ Titulo por video</div>", unsafe_allow_html=True)
            for i, fv in enumerate(files[:len(slots)]):
                cap = st.text_area(f"#{i+1} — {fv.name[:38]}", height=58,
                                   value=legenda_global, key=f"cap_auto_{i}")
                captions[i] = cap

    # ═══════════════════════════════════════════════════════════════════════════
    # MANUAL
    # ═══════════════════════════════════════════════════════════════════════════
    else:
        today = datetime.now().date()
        st.markdown(f"<div class='sh'>📅 Datas individuais ({n} videos)</div>", unsafe_allow_html=True)
        suggested = suggest_dates(n)
        slots = []; captions = []
        for i, fv in enumerate(files):
            sug = suggested[i] if i < len(suggested) else today + timedelta(days=i+1)
            st.markdown(f"""
            <div style='background:#111118;border-left:3px solid #ff2d55;border-radius:10px;
              padding:.4rem 1rem .2rem;margin-bottom:.3rem;'>
              <span style='font-size:.8rem;font-weight:700;color:#ff2d55;'>#{i+1} — {fv.name[:52]}{"…" if len(fv.name)>52 else ""}</span>
            </div>""", unsafe_allow_html=True)
            mc1, mc2, mc3 = st.columns([2.5,1.5,1.3])
            with mc1:
                cap = st.text_area(f"Titulo #{i+1}", height=65, value=legenda_global,
                                   key=f"cap_m_{i}", placeholder="Titulo…")
                captions.append(cap)
            with mc2:
                d = st.date_input("Data", value=sug, min_value=today+timedelta(days=1), key=f"ld_{i}")
            with mc3:
                h = st.selectbox("Hora", HOUR_OPTIONS, index=HOUR_OPTIONS.index("20:00"), key=f"lh_{i}")
            slots.append(datetime.combine(d, hour_str_to_time(h)))

    # ── Definicoes TikTok (aplicado a todos) ──────────────────────────────────
    st.markdown("---")
    st.markdown("<div class='sh'>⚙️ Definicoes TikTok</div>", unsafe_allow_html=True)

    commercial_toggle_b = st.checkbox("Este conteudo promove a ti, um produto ou servico?", value=False, key="commercial_batch")
    your_brand_b = False
    branded_content_b = False
    commercial_valid_b = True
    if commercial_toggle_b:
        ccb1, ccb2 = st.columns(2)
        with ccb1:
            your_brand_b = st.checkbox("Your brand", value=False, key="commercial_your_batch")
        with ccb2:
            branded_content_b = st.checkbox("Branded content", value=False, key="commercial_branded_batch")

        if your_brand_b and branded_content_b:
            st.info("Your photo/video will be labeled as 'Paid partnership'")
        elif your_brand_b:
            st.info("Your photo/video will be labeled as 'Promotional content'")
        elif branded_content_b:
            st.info("Your photo/video will be labeled as 'Paid partnership'")
        else:
            commercial_valid_b = False
            st.warning("Seleciona 'Your brand', 'Branded content', ou ambos.")

    privacy_options_b = list(_creator_flags.get("privacy_options") or [])
    if commercial_toggle_b and branded_content_b:
        privacy_options_b = [p for p in privacy_options_b if p != "SELF_ONLY"]
    if not privacy_options_b:
        st.warning("Nao foi possivel carregar opcoes de privacidade do creator_info.")
    privacy_key_b = "privacy_batch"
    if privacy_key_b in st.session_state and st.session_state[privacy_key_b] not in privacy_options_b:
        del st.session_state[privacy_key_b]
    privacy_choice_b = st.selectbox(
        "Privacidade",
        privacy_options_b,
        index=None,
        placeholder="Seleciona...",
        key=privacy_key_b,
        format_func=lambda x: PRIVACY_LABELS.get(x, x)
    )

    allow_comment_b = st.checkbox("Permitir comentarios", value=False,
                                  disabled=_creator_flags.get("comment_disabled", False),
                                  help="Desativado nas definicoes do criador" if _creator_flags.get("comment_disabled", False) else "",
                                  key="allow_comment_b")
    allow_duet_b = st.checkbox("Permitir duet", value=False,
                               disabled=_creator_flags.get("duet_disabled", False),
                               help="Desativado nas definicoes do criador" if _creator_flags.get("duet_disabled", False) else "",
                               key="allow_duet_b")
    allow_stitch_b = st.checkbox("Permitir stitch", value=False,
                                 disabled=_creator_flags.get("stitch_disabled", False),
                                 help="Desativado nas definicoes do criador" if _creator_flags.get("stitch_disabled", False) else "",
                                 key="allow_stitch_b")

    consent_text_b = "By posting, you agree to TikTok's Music Usage Confirmation."
    if commercial_toggle_b and branded_content_b:
        consent_text_b = "By posting, you agree to TikTok's Branded Content Policy and Music Usage Confirmation."
    st.markdown(f"<div style='font-size:.75rem;color:#6b7280;margin:.4rem 0 .2rem;'>{consent_text_b}</div>", unsafe_allow_html=True)
    user_consent_b = st.checkbox("Concordo com a declaracao acima", value=False, key="consent_batch")
    st.markdown("<div style='font-size:.7rem;color:#6b7280;margin-top:.2rem;'>Apos publicar, pode demorar alguns minutos a aparecer no perfil.</div>", unsafe_allow_html=True)

    # ── Agendar ───────────────────────────────────────────────────────────────
    if slots:
        st.markdown("---")
        if st.button(f"🚀 AGENDAR {n} VIDEO{'S' if n>1 else ''}", use_container_width=True):
            errs = []
            today = datetime.now().date()
            if not _creator_info:
                errs.append("Nao foi possivel obter creator_info. Conecta a conta TikTok.")
            if not _creator_flags.get("can_post", True):
                errs.append("O criador nao pode publicar agora. Tenta mais tarde.")
            if privacy_choice_b is None:
                errs.append("Seleciona a privacidade (sem valor por defeito).")
            if commercial_toggle_b and not commercial_valid_b:
                errs.append("Seleciona o tipo de conteudo comercial.")
            if commercial_toggle_b and branded_content_b and privacy_choice_b == "SELF_ONLY":
                errs.append("Branded content nao pode ser privado.")
            if not user_consent_b:
                errs.append("Confirma o consentimento antes de publicar.")

            for i,(fv,dt,cap) in enumerate(zip(files, slots, captions)):
                if not cap.strip(): errs.append(f"#{i+1} titulo vazio")
                if dt.date() <= today: errs.append(f"#{i+1} data no passado")
            if errs:
                for e in errs: st.error(e)
            else:
                prog = st.progress(0, text="A validar…")
                tmp_paths = []
                max_dur = _creator_flags.get("max_duration")
                for i,(fv,dt,cap) in enumerate(zip(files,slots,captions)):
                    dest = os.path.join(VIDEOS_DIR, fv.name)
                    with open(dest,"wb") as fo: fo.write(fv.getbuffer())
                    tmp_paths.append(dest)
                    if max_dur:
                        dsec, derr = get_video_duration_sec(dest)
                        if dsec is None:
                            errs.append(f"#{i+1} nao foi possivel validar duracao ({derr})")
                        elif dsec > max_dur:
                            errs.append(f"#{i+1} duracao {int(dsec)}s excede max {int(max_dur)}s")
                    prog.progress((i+1)/n, text=f"Validado {i+1}/{n}")

                if errs:
                    for p in tmp_paths:
                        try:
                            if os.path.exists(p):
                                os.remove(p)
                        except Exception:
                            pass
                    for e in errs: st.error(e)
                else:
                    prog.progress(0, text="A guardar…")
                    for i,(fv,dt,cap) in enumerate(zip(files,slots,captions)):
                        dest = tmp_paths[i]
                        meta = {
                            "privacy_level": privacy_choice_b,
                            "allow_comment": bool(allow_comment_b),
                            "allow_duet": bool(allow_duet_b),
                            "allow_stitch": bool(allow_stitch_b),
                            "commercial_toggle": bool(commercial_toggle_b),
                            "commercial_your_brand": bool(your_brand_b),
                            "commercial_branded_content": bool(branded_content_b),
                            "user_consent": bool(user_consent_b),
                            "consent_text": consent_text_b,
                            "creator_nickname": _creator_flags.get("nickname", "")
                        }
                        add_post(dest, cap, hashtags, dt.isoformat(), meta=meta)
                        prog.progress((i+1)/n, text=f"Agendado {i+1}/{n}")
                    prog.empty()
                    st.success(f"✅ {n} videos agendados!")
                    st.balloons()

# ════════════════════════════════════════════════════════════════════════════════
# PAGE: CALENDARIO
# ════════════════════════════════════════════════════════════════════════════════
elif page == "📅 Calendario":
    st.markdown("<div class='pt'>📅 Calendario</div>", unsafe_allow_html=True)
    st.markdown("<div class='ps'>Arrasta os posts para mudar de hora — clica para apagar. Heatmap de engagement em tempo real.</div>", unsafe_allow_html=True)

    # ── Fetch live engagement data via pytrends / fallback estático ───────────
    # ── Dados de engagement PT — recalcula por hora, usa dia da semana actual ─
    # BUG FIX: sem cache preso — recalcula cada vez que a pagina abre
    # Scores variam por dia da semana (seg-sex vs fds) + hora
    # BUG FIX: recebe a data alvo (start_from) para calcular scores do dia correto
    def get_live_engagement_pt(target_date=None):
        """Calcula scores de engagement para a data-alvo especifica (nao hoje)."""
        if target_date is None:
            target_date = datetime.now().date()
        dow = target_date.weekday()   # 0=Seg … 6=Dom — usa DATA ALVO
        is_weekend = dow >= 5

        # Base PT por hora (estudos 2023-2024)
        base = {
            "07:00":42,"07:30":58,"08:00":51,"08:30":45,
            "09:00":38,"09:30":35,"10:00":33,"10:30":31,
            "11:00":30,"11:30":32,"12:00":55,"12:15":62,
            "12:30":58,"13:00":50,"13:30":41,"14:00":37,
            "15:00":35,"16:00":40,"16:30":48,"17:00":78,
            "17:30":82,"18:00":75,"18:30":70,"19:00":72,
            "19:30":80,"20:00":95,"20:30":91,"21:00":85,
            "21:30":83,"22:00":78,"22:30":72,"23:00":58,
            "23:30":44,
        }
        # Fim de semana: manhã mais alta, noite ligeiramente menor
        weekend_mult = {
            "07:00":1.3,"07:30":1.4,"08:00":1.35,"08:30":1.2,
            "09:00":1.3,"09:30":1.2,"10:00":1.25,"10:30":1.2,
            "11:00":1.2,"11:30":1.15,"12:00":1.1,"12:15":1.1,
            "12:30":1.05,"13:00":1.0,"13:30":1.0,"14:00":1.0,
            "15:00":1.0,"16:00":1.0,"16:30":1.05,"17:00":1.0,
            "17:30":1.0,"18:00":1.0,"18:30":1.0,"19:00":1.0,
            "19:30":1.0,"20:00":0.95,"20:30":0.95,"21:00":0.9,
            "21:30":0.9,"22:00":0.88,"22:30":0.85,"23:00":0.82,
            "23:30":0.78,
        }
        if is_weekend:
            scores = {h: min(99, int(v * weekend_mult.get(h, 1.0))) for h, v in base.items()}
        else:
            scores = dict(base)

        # Tenta pytrends para factor de escala real
        try:
            from pytrends.request import TrendReq
            pt = TrendReq(hl="pt-PT", tz=-60, timeout=(4,12))
            pt.build_payload(["TikTok"], cat=0, timeframe="now 7-d", geo="PT")
            df = pt.interest_over_time()
            if not df.empty and "TikTok" in df.columns:
                recent = df["TikTok"].tail(24).tolist()
                factor = sum(recent) / max(1, len(recent)) / 55.0
                factor = max(0.75, min(1.25, factor))
                scores = {h: min(99, int(v * factor)) for h, v in scores.items()}
        except Exception:
            pass

        return scores, dow, is_weekend

    # Usar start_from se estiver disponivel (pagina lote), senao hoje
    _target = st.session_state.get("ap_start_from", datetime.now().date())
    live_scores, current_dow, is_weekend = get_live_engagement_pt(_target)
    dow_names_pt = ["Segunda","Terça","Quarta","Quinta","Sexta","Sábado","Domingo"]
    day_type = f"Fim de semana 🎉" if is_weekend else f"{dow_names_pt[current_dow]} 📅"

    # Top horas ordenadas pelos scores actuais
    live_best = sorted(
        [{"label": h, "score": s} for h, s in live_scores.items()],
        key=lambda x: -x["score"]
    )[:8]

    # ── Calendário ────────────────────────────────────────────────────────────
    q = load_queue()
    events = []
    colors = {"scheduled":"#7c3aed","posted":"#22c55e","failed":"#ff2d55","pending":"#f59e0b"}
    for post in q:
        try:
            nm  = os.path.basename(post.get("video_path",""))
            col = colors.get(post.get("status","scheduled"),"#7c3aed")
            hour_str = datetime.fromisoformat(post["scheduled_at"]).strftime("%H:%M")
            eng = live_scores.get(hour_str, 50)
            # Cor varia por engagement
            if post.get("status") == "scheduled":
                if eng >= 80:   col = "#ff2d55"
                elif eng >= 65: col = "#7c3aed"
                else:           col = "#00f5d4"
            events.append({
                "id": post["id"],
                "title": f"🎬 {nm[:18]}",
                "start": post["scheduled_at"],
                "backgroundColor": col,
                "borderColor": col,
                "editable": post.get("status") == "scheduled",
                "startEditable": post.get("status") == "scheduled",
                "extendedProps": {
                    "status": post.get("status",""),
                    "caption": post.get("caption","")[:60],
                    "video": nm,
                    "engagement": eng,
                }
            })
        except: pass

    events_json = json.dumps(events)

    # Heatmap por hora para o background do calendário
    heatmap_slots = []
    for h_str, score in live_scores.items():
        try:
            parts = h_str.split(":")
            h, m = int(parts[0]), int(parts[1])
            if score >= 80:
                alpha = 0.13
                color = f"rgba(255,45,85,{alpha})"
            elif score >= 65:
                alpha = 0.09
                color = f"rgba(124,58,237,{alpha})"
            elif score >= 50:
                alpha = 0.06
                color = f"rgba(0,245,212,{alpha})"
            else:
                color = "transparent"
            if color != "transparent":
                heatmap_slots.append({"time": h_str, "color": color, "score": score})
        except: pass
    heatmap_json = json.dumps(heatmap_slots)

    cal_html = f"""<!DOCTYPE html><html><head><meta charset='utf-8'>
<link href='https://cdn.jsdelivr.net/npm/fullcalendar@6.1.11/index.global.min.css' rel='stylesheet'>
<script src='https://cdn.jsdelivr.net/npm/fullcalendar@6.1.11/index.global.min.js'></script>
<style>
*{{box-sizing:border-box;margin:0;padding:0;}}
body{{background:#0a0a0f;font-family:'Space Grotesk',sans-serif;padding:8px;}}

/* ── FullCalendar base dark theme ── */
.fc{{
  --fc-border-color:#1e1e2e;
  --fc-today-bg-color:rgba(255,45,85,.08);
  --fc-page-bg-color:#0a0a0f;
  --fc-neutral-bg-color:#111118;
  --fc-now-indicator-color:#ff2d55;
  color:#f0f0f8;
}}
.fc-toolbar-title{{font-size:1.05rem!important;font-weight:800;color:#f0f0f8;
  font-family:'Space Grotesk',sans-serif;}}
.fc-button-primary{{
  background:linear-gradient(135deg,#ff2d55,#7c3aed)!important;
  border:none!important;border-radius:8px!important;
  font-weight:700!important;font-size:.76rem!important;
  padding:.35rem .75rem!important;transition:all .2s!important;}}
.fc-button-primary:hover{{transform:translateY(-1px)!important;
  box-shadow:0 4px 15px rgba(255,45,85,.3)!important;}}
.fc-button-active{{background:linear-gradient(135deg,#7c3aed,#ff2d55)!important;}}

/* ── Column headers ── */
.fc-col-header-cell{{
  background:linear-gradient(180deg,#111118,#0d0d14)!important;
  border-bottom:2px solid #1e1e2e!important;padding:.4rem 0!important;}}
.fc-col-header-cell-cushion{{
  color:#f0f0f8!important;font-size:.72rem!important;
  font-weight:700!important;text-transform:uppercase!important;
  letter-spacing:.8px!important;text-decoration:none!important;}}

/* ── Day grid ── */
.fc-daygrid-day{{background:#111118!important;}}
.fc-daygrid-day.fc-day-today{{background:rgba(255,45,85,.05)!important;}}
.fc-daygrid-day-number{{color:#6b7280!important;font-size:.78rem!important;font-weight:600!important;}}

/* ── Time grid ── */
.fc-timegrid-slot{{border-color:#1a1a26!important;min-height:28px!important;}}
.fc-timegrid-slot-minor{{border-color:#141420!important;}}
.fc-timegrid-slot-label{{color:#6b7280!important;font-size:.68rem!important;font-weight:500!important;}}
.fc-timegrid-col{{background:#0d0d14!important;}}
.fc-timegrid-col.fc-day-today{{background:rgba(255,45,85,.04)!important;}}

/* ── Events ── */
.fc-event{{
  border-radius:7px!important;border:none!important;
  padding:3px 6px!important;cursor:grab!important;
  font-size:.74rem!important;font-weight:600!important;
  box-shadow:0 2px 8px rgba(0,0,0,.4)!important;
  transition:transform .15s,box-shadow .15s!important;}}
.fc-event:hover{{
  transform:translateY(-1px) scale(1.02)!important;
  box-shadow:0 4px 16px rgba(0,0,0,.6)!important;}}
.fc-event-title{{font-weight:700!important;}}

/* ── Now indicator ── */
.fc-timegrid-now-indicator-line{{
  border-color:#ff2d55!important;border-width:2px!important;}}
.fc-timegrid-now-indicator-arrow{{border-top-color:#ff2d55!important;}}

/* ── Scrollbar ── */
::-webkit-scrollbar{{width:4px;height:4px;}}
::-webkit-scrollbar-track{{background:#0a0a0f;}}
::-webkit-scrollbar-thumb{{background:#1e1e2e;border-radius:2px;}}

/* ── Tooltip ── */
#tip{{
  position:fixed;background:#111118;
  border:1px solid #2a2a3e;border-radius:12px;
  padding:10px 14px;font-size:.76rem;color:#f0f0f8;
  pointer-events:none;z-index:9999;display:none;
  max-width:220px;box-shadow:0 8px 32px rgba(0,0,0,.7);
  backdrop-filter:blur(10px);}}
#tip .tv{{font-weight:800;color:#ff2d55;margin-bottom:4px;font-size:.82rem;}}
#tip .tt{{color:#00f5d4;font-size:.7rem;margin-bottom:3px;font-weight:600;}}
#tip .tc{{color:#a0a0b8;font-size:.68rem;line-height:1.4;margin-bottom:4px;}}
#tip .te{{font-size:.68rem;font-weight:700;padding:2px 7px;border-radius:20px;
  display:inline-block;margin-top:2px;}}

/* ── Toast ── */
#toast{{
  position:fixed;bottom:20px;right:20px;
  padding:.6rem 1.1rem;border-radius:10px;
  font-size:.8rem;font-weight:700;
  opacity:0;transition:opacity .3s;z-index:99999;pointer-events:none;
  box-shadow:0 4px 20px rgba(0,0,0,.5);}}

/* ── Heatmap slot highlights ── */
.fc-timegrid-slot.hot-slot{{position:relative;}}
</style></head><body>
<div id="tip">
  <div class="tv" id="tv"></div>
  <div class="tt" id="tt"></div>
  <div class="tc" id="tc"></div>
  <div class="te" id="te"></div>
</div>
<div id="toast"></div>
<div id="delModal" style="display:none;position:fixed;inset:0;background:rgba(0,0,0,.75);z-index:99999;align-items:center;justify-content:center;">
  <div style="background:#111118;border:1px solid #2a2a3e;border-radius:16px;padding:1.6rem 2rem;max-width:340px;width:90%;text-align:center;">
    <div style="font-size:1.5rem;margin-bottom:.5rem;">🗑️</div>
    <div style="color:#f0f0f8;font-weight:700;margin-bottom:.4rem;">Apagar post?</div>
    <div id="delMsg" style="color:#6b7280;font-size:.82rem;margin-bottom:1.2rem;word-break:break-word;"></div>
    <div style="display:flex;gap:.7rem;justify-content:center;">
      <button id="delCancel" style="padding:.5rem 1.2rem;background:#1e1e2e;border:1px solid #2a2a3e;border-radius:9px;color:#6b7280;cursor:pointer;font-size:.85rem;">Cancelar</button>
      <button id="delConfirm" style="padding:.5rem 1.2rem;background:linear-gradient(135deg,#ff2d55,#7c3aed);border:none;border-radius:9px;color:white;cursor:pointer;font-size:.85rem;font-weight:700;">Apagar</button>
    </div>
  </div>
</div>
<div id='cal'></div>
<script>
const EVENTS = {events_json};
const HEATMAP = {heatmap_json};

function showToast(msg, color){{
  const t = document.getElementById('toast');
  t.textContent = msg;
  t.style.background = color || '#22c55e';
  t.style.color = 'white';
  t.style.opacity = '1';
  setTimeout(() => t.style.opacity = '0', 2800);
}}
function updateParent(params){{
  // Constrói URL com query params e navega no top frame (Streamlit)
  try {{
    const base = window.top.location.href.split('?')[0];
    const qs   = new URLSearchParams(params).toString();
    window.top.location.replace(base + '?' + qs);
  }} catch(e) {{
    try {{
      const base = window.parent.location.href.split('?')[0];
      const qs   = new URLSearchParams(params).toString();
      window.parent.location.replace(base + '?' + qs);
    }} catch(e2) {{
      console.error('updateParent failed', e2);
    }}
  }}
}}
function engColor(score){{
  if(score >= 80) return {{bg:'rgba(255,45,85,.15)',text:'#ff2d55',label:'🔥 ' + score + '% engagement'}};
  if(score >= 65) return {{bg:'rgba(124,58,237,.12)',text:'#a78bfa',label:'⚡ ' + score + '% engagement'}};
  if(score >= 50) return {{bg:'rgba(0,245,212,.08)',text:'#00f5d4',label:'✓ ' + score + '% engagement'}};
  return {{bg:'transparent',text:'#6b7280',label:score + '% engagement'}};
}}

document.addEventListener('DOMContentLoaded', function(){{
  const calEl = document.getElementById('cal');
  const cal = new FullCalendar.Calendar(calEl, {{
    initialView: 'timeGridWeek',
    headerToolbar: {{
      left: 'prev,next today',
      center: 'title',
      right: 'dayGridMonth,timeGridWeek,timeGridDay'
    }},
    locale: 'pt',
    firstDay: 1,
    height: 700,
    slotMinTime: '06:00:00',
    slotMaxTime: '24:00:00',
    slotDuration: '00:30:00',
    snapDuration: '00:15:00',
    allDaySlot: false,
    nowIndicator: true,
    expandRows: true,
    events: EVENTS,

    // Colorir slots por engagement
    slotLaneDidMount: function(info) {{
      const timeStr = info.date.toTimeString().slice(0,5);
      const slot = HEATMAP.find(h => h.time === timeStr);
      if(slot) {{
        info.el.style.background = slot.color;
        info.el.style.borderLeft = slot.score >= 80 ? '2px solid rgba(255,45,85,.4)' : 'none';
      }}
    }},

    eventDrop: function(info) {{
      if(!info.event.startEditable) {{ info.revert(); return; }}
      const iso = info.event.start.toISOString().slice(0, 19);
      showToast('✅ A reagendar...', '#7c3aed');
      updateParent({{reschedule_id: info.event.id, reschedule_start: iso}});
    }},

        eventClick: function(info) {{
      const modal    = document.getElementById('delModal');
      const modalMsg = document.getElementById('delMsg');
      modalMsg.textContent = info.event.extendedProps.video || info.event.title;
      modal.style.display  = 'flex';
      document.getElementById('delConfirm').onclick = function() {{
        modal.style.display = 'none';
        showToast('🗑 Removido', '#ff2d55');
        updateParent({{delete_id: info.event.id}});
      }};
      document.getElementById('delCancel').onclick = function() {{
        modal.style.display = 'none';
      }};
    }},

    eventMouseEnter: function(info) {{
      const ep = info.event.extendedProps;
      const t = document.getElementById('tip');
      const ec = engColor(ep.engagement || 50);
      document.getElementById('tv').textContent = ep.video || info.event.title;
      document.getElementById('tt').textContent = info.event.start
        ? info.event.start.toLocaleString('pt-PT', {{
            weekday:'short', day:'2-digit', month:'2-digit',
            hour:'2-digit', minute:'2-digit'
          }}) : '';
      document.getElementById('tc').textContent = ep.caption || '';
      const teEl = document.getElementById('te');
      teEl.textContent = ec.label;
      teEl.style.background = ec.bg;
      teEl.style.color = ec.text;
      teEl.style.border = '1px solid ' + ec.text + '44';
      t.style.display = 'block';
    }},

    eventMouseLeave: function() {{
      document.getElementById('tip').style.display = 'none';
    }},

    // Destacar horas ao passar o rato no slot
    slotLaneMouseEnter: function(info) {{
      const timeStr = info.date.toTimeString().slice(0,5);
      const slot = HEATMAP.find(h => h.time === timeStr);
      if(slot && slot.score >= 65) {{
        info.el.style.filter = 'brightness(1.4)';
        info.el.title = 'Engagement: ' + slot.score + '%';
      }}
    }},
    slotLaneMouseLeave: function(info) {{
      info.el.style.filter = '';
    }},
  }});

  cal.render();

  // Tooltip segue o rato
  document.addEventListener('mousemove', function(e) {{
    const t = document.getElementById('tip');
    if(t.style.display === 'block') {{
      const x = e.clientX + 16;
      const y = e.clientY - 10;
      const maxX = window.innerWidth - 240;
      t.style.left = Math.min(x, maxX) + 'px';
      t.style.top = y + 'px';
    }}
  }});
}});
</script></body></html>"""

    components.html(cal_html, height=730, scrolling=False)

    # ── Legenda de engagement ─────────────────────────────────────────────────
    wknd_note = " — padrão fim de semana (manhã +forte)" if is_weekend else " — padrão dia útil"
    st.markdown(f"<div class='sh' style='margin-top:.8rem;'>🔥 Melhores horas agora · {day_type}{wknd_note}</div>", unsafe_allow_html=True)

    top_cols = st.columns(min(len(live_best), 8))
    for i, (col, t) in enumerate(zip(top_cols, live_best)):
        score = t["score"]
        if score >= 80:   bc, bg = "#ff2d55", "rgba(255,45,85,.1)"
        elif score >= 65: bc, bg = "#a78bfa", "rgba(124,58,237,.1)"
        else:             bc, bg = "#00f5d4", "rgba(0,245,212,.08)"
        medal = ["🥇","🥈","🥉","4️⃣","5️⃣","6️⃣","7️⃣","8️⃣"][i]
        with col:
            st.markdown(f"""
            <div style='background:{bg};border:1px solid {bc}44;border-radius:11px;
              padding:.7rem .5rem;text-align:center;'>
              <div style='font-size:.9rem;'>{medal}</div>
              <div style='font-family:Syne,sans-serif;font-size:1.05rem;font-weight:800;
                color:{bc};line-height:1;'>{t["label"]}</div>
              <div style='background:#1e1e2e;border-radius:3px;height:3px;
                overflow:hidden;margin:.4rem 0 .2rem;'>
                <div style='height:100%;width:{score}%;background:{bc};border-radius:3px;'></div></div>
              <div style='font-size:.7rem;color:{bc};font-weight:700;'>{score}%</div>
            </div>""", unsafe_allow_html=True)

    st.markdown("""
    <div style='display:flex;gap:1.2rem;flex-wrap:wrap;padding:.6rem .9rem;background:#111118;
      border-radius:10px;border:1px solid #1e1e2e;margin-top:.6rem;align-items:center;font-size:.75rem;'>
      <span>🟥 <b style='color:#ff2d55;'>≥80%</b> Prime time</span>
      <span>🟣 <b style='color:#a78bfa;'>≥65%</b> Bom</span>
      <span>🟦 <b style='color:#00f5d4;'>≥50%</b> OK</span>
      <span style='color:#6b7280;margin-left:auto;'>⏰ Arrastar guarda | 🖱️ Clique apaga</span>
    </div>""", unsafe_allow_html=True)


# ════════════════════════════════════════════════════════════════════════════════
# PAGE: FILA
# ════════════════════════════════════════════════════════════════════════════════
elif page == "📋 Fila de Posts":
    st.markdown("<div class='pt'>📋 Fila de Posts</div>", unsafe_allow_html=True)
    st.markdown("<div class='ps'>Todos os posts agendados, publicados e falhados</div>", unsafe_allow_html=True)
    st.markdown("<div style='font-size:.78rem;color:#6b7280;margin-bottom:.6rem;'>Apos publicar, pode demorar alguns minutos a aparecer no perfil.</div>", unsafe_allow_html=True)

    q = load_queue()
    t1,t2,t3,t4 = st.tabs([f"Todos ({len(q)})",
        f"⏳ Agendados ({len([p for p in q if p['status']=='scheduled'])})",
        f"✅ Publicados ({len([p for p in q if p['status']=='posted'])})",
        f"❌ Falhados ({len([p for p in q if p['status']=='failed'])})"])

    dpt = ["Seg","Ter","Qua","Qui","Sex","Sab","Dom"]

    def render_list(posts, tab_key=""):
        if not posts:
            st.markdown("<div style='text-align:center;padding:3rem;color:#6b7280;'><div style='font-size:2.5rem;'>📭</div><div>Sem posts</div></div>", unsafe_allow_html=True)
            return
        for post in sorted(posts, key=lambda x: x.get("scheduled_at","")):
            try:
                dt = datetime.fromisoformat(post["scheduled_at"])
                dow = dpt[dt.weekday()]
                ds = f"{dow} {dt.strftime('%d/%m/%Y')}"; ts = dt.strftime("%H:%M")
            except: ds="—"; ts="—"
            pst = post.get("status","scheduled")
            cc  = {"scheduled":"#00f5d4","posted":"#22c55e","failed":"#ff2d55","pending":"#f59e0b"}.get(pst,"#6b7280")
            lb  = {"scheduled":"Agendado","posted":"Publicado","failed":"Falhado","pending":"A enviar"}.get(pst,pst)
            nm  = os.path.basename(post.get("video_path",""))
            cap = post.get("caption","")[:80]
            tg  = post.get("hashtags","")
            err = post.get("error","")
            retry_ct = post.get("retry_count", 0)
            retry_html = f"<div style='font-size:.65rem;color:#f59e0b;margin-top:2px;'>🔄 Tentativa {retry_ct}/3 — próxima em breve</div>" if retry_ct and pst=="scheduled" else ""
            err_html = f"<div style='font-size:.68rem;color:#ff2d55;margin-top:2px;'>⚠️ {err[:80]}</div>" if err and pst in ("failed","scheduled") else ""

            c1, c2 = st.columns([11,3])
            with c1:
                st.markdown(f"""
                <div style='display:flex;align-items:flex-start;gap:.9rem;padding:.85rem 1rem;
                  background:#111118;border-radius:11px;margin-bottom:4px;
                  border:1px solid #1e1e2e;border-left:3px solid {cc};'>
                  <div style='min-width:70px;background:#16161f;border-radius:8px;
                    padding:.35rem .6rem;text-align:center;flex-shrink:0;'>
                    <div style='font-family:Syne,sans-serif;font-size:1.15rem;font-weight:800;
                      color:{cc};line-height:1;'>{ts}</div>
                    <div style='font-size:.6rem;color:#6b7280;margin-top:2px;'>{ds}</div>
                  </div>
                  <div style='flex:1;min-width:0;'>
                    <div style='font-weight:600;font-size:.86rem;color:#f0f0f8;
                      white-space:nowrap;overflow:hidden;text-overflow:ellipsis;'>&#127916; {nm}</div>
                    <div style='font-size:.76rem;color:#6b7280;margin-top:2px;line-height:1.4;'>{cap}</div>
                    <div style='font-size:.7rem;color:#7c3aed;margin-top:2px;'>{tg}</div>
                    {retry_html}
                    {err_html}
                  </div>
                  <div style='padding:.2rem .55rem;border-radius:20px;font-size:.67rem;font-weight:700;
                    text-transform:uppercase;letter-spacing:.5px;flex-shrink:0;
                    background:rgba(0,0,0,.3);color:{cc};border:1px solid {cc}44;'>{lb}</div>
                </div>""", unsafe_allow_html=True)
            with c2:
                if pst in ("scheduled", "failed"):
                    consent_text = post.get("consent_text") or "By posting, you agree to TikTok's Music Usage Confirmation."
                    if post.get("commercial_branded_content"):
                        consent_text = "By posting, you agree to TikTok's Branded Content Policy and Music Usage Confirmation."
                    st.markdown(f"<div style='font-size:.7rem;color:#6b7280;margin:.2rem 0;'>{consent_text}</div>", unsafe_allow_html=True)
                    consent_now = st.checkbox("Concordo", value=False, key=f"consent_now_{tab_key}_{post['id']}")
                    if st.button("Postar agora", key=f"post_now_{tab_key}_{post['id']}", use_container_width=True, disabled=not consent_now):
                        q_all = load_queue()
                        for _p in q_all:
                            if _p.get("id") == post.get("id"):
                                _p["user_consent"] = True
                                _p["consent_text"] = consent_text
                        save_queue(q_all)
                        with st.spinner("A publicar agora..."):
                            ok_now, msg_now = tk_scheduler.post_now(post["id"])
                        if ok_now:
                            st.success("Post enviado para publicacao.")
                        else:
                            st.error(msg_now)
                        st.rerun()
                if st.button("🗑", key=f"d_{tab_key}_{post['id']}"):
                    save_queue([p for p in load_queue() if p["id"]!=post["id"]]); st.rerun()

    with t1: render_list(q, 'all')
    with t2: render_list([p for p in q if p["status"]=="scheduled"])
    with t3: render_list([p for p in q if p["status"]=="posted"])
    with t4: render_list([p for p in q if p["status"]=="failed"])

    if q:
        st.markdown("---")
        ca,cb,cc2 = st.columns(3)
        with ca:
            if st.button("📥 Exportar JSON", use_container_width=True):
                st.download_button("⬇️ Download",data=json.dumps(q,indent=2,ensure_ascii=False),
                                   file_name="queue.json",mime="application/json")
        with cb:
            if st.button("🧹 Limpar Publicados", use_container_width=True):
                save_queue([p for p in q if p["status"]!="posted"]); st.rerun()
        with cc2:
            if st.button("🔄 Tentar Falhados", use_container_width=True):
                nq = load_queue()
                for p in nq:
                    if p["status"]=="failed": p["status"]="scheduled"; p["error"]=None
                save_queue(nq); st.rerun()


# ════════════════════════════════════════════════════════════════════════════════
# PAGE: VER NO TIKTOK
# ════════════════════════════════════════════════════════════════════════════════
elif page == "📱 Ver no TikTok":
    st.markdown("<div class='pt'>📱 Ver no TikTok</div>", unsafe_allow_html=True)
    st.markdown("<div class='ps'>Abre os teus vídeos e rascunhos diretamente no TikTok — sem sair da app</div>", unsafe_allow_html=True)

    config   = load_config()
    username = config.get("connected_display_name", "")
    q_all    = load_queue()
    posted   = sorted([p for p in q_all if p.get("status") == "posted"],
                      key=lambda x: x.get("posted_at", ""), reverse=True)
    scheduled = sorted([p for p in q_all if p.get("status") == "scheduled"],
                       key=lambda x: x.get("scheduled_at", ""))
    sandbox  = config.get("sandbox_mode", False)

    # ── Atalhos rápidos ───────────────────────────────────────────────────────
    st.markdown("<div class='sh'>⚡ Atalhos TikTok</div>", unsafe_allow_html=True)

    profile_url = f"https://www.tiktok.com/@{username}" if username else "https://www.tiktok.com/profile"
    drafts_url  = "https://www.tiktok.com/creator-center/content?tab=draft"
    creator_url = "https://www.tiktok.com/creator-center/content"

    qa, qb, qc = st.columns(3)
    with qa:
        st.link_button("👤 O meu Perfil", profile_url, use_container_width=True)
    with qb:
        st.link_button("📝 Rascunhos",    drafts_url,  use_container_width=True)
    with qc:
        st.link_button("🎬 Conteúdo",     creator_url, use_container_width=True)


    if sandbox:
        st.info("🧪 Modo Sandbox ativo — os posts aparecem como **Rascunhos**. Clica em Rascunhos acima para os ver.")

    st.markdown("---")

    # ── Posts publicados ──────────────────────────────────────────────────────
    st.markdown(f"<div class='sh'>✅ Publicados ({len(posted)})</div>", unsafe_allow_html=True)

    if not posted:
        st.markdown("<div style='text-align:center;padding:2rem;color:#6b7280;'>Ainda sem posts publicados</div>", unsafe_allow_html=True)
    else:
        for p in posted[:20]:
            nm   = os.path.basename(p.get("video_path", ""))
            cap  = p.get("caption", "")[:60]
            pid  = p.get("publish_id", "")
            try:
                pat = datetime.fromisoformat(p["posted_at"]).strftime("%d/%m/%Y %H:%M")
            except:
                pat = "—"
            tiktok_url = drafts_url if sandbox else (f"https://www.tiktok.com/@{username}" if username else creator_url)
            # Debug: log username
            if not username: tiktok_url = creator_url
            btn_label  = "📝 Ver Rascunho" if sandbox else "👁️ Ver no TikTok"
            pid_html   = f"<span style='font-family:monospace;'>{str(pid)[:20]}</span>" if pid else ""
            st.markdown(f"""
            <div style='display:flex;align-items:center;gap:.9rem;padding:.7rem 1rem;
              background:#111118;border-radius:11px;margin-bottom:4px;
              border:1px solid #22c55e33;border-left:3px solid #22c55e;'>
              <div style='flex:1;min-width:0;'>
                <div style='font-weight:600;font-size:.86rem;color:#f0f0f8;'>🎬 {nm[:45]}</div>
                <div style='font-size:.74rem;color:#6b7280;margin-top:2px;'>{cap}</div>
                <div style='font-size:.68rem;color:#6b7280;margin-top:2px;'>📅 {pat} {pid_html}</div>
              </div>
              <a href="{tiktok_url}" target="_blank"
                style='padding:.4rem .9rem;background:rgba(34,197,94,.12);
                border:1px solid #22c55e44;border-radius:8px;color:#22c55e;
                font-size:.78rem;font-weight:700;text-decoration:none;
                white-space:nowrap;'>{btn_label}</a>
            </div>""", unsafe_allow_html=True)

    st.markdown("---")

    # ── Posts agendados ───────────────────────────────────────────────────────
    st.markdown(f"<div class='sh'>⏳ Agendados ({len(scheduled)})</div>", unsafe_allow_html=True)

    if not scheduled:
        st.markdown("<div style='text-align:center;padding:1.5rem;color:#6b7280;'>Sem posts agendados</div>", unsafe_allow_html=True)
    else:
        for p in scheduled[:20]:
            nm  = os.path.basename(p.get("video_path", ""))
            cap = p.get("caption", "")[:60]
            try:
                sat   = datetime.fromisoformat(p["scheduled_at"])
                delta = sat - datetime.now()
                h = int(delta.total_seconds() // 3600)
                m = int((delta.total_seconds() % 3600) // 60)
                sat_str   = sat.strftime("%d/%m/%Y %H:%M")
                countdown = f"{h}h {m}m" if delta.total_seconds() > 0 else "A publicar..."
            except:
                sat_str = "—"; countdown = "—"
            st.markdown(f"""
            <div style='display:flex;align-items:center;gap:.9rem;padding:.7rem 1rem;
              background:#111118;border-radius:11px;margin-bottom:4px;
              border:1px solid #7c3aed33;border-left:3px solid #7c3aed;'>
              <div style='flex:1;min-width:0;'>
                <div style='font-weight:600;font-size:.86rem;color:#f0f0f8;'>🎬 {nm[:45]}</div>
                <div style='font-size:.74rem;color:#6b7280;margin-top:2px;'>{cap}</div>
                <div style='font-size:.68rem;color:#6b7280;margin-top:2px;'>📅 {sat_str}</div>
              </div>
              <div style='text-align:center;padding:.3rem .7rem;background:rgba(124,58,237,.1);
                border:1px solid #7c3aed44;border-radius:8px;'>
                <div style='font-family:Syne,sans-serif;font-size:.95rem;font-weight:800;color:#a78bfa;'>{countdown}</div>
                <div style='font-size:.6rem;color:#6b7280;'>para publicar</div>
              </div>
            </div>""", unsafe_allow_html=True)



# ════════════════════════════════════════════════════════════════════════════════
# PAGE: VERIFICACAO
# ════════════════════════════════════════════════════════════════════════════════
elif page == "🔍 Verificacao":
    st.markdown("<div class='pt'>🔍 Verificacao Pre-Publicacao</div>", unsafe_allow_html=True)
    st.markdown("<div class='ps'>Testa tudo antes de agendar — garante zero falhas na hora de publicar</div>", unsafe_allow_html=True)

    config = load_config()
    has_creds = bool(config.get("access_token") and config.get("open_id"))

    # ── 1. Estado das credenciais ─────────────────────────────────────────────
    st.markdown("<div class='sh'>1️⃣ Credenciais TikTok</div>", unsafe_allow_html=True)

    cred_fields = {
        "Client Key":    config.get("client_key",""),
        "Client Secret": config.get("client_secret",""),
        "Access Token":  config.get("access_token",""),
        "Open ID":       config.get("open_id",""),
    }
    all_filled = all(v for v in cred_fields.values())

    cred_cols = st.columns(4)
    for (label, val), col in zip(cred_fields.items(), cred_cols):
        ok = bool(val)
        with col:
            icon = "✅" if ok else "❌"
            color = "#22c55e" if ok else "#ff2d55"
            preview = ("●●●●" + val[-4:]) if ok and len(val) > 4 else ("Vazio" if not ok else val)
            st.markdown(f"""
            <div style='background:#111118;border:1px solid {"#22c55e44" if ok else "#ff2d5544"};
              border-radius:10px;padding:.7rem .9rem;text-align:center;'>
              <div style='font-size:1.2rem;'>{icon}</div>
              <div style='font-size:.72rem;color:#6b7280;text-transform:uppercase;letter-spacing:.5px;'>{label}</div>
              <div style='font-size:.75rem;color:{color};margin-top:2px;font-weight:600;'>{preview}</div>
            </div>""", unsafe_allow_html=True)

    if not all_filled:
        st.warning("⚠️ Preenche todas as credenciais em ⚙️ Configuracoes antes de testar.")

    st.markdown("<br>", unsafe_allow_html=True)

    # ── 2. Teste de conexao API ────────────────────────────────────────────────
    st.markdown("<div class='sh'>2️⃣ Teste de Conexao ao TikTok</div>", unsafe_allow_html=True)

    col_test, col_result = st.columns([1, 2])
    with col_test:
        test_api = st.button("🔌 Testar API agora", use_container_width=True, disabled=not all_filled)

    if test_api or st.session_state.get("api_test_result"):
        if test_api:
            with st.spinner("A testar conexao ao TikTok..."):
                try:
                    import requests as req
                    headers = {
                        "Authorization": f"Bearer {config['access_token']}",
                        "Content-Type": "application/json; charset=UTF-8"
                    }
                    resp = req.post(
                        "https://open.tiktokapis.com/v2/post/publish/creator_info/query/",
                        headers=headers, json={}, timeout=10
                    )
                    data = resp.json()
                    err_code = data.get("error", {}).get("code", "")
                    err_msg  = data.get("error", {}).get("message", "")

                    if err_code == "ok":
                        creator = data.get("data", {})
                        nickname = creator.get("creator_nickname", "—")
                        st.session_state["api_test_result"] = ("ok", f"Ligado como: {nickname}")
                    elif err_code == "access_token_invalid":
                        st.session_state["api_test_result"] = ("fail", "Access Token invalido ou expirado. Gera um novo em developers.tiktok.com")
                    elif err_code == "scope_not_authorized":
                        st.session_state["api_test_result"] = ("fail", "Token sem permissao video.upload. Regenera com o scope correto.")
                    elif resp.status_code == 401:
                        st.session_state["api_test_result"] = ("fail", "Autenticacao rejeitada (401). Verifica o Access Token.")
                    else:
                        st.session_state["api_test_result"] = ("warn", f"Resposta inesperada: {err_code} — {err_msg}")
                except req.exceptions.ConnectionError:
                    st.session_state["api_test_result"] = ("fail", "Sem ligacao a internet.")
                except req.exceptions.Timeout:
                    st.session_state["api_test_result"] = ("fail", "Timeout — TikTok nao respondeu em 10s.")
                except Exception as e:
                    st.session_state["api_test_result"] = ("fail", f"Erro: {str(e)}")
            st.rerun()

        result = st.session_state.get("api_test_result")
        if result:
            status, msg = result
            if status == "ok":
                st.success(f"✅ {msg}")
            elif status == "warn":
                st.warning(f"⚠️ {msg}")
            else:
                st.error(f"❌ {msg}")
                st.markdown("""
                <div style='background:rgba(255,45,85,.06);border:1px solid rgba(255,45,85,.2);
                  border-radius:10px;padding:.8rem 1rem;margin-top:.5rem;font-size:.82rem;color:#6b7280;'>
                  <b style='color:#f0f0f8;'>Como corrigir:</b><br>
                  1. Vai a <b>developers.tiktok.com</b><br>
                  2. A tua App → Manage → Gera novo Access Token<br>
                  3. Scope obrigatorio: <b style='color:#00f5d4;'>video.upload</b><br>
                  4. Cola o novo token em ⚙️ Configuracoes
                </div>""", unsafe_allow_html=True)
    else:
        if not all_filled:
            st.markdown("<div style='color:#6b7280;font-size:.82rem;'>Preenche as credenciais primeiro.</div>", unsafe_allow_html=True)
        else:
            st.markdown("<div style='color:#6b7280;font-size:.82rem;'>Clica no botao para testar a ligacao.</div>", unsafe_allow_html=True)

    st.markdown("---")

    # ── 3. Verificar video ────────────────────────────────────────────────────
    st.markdown("<div class='sh'>3️⃣ Verificar Video</div>", unsafe_allow_html=True)
    st.markdown("<div style='color:#6b7280;font-size:.82rem;margin-bottom:.8rem;'>Carrega um video para verificar se cumpre os requisitos do TikTok antes de agendar.</div>", unsafe_allow_html=True)

    test_video = st.file_uploader("Video para verificar", type=["mp4","mov","avi","webm"], key="verify_video")
    if test_video:
        size_mb = len(test_video.getbuffer()) / (1024*1024)
        duration_est = None

        checks = []

        # Formato
        ext = test_video.name.rsplit(".",1)[-1].lower()
        checks.append(("Formato", ext.upper(), ext in ["mp4","mov","avi","webm"], f".{ext}"))

        # Tamanho
        size_ok = size_mb <= 500
        checks.append(("Tamanho", f"{size_mb:.1f} MB", size_ok,
                        "✓ Dentro do limite" if size_ok else f"Excede 500MB ({size_mb:.0f}MB)"))

        # Nome do ficheiro
        name_ok = len(test_video.name) < 200 and all(c not in test_video.name for c in ['<','>',':','"','|','?','*'])
        checks.append(("Nome", test_video.name[:30]+"..." if len(test_video.name)>30 else test_video.name,
                       name_ok, "OK" if name_ok else "Caracteres invalidos no nome"))

        # Resolucao estimada (pelo tamanho — heuristico)
        if size_mb > 50:
            res_guess = "Provavelmente >= 720p"
            res_ok = True
        elif size_mb > 5:
            res_guess = "Resolucao media"
            res_ok = True
        else:
            res_guess = "Pode ser baixa resolucao"
            res_ok = False
        checks.append(("Resolucao", res_guess, res_ok, "TikTok recomenda >= 720p"))

        # Mostrar resultados
        c_checks = st.columns(len(checks))
        all_ok = all(c[2] for c in checks)

        for (label, val, ok, detail), col in zip(checks, c_checks):
            color = "#22c55e" if ok else "#ff2d55"
            icon  = "✅" if ok else "❌"
            with col:
                st.markdown(f"""
                <div style='background:#111118;border:1px solid {"#22c55e44" if ok else "#ff2d5544"};
                  border-radius:10px;padding:.8rem;text-align:center;'>
                  <div style='font-size:1.3rem;'>{icon}</div>
                  <div style='font-size:.7rem;color:#6b7280;text-transform:uppercase;'>{label}</div>
                  <div style='font-size:.78rem;color:{color};font-weight:600;margin-top:3px;'>{val}</div>
                  <div style='font-size:.65rem;color:#6b7280;margin-top:2px;'>{detail}</div>
                </div>""", unsafe_allow_html=True)

        st.markdown("<br>", unsafe_allow_html=True)
        if all_ok:
            st.success("✅ Video parece compativel com o TikTok! Podes agendar com confianca.")
        else:
            st.error("❌ Alguns requisitos nao sao cumpridos. Verifica os itens a vermelho.")

        # Requisitos TikTok
        with st.expander("📋 Requisitos oficiais TikTok Content Posting API"):
            st.markdown("""
            | Requisito | Valor |
            |-----------|-------|
            | Formatos aceites | MP4, MOV, WEBM, AVI |
            | Tamanho maximo | 500 MB |
            | Duracao minima | 3 segundos |
            | Duracao maxima | 10 minutos |
            | Resolucao minima | 540×960 (recomendado 1080×1920) |
            | FPS recomendado | 24–60 fps |
            | Codec video | H.264 ou H.265 |
            | Codec audio | AAC |
            """)

    st.markdown("---")

    # ── 4. Checklist pre-publicacao ───────────────────────────────────────────
    st.markdown("<div class='sh'>4️⃣ Checklist Completa</div>", unsafe_allow_html=True)

    q = load_queue()
    sched = [p for p in q if p["status"] == "scheduled"]
    scheduler_ok = os.path.exists(os.path.join(BASE_DIR, "scheduler.pid"))

    checklist = [
        ("Credenciais preenchidas",  all_filled,       "Vai a ⚙️ Configuracoes e preenche todos os campos"),
        ("API testada e OK",         st.session_state.get("api_test_result",("",""))[0] == "ok",
                                     "Clica em 'Testar API agora' acima"),
        ("Scheduler ativo",          scheduler_ok,     "Lanca a app pelo metricool_free.bat ou inicia em ⚙️ → Diagnostico"),
        ("Posts na fila",            len(sched) > 0,   "Agenda pelo menos um post em 🎬 ou 🚀"),
        ("Pasta videos existe",      os.path.isdir(VIDEOS_DIR), f"Cria a pasta: {VIDEOS_DIR}"),
        ("Ficheiros de video OK",    all(os.path.exists(p.get("video_path","")) for p in sched) if sched else True,
                                     "Algum video agendado nao foi encontrado no disco"),
        ("Modo simulacao desativado", has_creds,       "Sem credenciais so simula — nao publica mesmo"),
    ]

    for label, ok, fix in checklist:
        icon  = "✅" if ok else "❌"
        color = "#22c55e" if ok else "#ff2d55"
        fix_html = f" <span style='color:#6b7280;font-size:.72rem;'>→ {fix}</span>" if not ok else ""
        st.markdown(f"""
        <div style='display:flex;align-items:center;gap:.7rem;padding:.5rem .9rem;
          background:#111118;border-radius:9px;margin-bottom:3px;border:1px solid #1e1e2e;
          border-left:3px solid {color};'>
          <span style='font-size:1rem;'>{icon}</span>
          <span style='font-size:.84rem;color:#f0f0f8;'>{label}</span>
          {fix_html}
        </div>""", unsafe_allow_html=True)

    all_checks_ok = all(ok for _, ok, _ in checklist)
    st.markdown("<br>", unsafe_allow_html=True)
    if all_checks_ok:
        st.success("🎉 Tudo OK! O sistema vai publicar automaticamente na hora certa.")
    else:
        fails = sum(1 for _, ok, _ in checklist if not ok)
        st.error(f"⚠️ {fails} item{'ns' if fails>1 else ''} a corrigir antes de poder publicar com seguranca.")

    if st.button("🔄 Atualizar verificacao", use_container_width=True):
        if "api_test_result" in st.session_state:
            del st.session_state["api_test_result"]
        st.rerun()


# ════════════════════════════════════════════════════════════════════════════════
# PAGE: CONTA TIKTOK (Login Kit OAuth)
# ════════════════════════════════════════════════════════════════════════════════
elif page == "🔐 Conta TikTok":
    st.markdown("<div class='pt'>🔐 Conta TikTok</div>", unsafe_allow_html=True)
    st.markdown("<div class='ps'>Autoriza a app com o teu TikTok via Login Kit — necessário para publicar vídeos</div>", unsafe_allow_html=True)

    config = load_config()

    # ── Show success banner if just connected ─────────────────────────────────
    if "oauth_success" in st.session_state:
        display_name = st.session_state.pop("oauth_success")
        st.success(f"✅ TikTok conectado com sucesso! Bem-vindo, **{display_name}** 🎉")
        st.balloons()

    if "oauth_error" in st.session_state:
        err_msg = st.session_state.pop("oauth_error")
        st.error(f"❌ Erro OAuth: {err_msg}")

    if not OAUTH_AVAILABLE:
        st.error("❌ Módulo `oauth.py` não encontrado. Verifica a instalação.")
        st.stop()

    # ── Check if already connected ─────────────────────────────────────────────
    has_token   = bool(config.get("access_token") and config.get("open_id"))
    auth_method = config.get("auth_method", "")
    is_oauth    = auth_method == "oauth_login_kit"
    token_valid = tk_oauth.is_token_valid(config) if has_token else False
    refresh_ok  = tk_oauth.is_refresh_token_valid(config) if has_token else False

    if has_token:
        # ── Connected state ────────────────────────────────────────────────────
        display_name = config.get("connected_display_name", "")
        avatar_url   = config.get("connected_avatar_url", "")
        open_id      = config.get("open_id", "—")
        expires_str  = tk_oauth.token_expires_in_human(config)
        conn_ts      = config.get("connected_at", 0)
        conn_date    = datetime.fromtimestamp(conn_ts).strftime("%d/%m/%Y às %H:%M") if conn_ts else "—"

        # Profile card
        ca, cb = st.columns([1, 2])
        with ca:
            if avatar_url:
                st.image(avatar_url, width=120)
            else:
                st.markdown("""
                <div style='width:100px;height:100px;border-radius:50%;background:linear-gradient(135deg,#ff2d55,#7c3aed);
                  display:flex;align-items:center;justify-content:center;font-size:2.5rem;'>🎬</div>""",
                unsafe_allow_html=True)
        with cb:
            badge_method = "🔑 Login Kit OAuth" if is_oauth else "🔧 Token manual"
            badge_color  = "#22c55e" if is_oauth else "#f59e0b"
            st.markdown(f"""
            <div style='background:#111118;border:1px solid #22c55e44;border-radius:14px;padding:1.1rem 1.3rem;'>
              <div style='font-family:Syne,sans-serif;font-size:1.4rem;font-weight:800;color:#f0f0f8;'>
                {'@' + display_name if display_name else 'Conta TikTok'}</div>
              <div style='color:#6b7280;font-size:.75rem;margin-top:.2rem;'>Open ID: {open_id[:12]}…</div>
              <div style='margin-top:.6rem;display:flex;gap:.6rem;flex-wrap:wrap;'>
                <span style='padding:.2rem .6rem;border-radius:20px;background:{badge_color}22;
                  color:{badge_color};font-size:.72rem;font-weight:700;border:1px solid {badge_color}44;'>{badge_method}</span>
                <span style='padding:.2rem .6rem;border-radius:20px;background:{"#22c55e22" if token_valid else "#ff2d5522"};
                  color:{"#22c55e" if token_valid else "#ff2d55"};font-size:.72rem;font-weight:700;
                  border:1px solid {"#22c55e44" if token_valid else "#ff2d5544"};'>
                  {"✅ Token válido" if token_valid else "⚠️ Token expirado"}</span>
                <span style='padding:.2rem .6rem;border-radius:20px;background:#7c3aed22;
                  color:#a78bfa;font-size:.72rem;font-weight:700;border:1px solid #7c3aed44;'>
                  ⏱ Expira em {expires_str}</span>
              </div>
              <div style='font-size:.7rem;color:#6b7280;margin-top:.5rem;'>Conectado em: {conn_date}</div>
            </div>""", unsafe_allow_html=True)

        st.markdown("<br>", unsafe_allow_html=True)

        # ── Token management actions ──────────────────────────────────────────
        col_refresh, col_test, col_disco = st.columns(3)

        with col_refresh:
            refresh_disabled = not (refresh_ok and config.get("client_key") and config.get("client_secret"))
            if st.button("🔄 Renovar Token", use_container_width=True,
                         disabled=refresh_disabled,
                         help="Usa o refresh_token para obter um novo access_token sem precisar de fazer login de novo"):
                with st.spinner("A renovar token..."):
                    result = tk_oauth.refresh_access_token(
                        client_key    = config["client_key"],
                        client_secret = config["client_secret"],
                        refresh_token = config["refresh_token"],
                    )
                if result.get("error"):
                    st.error(f"❌ {result.get('error_description', result['error'])}")
                else:
                    tk_oauth.save_tokens_to_config(CONFIG_FILE, result, {
                        "open_id": result.get("open_id", config.get("open_id", "")),
                        "display_name": config.get("connected_display_name", ""),
                        "avatar_url": config.get("connected_avatar_url", ""),
                    })
                    st.success("✅ Token renovado com sucesso!")
                    st.rerun()

        with col_test:
            if st.button("🔌 Testar Ligação", use_container_width=True):
                with st.spinner("A testar..."):
                    user_info = tk_oauth.get_user_info(config.get("access_token", ""))
                if user_info.get("ok"):
                    nm = user_info.get("display_name", "")
                    st.success(f"✅ Ligação OK — @{nm}")
                else:
                    st.error(f"❌ {user_info.get('error', 'Erro desconhecido')}")

        with col_disco:
            if st.button("🔓 Desconectar", use_container_width=True,
                         help="Remove os tokens locais. Podes reconectar a qualquer altura."):
                # Revoke on TikTok side if possible
                if config.get("client_key") and config.get("client_secret"):
                    tk_oauth.revoke_token(config["client_key"], config["client_secret"],
                                          config.get("access_token", ""))
                # Wipe tokens from config
                for k in ["access_token","refresh_token","open_id","token_scope",
                          "access_token_expires_at","refresh_token_expires_at",
                          "connected_display_name","connected_avatar_url","connected_at","auth_method"]:
                    config.pop(k, None)
                save_config(config)
                st.success("✅ Conta desconectada.")
                st.rerun()

        if not refresh_ok and has_token:
            st.warning("⚠️ Refresh token expirado — terás de fazer login novamente para renovar.")

        # ── Published videos status ───────────────────────────────────────────
        st.markdown("---")
        st.markdown("<div class='sh'>📊 Status das Publicações</div>", unsafe_allow_html=True)
        q_all = load_queue()
        posted = [p for p in q_all if p.get("status") == "posted"]
        failed = [p for p in q_all if p.get("status") == "failed"]
        sched  = [p for p in q_all if p.get("status") == "scheduled"]

        sc1, sc2, sc3 = st.columns(3)
        for col, label, val, color in [
            (sc1, "✅ Publicados",  len(posted), "#22c55e"),
            (sc2, "⏳ Agendados",   len(sched),  "#00f5d4"),
            (sc3, "❌ Falhados",    len(failed), "#ff2d55"),
        ]:
            with col:
                st.markdown(f"""
                <div style='text-align:center;padding:.9rem;background:#111118;
                  border:1px solid {color}33;border-radius:12px;'>
                  <div style='font-family:Syne,sans-serif;font-size:2rem;font-weight:800;color:{color};'>{val}</div>
                  <div style='font-size:.75rem;color:#6b7280;margin-top:2px;'>{label}</div>
                </div>""", unsafe_allow_html=True)

        if posted:
            st.markdown("<br><div style='color:#6b7280;font-size:.8rem;font-weight:600;text-transform:uppercase;letter-spacing:1px;margin-bottom:.5rem;'>Últimos publicados</div>", unsafe_allow_html=True)
            for p in sorted(posted, key=lambda x: x.get("posted_at",""), reverse=True)[:5]:
                pid  = p.get("publish_id","—")
                nm   = os.path.basename(p.get("video_path",""))
                pat  = p.get("posted_at","")
                try: pat_str = datetime.fromisoformat(pat).strftime("%d/%m/%Y %H:%M")
                except: pat_str = pat
                st.markdown(f"""
                <div style='display:flex;justify-content:space-between;align-items:center;
                  padding:.5rem .9rem;background:#111118;border-radius:9px;
                  border:1px solid #22c55e33;margin-bottom:3px;'>
                  <span style='font-size:.8rem;color:#f0f0f8;'>🎬 {nm[:40]}</span>
                  <span style='font-size:.7rem;color:#6b7280;'>{pat_str}</span>
                  <span style='font-size:.68rem;color:#22c55e;font-family:monospace;'>{str(pid)[:16]}</span>
                </div>""", unsafe_allow_html=True)

        if failed:
            st.markdown("<br><div style='color:#ff2d55;font-size:.8rem;font-weight:600;text-transform:uppercase;letter-spacing:1px;margin-bottom:.5rem;'>Falhados</div>", unsafe_allow_html=True)
            for p in failed[:5]:
                nm  = os.path.basename(p.get("video_path",""))
                err = p.get("error","—")
                st.markdown(f"""
                <div style='padding:.5rem .9rem;background:#111118;border-radius:9px;
                  border:1px solid #ff2d5533;margin-bottom:3px;'>
                  <span style='font-size:.8rem;color:#f0f0f8;'>🎬 {nm[:40]}</span>
                  <div style='font-size:.7rem;color:#ff2d55;margin-top:2px;'>⚠️ {str(err)[:80]}</div>
                </div>""", unsafe_allow_html=True)

    else:
        # ── Not connected — show Login Kit flow ────────────────────────────────
        if not config.get("client_key") or not config.get("client_secret"):
            st.markdown("""
            <div style='background:rgba(245,158,11,.07);border:1px solid rgba(245,158,11,.3);
              border-radius:14px;padding:1.2rem 1.5rem;margin-bottom:1.5rem;'>
              <div style='color:#f59e0b;font-weight:700;font-size:.95rem;margin-bottom:.5rem;'>
                ⚠️ Preenche primeiro o Client Key e Client Secret</div>
              <div style='color:#6b7280;font-size:.82rem;line-height:1.8;'>
                1. Vai a <b style='color:#f0f0f8;'>developers.tiktok.com</b> → Login → My Apps → Create App<br>
                2. Em Products → adiciona <b style='color:#00f5d4;'>Login Kit</b> e <b style='color:#00f5d4;'>Content Posting API</b><br>
                3. Copia o <b style='color:#f0f0f8;'>Client Key</b> e <b style='color:#f0f0f8;'>Client Secret</b><br>
                4. Preenche em ⚙️ Configuracoes → TikTok API<br>
                5. Em <b style='color:#ff2d55;'>Redirect URIs</b>, adiciona <b>EXATAMENTE</b>: <code style='color:#00f5d4;background:#0a0a0f;padding:1px 5px;border-radius:4px;'>http://localhost:8501/</code><br>
                &nbsp;&nbsp;&nbsp;(com o / no final — sem isso o login falha com erro redirect_uri)
              </div>
            </div>""", unsafe_allow_html=True)

            with st.expander("🔧 Preencher Client Key / Secret aqui"):
                ck_in = st.text_input("Client Key",    value=config.get("client_key",""),    type="password", key="oauth_ck")
                cs_in = st.text_input("Client Secret", value=config.get("client_secret",""), type="password", key="oauth_cs")
                if st.button("💾 Guardar e continuar", use_container_width=True):
                    config["client_key"]    = ck_in
                    config["client_secret"] = cs_in
                    save_config(config)
                    st.rerun()
        else:
            # ── Show the Connect button ────────────────────────────────────────
            st.markdown("""
            <div style='text-align:center;padding:2rem 1rem 1.5rem;'>
              <div style='font-size:3.5rem;margin-bottom:.5rem;'>🎵</div>
              <div style='font-family:Syne,sans-serif;font-size:1.5rem;font-weight:800;
                color:#f0f0f8;margin-bottom:.4rem;'>Conecta a tua conta TikTok</div>
              <div style='color:#6b7280;font-size:.87rem;max-width:480px;margin:0 auto;line-height:1.7;'>
                Usa o fluxo oficial <b style='color:#00f5d4;'>TikTok Login Kit</b> para autorizar
                esta app a publicar vídeos em teu nome.<br>
                O teu token é guardado <b style='color:#f0f0f8;'>localmente</b> — nunca partilhado.
              </div>
            </div>""", unsafe_allow_html=True)

            # Sandbox toggle
            sandbox_mode = st.checkbox(
                "🧪 Modo Sandbox (para testes sem publicar de verdade)",
                value=config.get("sandbox_mode", False),
                help="Activa durante a revisão da app TikTok. Os posts ficam em rascunho."
            )
            if sandbox_mode != config.get("sandbox_mode", False):
                config["sandbox_mode"] = sandbox_mode
                save_config(config)

            st.markdown("<br>", unsafe_allow_html=True)
            col_btn = st.columns([1, 2, 1])[1]
            with col_btn:
                if st.button("🔗 Conectar TikTok", use_container_width=True):
                    # Gera PKCE e guarda em sessão E em ficheiro (fallback para nova sessão)
                    code_verifier = tk_oauth.generate_code_verifier()
                    state         = secrets.token_urlsafe(16)
                    auth_url      = tk_oauth.build_auth_url(
                        client_key   = config["client_key"],
                        redirect_uri = OAUTH_REDIRECT_URI,
                        code_verifier= code_verifier,
                        state        = state,
                        sandbox      = sandbox_mode,
                    )
                    # Guarda em session_state
                    st.session_state["oauth_code_verifier"] = code_verifier
                    st.session_state["oauth_state"]         = state
                    st.session_state["oauth_initiated"]     = True

                    # ── CRÍTICO: guardar também em ficheiro ──────────────────
                    # O TikTok redireciona para localhost:8501 que pode abrir
                    # numa nova janela/sessão Streamlit sem session_state.
                    # O ficheiro garante que o code_verifier sobrevive.
                    try:
                        import json as _json
                        with open(OAUTH_PENDING_FILE, "w", encoding="utf-8") as _f:
                            _json.dump({"state": state, "code_verifier": code_verifier}, _f)
                    except Exception:
                        pass

                    # Redireciona a própria janela da app para o TikTok
                    # O TikTok devolve para localhost:8501 — ficamos sempre na mesma janela
                    st.markdown(f"""
                    <div style='text-align:center;padding:.5rem;color:#6b7280;font-size:.85rem;'>
                      A redirecionar para o TikTok…
                    </div>
                    <script>window.location.href = "{auth_url}";</script>
                    """, unsafe_allow_html=True)
                    st.markdown(
                        f"<div style='text-align:center;margin-top:.4rem;'>"
                        f"<a href='{auth_url}' target='_self' "
                        f"style='color:#00f5d4;font-weight:700;text-decoration:none;'>"
                        f"Abrir TikTok Login (se não redirecionou)</a></div>",
                        unsafe_allow_html=True
                    )

            # Auth info box
            st.markdown("<br>", unsafe_allow_html=True)
            st.markdown("""
            <div style='background:#111118;border:1px solid #1e1e2e;border-radius:12px;
              padding:1rem 1.2rem;'>
              <div style='color:#f0f0f8;font-weight:600;margin-bottom:.6rem;font-size:.85rem;'>
                🔒 Como funciona a autenticação</div>
              <div style='color:#6b7280;font-size:.78rem;line-height:1.9;'>
                1. <b style='color:#f0f0f8;'>Clicas em "Conectar TikTok"</b> → abre o login oficial TikTok<br>
                2. <b style='color:#f0f0f8;'>Fazes login</b> e autorizas os scopes: <code style='color:#00f5d4;'>user.info.basic · video.upload · video.publish</code><br>
                3. <b style='color:#f0f0f8;'>TikTok redireciona</b> de volta para <code style='color:#00f5d4;'>localhost:8501</code> com um código<br>
                4. <b style='color:#f0f0f8;'>A app troca</b> o código por <code style='color:#7c3aed;'>access_token</code> + <code style='color:#7c3aed;'>refresh_token</code><br>
                5. <b style='color:#f0f0f8;'>Tokens guardados localmente</b> em <code style='color:#6b7280;'>config.json</code> — nunca enviados para terceiros<br>
                6. <b style='color:#f0f0f8;'>Cada publicação</b> usa o teu access_token — auditável pelo TikTok
              </div>
            </div>""", unsafe_allow_html=True)


# ════════════════════════════════════════════════════════════════════════════════
# PAGE: CONFIGURACOES
# ════════════════════════════════════════════════════════════════════════════════
elif page == "⚙️ Configuracoes":
    st.markdown("<div class='pt'>⚙️ Configuracoes</div>", unsafe_allow_html=True)
    st.markdown("<div class='ps'>Credenciais TikTok API e preferencias do scheduler</div>", unsafe_allow_html=True)

    config = load_config()
    ta, tb, tc = st.tabs(["🔑 TikTok API","🎛️ Preferencias","🩺 Diagnostico"])

    with ta:
        # OAuth status banner
        auth_method = config.get("auth_method", "")
        has_at = bool(config.get("access_token") and config.get("open_id"))
        if has_at and auth_method == "oauth_login_kit":
            display_name = config.get("connected_display_name", "")
            expires_str  = tk_oauth.token_expires_in_human(config) if OAUTH_AVAILABLE else "—"
            st.markdown(f"""
            <div style='background:rgba(34,197,94,.07);border:1px solid rgba(34,197,94,.25);
              border-radius:12px;padding:.8rem 1rem;margin-bottom:1rem;'>
              <div style='display:flex;align-items:center;justify-content:space-between;'>
                <div>
                  <span style='color:#22c55e;font-weight:700;'>✅ Autenticado via Login Kit OAuth</span>
                  {'<span style="color:#6b7280;font-size:.8rem;margin-left:.5rem;">@' + display_name + '</span>' if display_name else ''}
                </div>
                <span style='color:#6b7280;font-size:.75rem;'>Token expira: {expires_str}</span>
              </div>
              <div style='color:#6b7280;font-size:.75rem;margin-top:.3rem;'>
                Para reconectar ou gerir a conta → <b style='color:#00f5d4;'>🔐 Conta TikTok</b>
              </div>
            </div>""", unsafe_allow_html=True)
        else:
            st.markdown("""
            <div style='background:rgba(245,158,11,.07);border:1px solid rgba(245,158,11,.2);
              border-radius:12px;padding:1rem 1.2rem;margin-bottom:1.2rem;'>
              <div style='color:#f59e0b;font-weight:600;margin-bottom:.4rem;'>Como obter as credenciais</div>
              <div style='color:#6b7280;font-size:.83rem;line-height:1.7;'>
                1. developers.tiktok.com → Login → My Apps → Create App<br>
                2. Products → Content Posting API + Login Kit<br>
                3. Copia Client Key e Client Secret<br>
                4. Usa <b style='color:#00f5d4;'>🔐 Conta TikTok</b> para autenticar via OAuth (recomendado)<br>
                5. Ou cola Access Token manualmente abaixo (legado)
              </div>
            </div>""", unsafe_allow_html=True)

        ck = st.text_input("Client Key",    value=config.get("client_key",""),    type="password")
        cs = st.text_input("Client Secret", value=config.get("client_secret",""), type="password")

        st.markdown("<div style='color:#6b7280;font-size:.75rem;margin:.6rem 0 .2rem;'>Token manual (legado — prefere o fluxo OAuth em 🔐 Conta TikTok)</div>", unsafe_allow_html=True)
        at = st.text_input("Access Token",  value=config.get("access_token",""),  type="password")
        oi = st.text_input("Open ID",       value=config.get("open_id",""))

        sandbox_toggle = st.checkbox("🧪 Modo Sandbox", value=config.get("sandbox_mode", False),
                                      help="Posts ficam em rascunho — ideal para testes")
        audited_toggle = st.checkbox("✅ App auditada pelo TikTok (publica como Público)",
                                      value=config.get("app_audited", False),
                                      help="Ativa após receberes aprovação da auditoria TikTok. Até lá os posts ficam privados (SELF_ONLY).")
        if not audited_toggle:
            st.info("⏳ Enquanto a app não for auditada, os posts publicam como **Privado (SELF_ONLY)**. Após aprovação, ativa esta opção.")

        if st.button("💾 Guardar Credenciais", use_container_width=True):
            config.update({"client_key": ck, "client_secret": cs,
                           "access_token": at, "open_id": oi,
                           "sandbox_mode": sandbox_toggle,
                           "app_audited": audited_toggle})
            if at and not auth_method:
                config["auth_method"] = "manual"
            save_config(config)
            st.success("✅ Guardado!")
        if not config.get("access_token"):
            st.info("💡 Sem credenciais: modo simulação (agenda mas não publica)")

    with tb:
        retry       = st.toggle("Tentar novamente se falhar", value=config.get("retry_failed",True))
        interval    = st.slider("Verificar fila a cada (seg)", 10, 120, config.get("check_interval",30))
        notify_ok   = st.toggle("Notificar quando publicado", value=config.get("notify_success",True))
        notify_fail = st.toggle("Notificar quando falhar",    value=config.get("notify_fail",True))
        if st.button("💾 Guardar Preferencias", use_container_width=True):
            config.update({"retry_failed":retry,"check_interval":interval,
                           "notify_success":notify_ok,"notify_fail":notify_fail})
            save_config(config); st.success("✅ Guardado!")

    with tc:
        st.markdown("<div class='sh'>📂 Caminhos</div>", unsafe_allow_html=True)
        st.code(f"Videos: {VIDEOS_DIR}")
        st.code(f"Fila:   {QUEUE_FILE}")
        st.code(f"Config: {CONFIG_FILE}")
        st.markdown("---")
        try:
            vids = [f for f in os.listdir(VIDEOS_DIR) if f.lower().endswith((".mp4",".mov",".avi",".webm"))]
            total_mb = sum(os.path.getsize(os.path.join(VIDEOS_DIR,v)) for v in vids) / (1024*1024)
            st.markdown(f"<div style='color:#6b7280;font-size:.82rem;'>📁 {len(vids)} videos — {total_mb:.1f}MB no total</div>", unsafe_allow_html=True)
        except: pass
        st.markdown("---")
        pid_file = os.path.join(BASE_DIR,"scheduler.pid")
        if os.path.exists(pid_file):
            try:
                with open(pid_file) as f: pid_val = f.read().strip()
                st.success(f"✅ Scheduler ativo (PID: {pid_val})")
            except: st.warning("⚠️ Ficheiro PID existe mas nao legivel")
        else:
            st.error("❌ Scheduler nao esta a correr")
            if st.button("▶️ Iniciar Scheduler", use_container_width=True):
                kwargs = {"creationflags": subprocess.CREATE_NO_WINDOW} if sys.platform=="win32" else {}
                subprocess.Popen([sys.executable, "scheduler.py"], cwd=BASE_DIR, **kwargs)
                time.sleep(1); st.rerun()
