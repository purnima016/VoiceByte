from flask import Flask, request, jsonify, send_from_directory, Response
from flask_cors import CORS
from groq import Groq
from dotenv import load_dotenv
import os, sqlite3, time, uuid, re, io, urllib.request, json as _json
from datetime import datetime

load_dotenv()

app    = Flask(__name__)
CORS(app)

client  = Groq(api_key=os.getenv("GROQ_API_KEY"))
DB_PATH = "voicebyte.db"

# ─────────────────────────────
#  DATABASE
# ─────────────────────────────
def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute('''
        CREATE TABLE IF NOT EXISTS patients (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            registration_number TEXT,
            name                TEXT,
            age                 TEXT,
            mobile              TEXT,
            symptoms_keywords   TEXT,
            days_suffering      TEXT,
            department          TEXT,
            floor_number        INTEGER,
            floor_word          TEXT,
            emergency           INTEGER DEFAULT 0,
            priority            TEXT,
            doctor              TEXT,
            language            TEXT,
            visit_time          TEXT,
            token_number        INTEGER DEFAULT 0,
            status              TEXT DEFAULT 'waiting'
        )
    ''')
    for col, defn in [("token_number","INTEGER DEFAULT 0"),("status","TEXT DEFAULT 'waiting'")]:
        try: conn.execute(f"ALTER TABLE patients ADD COLUMN {col} {defn}")
        except: pass
    conn.commit()
    conn.close()

def get_next_token():
    today = datetime.now().strftime('%Y-%m-%d')
    conn  = sqlite3.connect(DB_PATH)
    c     = conn.cursor()
    c.execute("SELECT COUNT(*) FROM patients WHERE DATE(visit_time)=?", (today,))
    n = c.fetchone()[0]
    conn.close()
    return n + 1

FAST2SMS_KEY = os.getenv("FAST2SMS_KEY","")

SMS_TPL = {
    "registration":{
        "English":  "VoiceByte: Token {t}. Dept: {d}. Floor {f}. Wait for your token to be called.",
        "Telugu":   "VoiceByte: Token {t}. Dept: {d}. Floor {f}. Meeru token pilavabadevvaraku vechi undandi.",
        "Hindi":    "VoiceByte: Token {t}. Dept: {d}. Manzil {f}. Token bulane tak pratiksha karein.",
        "Tamil":    "VoiceByte: Token {t}. Dept: {d}. Thalam {f}. Ungal token azhaikkappatum varai kaattirunga.",
        "Malayalam":"VoiceByte: Token {t}. Dept: {d}. Nila {f}. Token vilikkumvare kaattirikku.",
    },
    "called":{
        "English":  "VoiceByte: Token {t} called! Please come to {d}, Floor {f}.",
        "Telugu":   "VoiceByte: Token {t} pilavabadindi! {d} ki randi. Antastu {f}.",
        "Hindi":    "VoiceByte: Token {t} bulaya! {d} mein aayen. Manzil {f}.",
        "Tamil":    "VoiceByte: Token {t} azhaikkappattadu! {d} varuga. Thalam {f}.",
        "Malayalam":"VoiceByte: Token {t} viliccu! {d} il varika. Nila {f}.",
    }
}

def send_sms(mobile, mtype, token, dept, floor, lang="English"):
    if not FAST2SMS_KEY or not mobile or len(str(mobile))<10:
        print(f"[SMS SKIP] key={bool(FAST2SMS_KEY)} mobile={mobile}")
        return False
    try:
        l   = lang if lang in SMS_TPL[mtype] else "English"
        msg = SMS_TPL[mtype][l].format(t=token,d=dept,f=floor)
        data = _json.dumps({"route":"q","message":msg,"language":"english","flash":0,"numbers":str(mobile)[-10:]}).encode()
        req  = urllib.request.Request("https://www.fast2sms.com/dev/bulkV2",data=data,
               headers={"authorization":FAST2SMS_KEY,"Content-Type":"application/json"})
        urllib.request.urlopen(req,timeout=6)
        print(f"[SMS OK] {mtype} token={token} -> {mobile}")
        return True
    except Exception as e:
        print(f"[SMS ERR] {e}")
        return False

def save_patient(data):
    conn  = sqlite3.connect(DB_PATH)
    c     = conn.cursor()
    reg   = f"VBT-{datetime.now().strftime('%Y%m%d')}-{str(uuid.uuid4())[:3].upper()}"
    token = get_next_token()
    c.execute('''
        INSERT INTO patients
        (registration_number,name,age,mobile,symptoms_keywords,days_suffering,
         department,floor_number,floor_word,emergency,priority,doctor,language,visit_time,
         token_number,status)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    ''', (
        reg,
        data.get('name',''),
        data.get('age',''),
        data.get('mobile',''),
        data.get('symptoms',''),
        data.get('days',''),
        data.get('department',''),
        data.get('floor',1),
        data.get('floorWord',''),
        1 if data.get('emergency') else 0,
        data.get('priority','Normal'),
        data.get('doctor',''),
        data.get('language','English'),
        datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        token, 'waiting'
    ))
    conn.commit()
    conn.close()
    return reg, token

