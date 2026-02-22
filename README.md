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

---

## ✨ Features

- 🎤 **Voice only** — patient just speaks, nothing to read or type
- 🌍 **5 languages** — Telugu, Tamil, Hindi, Malayalam, English
- 🧠 **AI powered** — Groq LLaMA 3.3 70B extracts symptoms accurately
- 🔍 **Auto language detection** — no manual selection needed
- 📱 **SMS alerts** — patient gets SMS on registration and when called
- 🚨 **Emergency detection** — chest pain, stroke etc. auto-routed to emergency
- 👨‍⚕️ **Admin dashboard** — doctors see live queue, call next patient
- 🎫 **Token system** — real queue management, no crowding
- ⏱️ **Idle detection** — kiosk auto-resets after 30 seconds
- 🧾 **Instant receipt** — department, floor, token, doctor name

---

## 🎥 Demo

> Patient speaks in Telugu → Language detected → Questions asked in Telugu → Symptoms extracted → Department assigned → Receipt generated → SMS sent → Doctor calls via admin dashboard

---

## 🛠️ Tech Stack

| Layer          | Technology                      |
|---             |---                              |
| Frontend       | HTML, CSS, JavaScript (Vanilla) |
| Backend        | Python Flask                    |
| AI / NLP       | Groq — LLaMA 3.3 70B            |
| Text to Speech | gTTS (Google TTS) — Free        |
| Speech to Text | Chrome Web Speech API — Free    |
| SMS            | Fast2SMS — Free tier            |
| Database       | SQLite (local, no setup needed) |

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

> ⚠️ **Must use Google Chrome** — Web Speech API not supported in other browsers

---

## 🔑 Free API Keys

| Key            | Where to get     | Cost                     |
|---             |---               |---                       |
| `GROQ_API_KEY` | console.groq.com | 100% Free                |
| `FAST2SMS_KEY` | fast2sms.com     | Free (200 SMS on signup) |

---

## 🌍 Supported Languages

| Language  | Voice Input | Voice Output | Symptom Detection |
|---        |---          |---           |---                |
| Telugu    | ✅         | ✅           | ✅               |
| Tamil     | ✅         | ✅           | ✅               |
| Hindi     | ✅         | ✅           | ✅               |
| Malayalam | ✅         | ✅           | ✅               |
| English   | ✅         | ✅           | ✅               |

---

## 🏥 Department Routing

| Symptoms Detected         | Department               |
|---                        |---                       |
| Chest pain, heart         | Cardiology — Floor 2     |
| Headache, seizure, stroke | Neurology — Floor 3      |
| Bone, knee, back pain    | Orthopedics — Floor 1     |
| Child, baby, vaccination | Pediatrics — Floor 2      |
| Pregnancy, periods       | Gynecology — Floor 3      |
| Fever, cough, cold       | General Medicine — Floor 1|
| Emergency keywords       | Emergency — Ground Floor  |

---

## 🔒 Privacy & Security

- Patient database (`voicebyte.db`) is **local only** — never uploaded anywhere
- API keys stored in `.env` — **not visible** in this repository
- `.gitignore` blocks all sensitive files from GitHub

---

## 👩‍💻 Built By

**Purnima** — Built for hackathon to solve real problems faced by illiterate and elderly patients in Indian hospitals.

---

## 📄 License

MIT License — free to use and modify
