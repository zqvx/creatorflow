# 🎬 TikTok Scheduler — Free Metricool

Agenda e publica vídeos no TikTok automaticamente, com interface visual tipo Metricool.

---

## 🚀 Início Rápido

### 1ª vez (instalação)
```
Duplo clique em: setup.bat
```

### Todas as outras vezes
```
Duplo clique em: metricool_free.bat
```

Abre automaticamente em: **http://localhost:8501**

---

## 📁 Estrutura

```
CalendarioTikTok/
├── app.py              ← Interface Streamlit
├── scheduler.py        ← Scheduler automático
├── queue.json          ← Posts agendados
├── config.json         ← Credenciais e config
├── videos/             ← Pasta de vídeos
├── metricool_free.bat  ← Lançar tudo
├── setup.bat           ← Instalação inicial
└── requirements.txt    ← Dependências Python
```

---

## ⚙️ Configurar TikTok API

1. Vai a [developers.tiktok.com](https://developers.tiktok.com)
2. Cria uma app → Product → **Content Posting API**
3. Vai a Configurações na app e preenche:
   - **Client Key**
   - **Client Secret**  
   - **Access Token** (com scope `video.upload`)
   - **Open ID**

> **Sem credenciais**, o scheduler corre em **modo simulação** — ideal para testar o fluxo.

---

## 📖 Como usar

1. Abre `metricool_free.bat`
2. Vai a **➕ Agendar Post**
3. Faz upload do vídeo (MP4, MOV, etc.)
4. Escreve legenda e hashtags
5. Define data e hora
6. Clica **🚀 Agendar Post**
7. O scheduler publica automaticamente na hora certa!

---

## 🔑 queue.json — Estrutura de um post

```json
{
  "id": "abc12345",
  "video_path": "C:\\...\\videos\\meu_video.mp4",
  "caption": "Legenda do post",
  "hashtags": "#fyp #viral",
  "scheduled_at": "2025-01-15T18:00:00",
  "status": "scheduled",
  "created_at": "2025-01-14T10:30:00",
  "posted_at": null,
  "error": null
}
```

**Status possíveis:** `scheduled` → `pending` → `posted` / `failed`

---

## 🛠️ Requisitos

- Python 3.10+
- Windows 10/11
- Ligação à internet (para TikTok API)