# ─────────────────────────────
#  GROQ HELPER
# ─────────────────────────────
def ask_groq(system_prompt, user_msg, max_tok=150):
    # Retry up to 3 times if Groq fails
    last_error = None
    for attempt in range(3):
        try:
            response = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user",   "content": user_msg}
                ],
                max_tokens=max_tok,
                temperature=0.0,
                timeout=15
            )
            return response.choices[0].message.content.strip()
        except Exception as e:
            last_error = e
            print(f"[Groq attempt {attempt+1} failed]: {e}")
            time.sleep(1)  # wait 1 second before retry
    print(f"[Groq all retries failed]: {last_error}")
    raise last_error

# ─────────────────────────────
#  WORD-TO-DIGIT MAP
# ─────────────────────────────
# ── Units for each language ──────────────────────────────────────────────────
UNITS = {
    # English
    'zero':0,'one':1,'two':2,'three':3,'four':4,'five':5,
    'six':6,'seven':7,'eight':8,'nine':9,'ten':10,'eleven':11,
    'twelve':12,'thirteen':13,'fourteen':14,'fifteen':15,'sixteen':16,
    'seventeen':17,'eighteen':18,'nineteen':19,
    # Hindi — standard
    'shunya':0,'ek':1,'do':2,'teen':3,'char':4,'paanch':5,
    'chhe':6,'che':6,'saat':7,'aath':8,'nau':9,
    'das':10,'gyarah':11,'barah':12,'terah':13,'chaudah':14,
    'pandrah':15,'solah':16,'satrah':17,'atharah':18,'unnis':19,
    'bees':20,'ikkis':21,'baais':22,'teis':23,'chaubis':24,
    'pachchis':25,'pachis':25,'chhabbis':26,'sattais':27,'atthaais':28,'unnatis':29,
    'tees':30,'iktis':31,'battis':32,'taintis':33,'chautis':34,
    'paintis':35,'chhattis':36,'saintis':37,'artis':38,'untalees':39,
    'chalis':40,'iktalis':41,'bayalis':42,'tentalis':43,'chaualis':44,
    'paintalis':45,'chhiyalis':46,'saintalis':47,'artalis':48,'unchas':49,
    'pachas':50,'ikyavan':51,'bavan':52,'tirpan':53,'chauvan':54,
    'pachpan':55,'chhappan':56,'sattavan':57,'attavan':58,'unsath':59,
    'saath':60,'eksath':61,'barsath':62,'tirsath':63,'chausath':64,
    'painsath':65,'chhiyasath':66,'sarsath':67,'arsath':68,'unhattar':69,
    'sattar':70,'ikhattar':71,'bahattar':72,'tihattar':73,'chauhattar':74,
    'pachattar':75,'chhihattar':76,'satahattar':77,'atthattar':78,'unasi':79,
    'assi':80,'ikyasi':81,'bayasi':82,'tirasi':83,'chaurasi':84,
    'pachasi':85,'chhiyasi':86,'satasi':87,'athasi':88,'nabbe':89,
    'nabbe':89,'navve':90,'nabbe':90,
    # Hindi compound fallbacks (tens + units spoken separately)
    'bis':20,'tis':30,'chalees':40,'panchas':50,'saath':60,
    # Telugu units
    'sunna':0,'okati':1,'okka':1,'rendu':2,'madu':3,'mudu':3,
    'nalugu':4,'ayidu':5,'aidu':5,'aaru':6,'edu':7,'enimidi':8,'tommidi':9,
    # Telugu 11-19
    'padakorta':11,'padakortha':11,'pannendu':12,'padimadu':13,'padamadu':13,
    'padunalugu':14,'padayaidu':15,'padaaaru':16,'padaaru':16,
    'padadeddu':17,'padededdu':17,'padenendu':18,'pantommidi':19,
    # Telugu tens
    'padi':10,'iravai':20,'iravayi':20,'iravei':20,
    'mubbhai':30,'muppai':30,'mubhai':30,'mupphai':30,'muphai':30,
    'nalabhai':40,'nalabai':40,'nalbhai':40,
    'yabhai':50,'yabbai':50,'abhai':50,
    'aravai':60,'aravei':60,'araavai':60,
    'yebhai':70,'yabbhai':70,'debhai':70,
    'tombhai':80,'tombai':80,'thombhai':80,
    'navvai':90,'navai':90,'nabbhai':90,
    # Tamil units
    'poojiyam':0,'onru':1,'ondru':1,'irandu':2,'moondru':3,'mundru':3,
    'naangu':4,'nangu':4,'ainthu':5,'aindhu':5,'aaru':6,'ezhu':7,'ettu':8,'onbathu':9,'ombathu':9,
    # Tamil 11-19
    'pathinonru':11,'pannirendu':12,'pathinmoondru':13,'pathinaangu':14,
    'pathinainthu':15,'pathinaaru':16,'pathinezhu':17,'pathinettu':18,'pathonpathu':19,
    # Tamil tens
    'pathu':10,'patthu':10,'irupathu':20,'muppathu':30,'naarpathu':40,'narpathu':40,
    'aimpathu':50,'ampathu':50,'aruvathu':60,'ezhuvathu':70,'enpathu':80,'thonnuru':90,
    # Malayalam units
    'poojyam':0,'onnu':1,'randu':2,'moonnu':3,'naalu':4,
    'anchu':5,'aaru':6,'ezhu':7,'ettu':8,'onpathu':9,'onnpathu':9,
    # Malayalam 11-19
    'pathinonnu':11,'pannirandu':12,'pathinoonnu':13,'pathinaalu':14,
    'pathinanchu':15,'pathinaaru':16,'pathinezhu':17,'pathinettu':18,'pathombathu':19,
    # Malayalam tens
    'pathu':10,'iruppathu':20,'muppatu':30,'muppathu':30,'nalppathu':40,'nalpathu':40,
    'anpathu':50,'ampathu':50,'arupathu':60,'ezhupathu':70,'enpathu':80,'thonnuru':90,
}

