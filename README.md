# 🏥 VoiceByte — AI Hospital Registration Kiosk

 Voice-Byte hospital self-registration for elderly and illiterate patients.  
 **Speak in your language — we understand you.**

---

## 🚨 Problem

In rural and semi-urban Indian hospitals:
- Elderly and illiterate patients **cannot fill registration forms**
- Staff spend 10–15 minutes per patient on manual registration
- Language barriers cause miscommunication of symptoms
- Emergency patients waste critical time at registration desk
- No queue system — patients don't know when to go to doctor

---

## 💡 Solution

An AI-powered **voice-only kiosk** that:
- Listens to patient speaking in their own language
- Automatically detects the language
- Extracts name, age, symptoms using AI
- Routes to correct department
- Generates receipt with token number
- Sends SMS to patient's mobile
- Alerts doctor via live admin dashboard

**No reading. No typing. No language barrier.**


## 🎥 Demo

> Patient speaks in Telugu → Language detected → Questions asked in Telugu → Symptoms extracted → Department assigned → Receipt generated → SMS sent → Doctor calls via admin dashboard

---


## 🚀 How to Run Locally

### 1. Clone the repo
```bash
git clone https://github.com/purnima016/VoiceByte.git
cd VoiceByte
```

### 2. Install dependencies
```bash
pip install -r requirements.txt
```

### 3. Add your API keys
```bash
# Create a .env file inside voicebyte_livekit folder
# Add these two lines:
GROQ_API_KEY=your_groq_key_here
FAST2SMS_KEY=your_fast2sms_key_here
```

### 4. Run the backend
```bash
cd voicebyte_livekit/backend
python app.py
```

### 5. Open in browser
```
Kiosk  → http://127.0.0.1:5000
Admin  → http://127.0.0.1:5000/admin
```

## 🔒 Privacy & Security

- Patient database (`voicebyte.db`) is **local only** — never uploaded anywhere
- API keys stored in `.env` — **not visible** in this repository
- `.gitignore` blocks all sensitive files from GitHub

---

## 📄 License

MIT License — free to use and modify