# ── Compound number tables (phrase → number) — ALL languages 1-90 ─────────────
def _build_compounds():
    compounds = {}

    # Telugu: tens_word + unit_word  e.g. "iravai okati"=21
    te_tens = {
        'iravai':20,'iravayi':20,'iravei':20,
        'mubbhai':30,'muppai':30,'mubhai':30,'mupphai':30,
        'nalabhai':40,'nalabai':40,'nalbhai':40,
        'yabhai':50,'yabbai':50,'abhai':50,
        'aravai':60,'aravei':60,
        'yebhai':70,'debhai':70,
        'tombhai':80,'tombai':80,'thombhai':80,
        'navvai':90,'navai':90,
    }
    te_units = {
        'okati':1,'okka':1,'rendu':2,'madu':3,'mudu':3,
        'nalugu':4,'ayidu':5,'aidu':5,'aaru':6,'edu':7,'enimidi':8,'tommidi':9,
    }
    for t_word, t_val in te_tens.items():
        for u_word, u_val in te_units.items():
            compounds[t_word + ' ' + u_word] = str(t_val + u_val)

    # Hindi: tens + units spoken separately e.g. "tees paanch"=35
    hi_tens = {'das':10,'bees':20,'bis':20,'tees':30,'tis':30,'chalis':40,'chalees':40,
               'pachas':50,'panchas':50,'saath':60,'sattar':70,'assi':80,'nabbe':90}
    hi_units = {'ek':1,'do':2,'teen':3,'char':4,'paanch':5,'chhe':6,'che':6,
                'saat':7,'aath':8,'nau':9}
    for t_word, t_val in hi_tens.items():
        for u_word, u_val in hi_units.items():
            key = t_word + ' ' + u_word
            if key not in compounds:
                compounds[key] = str(t_val + u_val)

    # Tamil: tens + units e.g. "irupathu onru"=21
    ta_tens = {'pathu':10,'patthu':10,'irupathu':20,'muppathu':30,'naarpathu':40,
               'narpathu':40,'aimpathu':50,'ampathu':50,'aruvathu':60,'ezhuvathu':70,
               'enpathu':80,'thonnuru':90}
    ta_units = {'onru':1,'ondru':1,'irandu':2,'moondru':3,'mundru':3,'naangu':4,
                'nangu':4,'ainthu':5,'aindhu':5,'aaru':6,'ezhu':7,'ettu':8,'onbathu':9,'ombathu':9}
    for t_word, t_val in ta_tens.items():
        for u_word, u_val in ta_units.items():
            key = t_word + ' ' + u_word
            if key not in compounds:
                compounds[key] = str(t_val + u_val)

    # Malayalam: tens + units e.g. "iruppathu onnu"=21
    ml_tens = {'pathu':10,'iruppathu':20,'muppatu':30,'muppathu':30,'nalppathu':40,
               'nalpathu':40,'anpathu':50,'ampathu':50,'arupathu':60,'ezhupathu':70,
               'enpathu':80,'thonnuru':90}
    ml_units = {'onnu':1,'randu':2,'moonnu':3,'naalu':4,'anchu':5,
                'aaru':6,'ezhu':7,'ettu':8,'onpathu':9,'onnpathu':9}
    for t_word, t_val in ml_tens.items():
        for u_word, u_val in ml_units.items():
            key = t_word + ' ' + u_word
            if key not in compounds:
                compounds[key] = str(t_val + u_val)

    # Sort longest first so multi-word matches take priority
    return dict(sorted(compounds.items(), key=lambda x: -len(x[0])))

COMPOUND_NUMBERS = _build_compounds()

# Keep TELUGU_AGES as alias for backward compat
TELUGU_AGES = {k:v for k,v in COMPOUND_NUMBERS.items()}

def words_to_digits(text):
    text = text.lower().strip()
    # First pass: replace compound phrases (longest match first)
    for phrase, num in COMPOUND_NUMBERS.items():
        text = text.replace(phrase, num)
    # Second pass: replace single number words
    for word, val in UNITS.items():
        text = re.sub(r'\b' + re.escape(word) + r'\b', str(val), text)
    return text

WORD_DIGITS = UNITS  # backward compat alias

def extract_mobile_from_text(text):
    converted = words_to_digits(text)
    digits = re.sub(r'\D', '', converted)
    if len(digits) >= 10:
        return digits[:10]
    elif len(digits) >= 6:
        return digits
    return None

def extract_age_from_text(text):
    t = text.lower().strip()
    # Check compound phrases first (e.g. "muppai rendu" = 32)
    for phrase, num in COMPOUND_NUMBERS.items():
        if phrase in t:
            n = int(num)
            if 1 <= n <= 120:
                return str(n)
    # Then convert all number words to digits and scan
    converted = words_to_digits(t)
    numbers = re.findall(r'\d+', converted)
    for n in numbers:
        if 1 <= int(n) <= 120:
            return n
    return None

# ─────────────────────────────
#  DEPARTMENT MAPPING
# ─────────────────────────────
DEPTS = {
    'Cardiology': {
        'floor':2,'fw':'Second Floor','doctor':'Dr. Rajesh Kumar','color':'#D92D20',
        'words':['chest pain','heart pain','heart attack','cardiac','palpitation',
                 'blood pressure','high bp','low bp','chest tightness','chest heaviness',
                 'arm numbness','heart failure','heart blockage','angina',
                 'cholesterol','hypertension','chest','heart','bp']
    },
    'Neurology': {
        'floor':3,'fw':'Third Floor','doctor':'Dr. Priya Sharma','color':'#7C3AED',
        'words':['seizure','epilepsy','paralysis','stroke','memory loss','migraine',
                 'numbness','trembling','nerve pain','brain pressure','vision problem',
                 'speech difficulty','dizziness','unconscious','fainting','brain','nerve']
    },
    'Orthopedics': {
        'floor':1,'fw':'First Floor','doctor':'Dr. Anil Verma','color':'#0369A1',
        'words':['fracture','bone','joint pain','knee pain','back pain','shoulder pain',
                 'hip pain','neck pain','spine','ankle','wrist','elbow','arthritis',
                 'muscle pain','ligament','disc','knee','back','shoulder','leg pain',
                 'hand pain','arm pain','foot pain','lower back']
    },
    'Pediatrics': {
        'floor':2,'fw':'Second Floor','doctor':'Dr. Sunita Rao','color':'#D97706',
        'words':['child','baby','infant','toddler','kid','vaccination','newborn',
                 'growth problem','childhood','pediatric']
    },
    'Gynecology': {
        'floor':3,'fw':'Third Floor','doctor':'Dr. Meena Pillai','color':'#DB2777',
        'words':['pregnancy','menstrual pain','irregular periods','vaginal discharge',
                 'breast pain','uterus','ovary','gynec','female problem','periods',
                 'menstruation','pregnancy complication','period']
    },
    'General Medicine': {
        'floor':1,'fw':'First Floor','doctor':'Dr. Suresh Nair','color':'#059669',
        'words':['fever','cough','cold','viral','flu','infection','weakness','fatigue',
                 'body pain','vomiting','nausea','diarrhea','constipation','acidity',
                 'gas','loss of appetite','headache','stomach pain','throat pain',
                 'eye pain','ear pain','skin rash','itching','allergy','diabetes',
                 'thyroid','anaemia','weight loss','swelling','jaundice','malaria',
                 'dengue','typhoid','tuberculosis','asthma','breathlessness',
                 'kidney problem','kidney stone','urinary problem','liver problem',
                 'stomach','throat','sore throat']
    },
    'Emergency': {
        'floor':0,'fw':'Ground Floor','doctor':'Emergency Team','color':'#DC2626',
        'words':['emergency','severe','accident','heavy bleeding','unconscious',
                 'trauma','heart attack','stroke','cannot breathe','breathing difficulty',
                 'cardiac arrest','coughing blood','blood in urine','injury']
    },
}
EM_WORDS = ['chest pain','heart attack','heavy bleeding','unconscious','seizure',
            'severe pain','accident','trauma','stroke','cannot breathe','breathing difficulty']

def map_departments(symptoms, emergency):
    """
    Uses Groq AI to determine departments like a real doctor would.
    Understands symptom relationships — fever+leg pain = General Medicine not Orthopedics.
    Returns (primary_dept, primary_info, all_depts_list)
    """
    if emergency:
        return 'Emergency', DEPTS['Emergency'], [{'name':'Emergency','floor':0,'fw':'Ground Floor','doctor':'Emergency Team','color':'#DC2626'}]

    lower = symptoms.lower()
    for w in EM_WORDS:
        if w in lower:
            return 'Emergency', DEPTS['Emergency'], [{'name':'Emergency','floor':0,'fw':'Ground Floor','doctor':'Emergency Team','color':'#DC2626'}]

    dept_list = [d for d in DEPTS.keys() if d != 'Emergency']

    prompt = f"""You are a hospital triage doctor. A patient has these symptoms: "{symptoms}"

Available departments: {', '.join(dept_list)}

Rules:
- Fever with body pain/leg pain/headache = General Medicine (viral fever, dengue, malaria)
- Chest pain, palpitation, BP issues, arm numbness = Cardiology
- Seizure, stroke, paralysis, memory loss, severe headache with vomiting = Neurology
- Bone fracture, joint pain, knee/back/shoulder pain WITHOUT fever = Orthopedics
- Pregnancy, periods, female reproductive issues = Gynecology
- Child/baby/infant patients = Pediatrics
- Everything else = General Medicine
- If symptoms belong to 2 different departments genuinely (e.g. knee fracture + chest pain) list both
- Maximum 2 departments

Respond ONLY with department names separated by comma. Nothing else.
Example: Cardiology
Example: General Medicine, Orthopedics"""

    try:
        raw = ask_groq(prompt, symptoms)
        # Parse response
        chosen = [d.strip() for d in raw.split(',')]
        # Validate — only accept known dept names
        valid = [d for d in chosen if d in DEPTS]
        if not valid:
            valid = ['General Medicine']
    except Exception:
        # Fallback to keyword scoring if Groq fails
        valid = ['General Medicine']
        scores = {}
        for dept, info in DEPTS.items():
            if dept == 'Emergency': continue
            score = sum(len(w.split()) for w in info['words'] if w in lower)
            if score > 0: scores[dept] = score
        if scores:
            valid = [max(scores, key=scores.get)]

    # Build response
    all_depts = []
    for dept_name in valid:
        if dept_name not in DEPTS: continue
        info = DEPTS[dept_name]
        all_depts.append({
            'name': dept_name,
            'floor': info['floor'],
            'fw': info['fw'],
            'doctor': info['doctor'],
            'color': info.get('color','#1252A3')
        })

    if not all_depts:
        gm = DEPTS['General Medicine']
        all_depts = [{'name':'General Medicine','floor':gm['floor'],'fw':gm['fw'],'doctor':gm['doctor'],'color':gm['color']}]

    primary = all_depts[0]['name']
    return primary, DEPTS[primary], all_depts

def map_department(symptoms, emergency):
    p, info, _ = map_departments(symptoms, emergency)
    return p, info

# ─────────────────────────────
#  TTS ENDPOINT — uses gTTS
#  Supports ALL Indian languages
#  No API key needed — free Google TTS
# ─────────────────────────────
GTTS_LANG_CODES = {
    'English':   'en',
    'Hindi':     'hi',
    'Telugu':    'te',
    'Tamil':     'ta',
    'Malayalam': 'ml',
}

@app.route('/tts', methods=['POST'])
def tts():
    body   = request.json
    text   = body.get('text', '')
    lang   = body.get('lang', 'English')

    if not text:
        return jsonify({'error': 'no text'}), 400

    lang_code = GTTS_LANG_CODES.get(lang, 'en')

    try:
        from gtts import gTTS
        tts_obj = gTTS(text=text, lang=lang_code, slow=False)
        mp3_fp  = io.BytesIO()
        tts_obj.write_to_fp(mp3_fp)
        mp3_fp.seek(0)
        return Response(mp3_fp.read(), mimetype='audio/mpeg')
    except ImportError:
        return jsonify({'error': 'gTTS not installed. Run: pip install gtts'}), 500
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ─────────────────────────────
#  SERVE FRONTEND
# ─────────────────────────────
@app.route('/')
@app.route('/app')
def serve_frontend():
    frontend_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        '..', 'frontend'
    )
    return send_from_directory(frontend_path, 'index.html')

# ─────────────────────────────
#  DETECT LANGUAGE
# ─────────────────────────────
@app.route('/detect-language', methods=['POST'])
def detect_language():
    transcript = request.json.get('transcript','')
    lang_raw = ask_groq(
        "Identify the language of this spoken text. "
        "Return ONLY one word from: English, Hindi, Telugu, Tamil, Malayalam. "
        "Default to English if unsure.",
        transcript
    )
    lang = lang_raw.strip()
    if lang not in ['English','Hindi','Telugu','Tamil','Malayalam']:
        lang = 'English'

    questions = {
        "English": {"name":"What is your full name?","age":"How old are you?",
            "mobile":"Please say your 10-digit mobile number digit by digit.",
            "symptoms":"Please describe your health problem.","days":"How many days have you had this problem?"},
        "Hindi":   {"name":"आपका पूरा नाम क्या है?","age":"आपकी उम्र क्या है?",
            "mobile":"कृपया अपना 10 अंकों का मोबाइल नंबर बोलें।",
            "symptoms":"अपनी बीमारी के बारे में बताएं।","days":"कितने दिनों से परेशान हैं?"},
        "Telugu":  {"name":"మీ పూర్తి పేరు చెప్పండి.","age":"మీ వయసు ఎంత?",
            "mobile":"మీ 10 అంకెల మొబైల్ నంబర్ చెప్పండి.",
            "symptoms":"మీ అనారోగ్యం గురించి చెప్పండి.","days":"ఎన్ని రోజులుగా ఈ సమస్య ఉంది?"},
        "Tamil":   {"name":"உங்கள் முழு பெயர் சொல்லுங்கள்.","age":"உங்கள் வயது என்ன?",
            "mobile":"உங்கள் 10 இலக்க மொபைல் எண் சொல்லுங்கள்.",
            "symptoms":"உங்கள் உடல்நல பிரச்சனையை சொல்லுங்கள்.","days":"எத்தனை நாட்களாக இந்த பிரச்சனை?"},
        "Malayalam":{"name":"നിങ്ങളുടെ പൂർണ്ണ പേര് പറയൂ.","age":"നിങ്ങൾക്ക് എത്ര വയസ്സ്?",
            "mobile":"നിങ്ങളുടെ 10 അക്ക മൊബൈൽ നമ്പർ പറയൂ.",
            "symptoms":"നിങ്ങളുടെ ആരോഗ്യ പ്രശ്നം പറയൂ.","days":"എത്ര ദിവസമായി ഈ പ്രശ്നം?"},
    }
    return jsonify({'language': lang, 'questions': questions.get(lang, questions['English'])})

# ─────────────────────────────
#  EXTRACT FIELD
# ─────────────────────────────
@app.route('/extract', methods=['POST'])
def extract():
    body       = request.json
    field      = body.get('field','')
    transcript = body.get('transcript','').strip()
    lang       = body.get('lang','English')
    extracted  = ''

    if field == 'name':
        # Extract name AND transliterate to English Roman letters
        try:
            extracted = ask_groq(
                "Extract the person's name from this text and write it in English Roman letters only. "
                "Remove filler phrases like 'my name is', 'mera naam', 'naa peru', 'en peyar', 'ente peru' etc. "
                "If name is in Telugu/Hindi/Tamil/Malayalam script, transliterate it to English. "
                "Example: 'నా పేరు పూర్ణిమ' → 'Purnima', 'मेरा नाम सुरेश' → 'Suresh'. "
                "Return ONLY the name in English letters, 1-3 words max.",
                transcript, max_tok=15)
            extracted = extracted.strip().title()
            words = extracted.split()
            if len(words) > 3:
                extracted = ' '.join(words[:2])
        except:
            words = transcript.strip().split()
            extracted = ' '.join(words[-2:]).title() if len(words) >= 2 else 'Patient'

    elif field == 'age':
        # No Groq — use number conversion locally
        age = extract_age_from_text(transcript)
        if age:
            extracted = age
        else:
            t_lower = transcript.lower().strip()
            for phrase, num in COMPOUND_NUMBERS.items():
                if phrase in t_lower:
                    n = int(num)
                    if 1 <= n <= 120:
                        extracted = str(n)
                        break
            if not extracted:
                raw = ask_groq(
                    "Extract age number only (1-120). Return ONLY digits.",
                    "Patient said: " + transcript, max_tok=10)
                digits = re.sub(r"\D","",raw)
                extracted = digits if digits and 1<=int(digits or 0)<=120 else 'Unknown'

    elif field == 'mobile':
        # No Groq — pure local extraction
        mobile = extract_mobile_from_text(transcript)
        extracted = mobile if mobile and len(mobile) >= 8 else 'Not provided'

    elif field == 'symptoms':
        # Better symptom extraction with body part awareness
        sym_prompt = (
            "You are a medical assistant. Patient spoke in " + lang + ". "
            "Extract their health symptoms as 1-4 clear English medical terms. "
            "IMPORTANT: Combine body part + pain as one term. Examples: "
            "kai vali = hand pain, kaal vali = leg pain, "
            "kadupu noppi = stomach pain, tala noppi = headache, "
            "gunde noppi = chest pain, muru noppi = knee pain, "
            "veepu noppi = back pain, melu noppi = neck pain. "
            "Language hints - "
            "Telugu: noppi=pain,jwaram=fever,daggulu=cough,vanthi=vomit,gunde=chest,tala=head,kadupu=stomach,kalu=leg,kai=hand,veepu=back,muru=knee. "
            "Hindi: dard=pain,bukhar=fever,khansi=cough,ulti=vomit,seena=chest,sar=head,pet=stomach,pair=leg,haath=hand,kamar=back,ghutna=knee. "
            "Tamil: vali=pain,kaichal=fever,irumal=cough,vanthi=vomit,nenja=chest,thalai=head,vayiru=stomach,kaal=leg,kai=hand,muppu=back. "
            "Malayalam: veda=pain,pani=fever,irumal=cough,oki=vomit,maarbu=chest,thala=head,vayaru=stomach,kaal=leg,kai=hand,novu=pain. "
            "Rules: Return ONLY English medical terms comma separated. Max 4 terms. "
            "Keep body+pain together as one term like 'hand pain' not separate 'hand' and 'pain'."
        )
        extracted = ask_groq(sym_prompt, "Patient said: " + transcript, max_tok=60)
        if not extracted or len(extracted) > 150:
            extracted = 'general complaint'

    elif field == 'days':
        # Try local first
        t = transcript.lower()
        day_map = {
            'one day':'1 day','two days':'2 days','three days':'3 days',
            'four days':'4 days','five days':'5 days',
            'one week':'1 week','two weeks':'2 weeks','one month':'1 month',
            'okati roju':'1 day','rendu rojulu':'2 days','madu rojulu':'3 days',
            'oka vaaram':'1 week','rendu vaaram':'2 weeks','oka nela':'1 month',
            'ek din':'1 day','do din':'2 days','teen din':'3 days',
            'ek hafte':'1 week','ek mahina':'1 month',
            'oru naal':'1 day','irandu naal':'2 days','oru vaaram':'1 week',
            'oru divasam':'1 day','randu divasam':'2 days','oru azhcha':'1 week',
        }
        found = None
        for phrase, val in day_map.items():
            if phrase in t:
                found = val
                break
        if found:
            extracted = found
        else:
            nums = re.findall(r"\d+", words_to_digits(transcript))
            if nums:
                n = int(nums[0])
                extracted = str(n) + (" day" if n==1 else " days") if n<=30 else str(n)+" weeks"
            else:
                raw = ask_groq(
                    "Convert to duration. Return ONLY like: 3 days or 1 week",
                    "Patient said: " + transcript, max_tok=15)
                extracted = raw.strip().split("\n")[0][:25] if raw else '1 day'

    return jsonify({'extracted': extracted.strip() if extracted else 'Unknown'})


@app.route('/process', methods=['POST'])
def process():
    body      = request.json
    symptoms  = body.get('symptoms','')
    days      = body.get('days','')
    emergency = body.get('emergency', False)
    name      = body.get('name','')
    age       = body.get('age','')
    mobile    = body.get('mobile','')
    language  = body.get('language','English')

    for w in EM_WORDS:
        if w in symptoms.lower():
            emergency = True
            break

    dept_name, dept_info, all_depts = map_departments(symptoms, emergency)
    keywords  = [k.strip() for k in symptoms.split(',') if k.strip()]
    priority  = 'High' if emergency else 'Normal'

    reg_no, token = save_patient({
        'name':name,'age':age,'mobile':mobile,'symptoms':symptoms,'days':days,
        'department':dept_name,'floor':dept_info['floor'],'floorWord':dept_info['fw'],
        'emergency':emergency,'priority':priority,'doctor':dept_info['doctor'],'language':language
    })
    send_sms(mobile,'registration',token,dept_name,dept_info['floor'],language)
    return jsonify({
        'department':dept_name,'floor':dept_info['floor'],'floorWord':dept_info['fw'],
        'doctor':dept_info['doctor'],'keywords':keywords,'days':days,
        'priority':priority,'registration_number':reg_no,'emergency':emergency,
        'token_number':token,'all_departments':all_depts
    })

# ─────────────────────────────
#  VIEW PATIENTS
# ─────────────────────────────
@app.route('/patients', methods=['GET'])
def get_patients():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT * FROM patients ORDER BY id DESC LIMIT 100")
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return jsonify(rows)

# ─────────────────────────────
#  ADMIN DASHBOARD ROUTES
# ─────────────────────────────
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "voicebyte2024")

@app.route('/admin')
def admin_page():
    auth = request.args.get('key','')
    if auth != ADMIN_PASSWORD:
        wrong = request.args.get('key') is not None
        return f'''<html><body style="font-family:sans-serif;display:flex;align-items:center;
        justify-content:center;height:100vh;margin:0;background:#0F2137;">
        <div style="background:white;padding:40px;border-radius:16px;text-align:center;width:320px;box-shadow:0 20px 60px rgba(0,0,0,0.5);">
          <div style="font-size:48px">🏥</div>
          <h2 style="color:#1252A3;margin:10px 0">VoiceByte Admin</h2>
          <p style="color:#666;font-size:14px;margin-bottom:20px">Doctors only. Enter password to continue.</p>
          <form method="GET">
            <input name="key" type="password" placeholder="Enter admin password"
              style="width:100%;padding:12px;border:2px solid #ddd;border-radius:8px;
              font-size:15px;box-sizing:border-box;margin-bottom:12px;outline:none;"/>
            <button type="submit"
              style="width:100%;padding:12px;background:#1252A3;color:white;
              border:none;border-radius:8px;font-size:16px;cursor:pointer;font-weight:700;">
              🔐 Login
            </button>
          </form>
          {'<p style="color:red;font-size:13px;margin-top:10px;">❌ Wrong password. Try again.</p>' if wrong else ''}
        </div></body></html>''', 401

    # Find Admin.html — works both locally and on Render
    base = os.path.dirname(os.path.abspath(__file__))
    candidates = [
        os.path.join(base, '..', 'frontend', 'Admin.html'),
        os.path.join(base, 'frontend', 'Admin.html'),
        os.path.join(base, '..', 'frontend', 'admin.html'),
        os.path.join(base, 'Admin.html'),
        os.path.join(base, 'admin.html'),
    ]
    for path in candidates:
        if os.path.exists(path):
            return send_from_directory(os.path.dirname(path), os.path.basename(path))
    return "Admin page not found. Check Admin.html is in frontend folder.", 404

@app.route('/admin/queue')
def admin_queue():
    today = datetime.now().strftime('%Y-%m-%d')
    conn  = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT * FROM patients WHERE DATE(visit_time)=? ORDER BY token_number ASC",(today,))
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return jsonify(rows)

@app.route('/admin/call',methods=['POST'])
def admin_call():
    """Mark patient as 'called' (being seen) and fire SMS."""
    pid = request.json.get('id')
    if not pid: return jsonify({'error':'missing id'}),400
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("UPDATE patients SET status='called' WHERE id=?",(pid,))
    conn.commit()
    c.execute("SELECT * FROM patients WHERE id=?",(pid,))
    row = dict(c.fetchone())
    conn.close()
    send_sms(row.get('mobile',''),'called',row.get('token_number',0),row.get('department',''),row.get('floor_number',1),row.get('language','English'))
    return jsonify({'ok':True,'sms_sent':bool(FAST2SMS_KEY)})

@app.route('/admin/seen',methods=['POST'])
def admin_seen():
    """Mark patient as fully 'seen' (completed)."""
    pid = request.json.get('id')
    if not pid: return jsonify({'error':'missing id'}),400
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("UPDATE patients SET status='seen' WHERE id=?",(pid,))
    conn.commit()
    c.execute("SELECT * FROM patients WHERE id=?",(pid,))
    row = dict(c.fetchone())
    conn.close()
    return jsonify({'ok':True})

@app.route('/admin/stats')
def admin_stats():
    today = datetime.now().strftime('%Y-%m-%d')
    conn  = sqlite3.connect(DB_PATH)
    c     = conn.cursor()
    c.execute("SELECT COUNT(*) FROM patients WHERE DATE(visit_time)=?",(today,))
    total = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM patients WHERE DATE(visit_time)=? AND emergency=1",(today,))
    emerg = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM patients WHERE DATE(visit_time)=? AND status='seen'",(today,))
    seen  = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM patients WHERE DATE(visit_time)=? AND status='called'",(today,))
    called= c.fetchone()[0]
    c.execute("SELECT department,COUNT(*) as n FROM patients WHERE DATE(visit_time)=? GROUP BY department ORDER BY n DESC LIMIT 1",(today,))
    r = c.fetchone()
    top  = r[0] if r else 'None'
    conn.close()
    return jsonify({'total':total,'emergencies':emerg,'seen':seen,'called':called,'waiting':total-seen-called,'top_dept':top})

@app.route('/health')
def health():
    return jsonify({'status':'VoiceByte OK'})

if __name__ == '__main__':
    init_db()
    print("✅ VoiceByte backend started!")
    print("🌐 Open Chrome → http://127.0.0.1:5000")
    print("")
    print("📦 Make sure gTTS is installed:")
    print("   pip install gtts")
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)), debug=False)