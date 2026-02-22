from flask import Flask, request, jsonify, send_from_directory, Response
from flask_cors import CORS
from groq import Groq
from dotenv import load_dotenv
import os, sqlite3, uuid, re, io, urllib.request, json as _json
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
        data = _json.dumps({"route":"v3","message":msg,"language":"english","flash":0,"numbers":str(mobile)[-10:]}).encode()
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
def ask_groq(system_prompt, user_msg):
    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": user_msg}
        ],
        max_tokens=150,
        temperature=0.0
    )
    return response.choices[0].message.content.strip()

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
    'Cardiology':       {'floor':2,'words':['chest','heart','bp','palpitation','cardiac','blood pressure'],'doctor':'Dr. Rajesh Kumar','fw':'Second Floor'},
    'Neurology':        {'floor':3,'words':['head','brain','seizure','migraine','dizzy','dizziness','stroke','nerve'],'doctor':'Dr. Priya Sharma','fw':'Third Floor'},
    'Orthopedics':      {'floor':1,'words':['bone','fracture','knee','back','leg','arm','joint','spine','shoulder'],'doctor':'Dr. Anil Verma','fw':'First Floor'},
    'Pediatrics':       {'floor':2,'words':['child','baby','infant','vaccination','kid','toddler'],'doctor':'Dr. Sunita Rao','fw':'Second Floor'},
    'Gynecology':       {'floor':3,'words':['pregnancy','menstrual','period','female','gynec','uterus'],'doctor':'Dr. Meena Pillai','fw':'Third Floor'},
    'General Medicine': {'floor':1,'words':['fever','cough','cold','infection','weakness','fatigue','viral','flu','pain','stomach','body','vomit','nausea','headache'],'doctor':'Dr. Suresh Nair','fw':'First Floor'},
    'Emergency':        {'floor':0,'words':['emergency','severe','accident','bleeding','unconscious','trauma','heart attack','stroke'],'doctor':'Emergency Team','fw':'Ground Floor'},
}
EM_WORDS = ['chest pain','heart attack','heavy bleeding','unconscious','seizure',
            'severe pain','accident','trauma','stroke','cannot breathe','breathing difficulty']

def map_department(symptoms, emergency):
    if emergency:
        return 'Emergency', DEPTS['Emergency']
    lower = symptoms.lower()
    for dept, info in DEPTS.items():
        for word in info['words']:
            if word in lower:
                return dept, info
    return 'General Medicine', DEPTS['General Medicine']

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
    transcript = body.get('transcript','')
    extracted  = ''

    lang = body.get('lang', 'English')

    if field == 'name':
        extracted = ask_groq(
            "Extract the person's name from this speech transcript. "
            "The person spoke in " + lang + ". "
            "Return ONLY the name, nothing else. Capitalize properly.",
            transcript)
        extracted = extracted.strip().title()

    elif field == 'age':
        # First try direct digit extraction
        age = extract_age_from_text(transcript)
        if age:
            extracted = age
        else:
            # Try Telugu/Tamil compound number lookup
            t_lower = transcript.lower().strip()
            found = None
            for phrase, num in TELUGU_AGES.items():
                if phrase in t_lower:
                    found = num
                    break
            if found:
                extracted = found
            else:
                # Ask Groq with full language context — must reject non-age input
                raw = ask_groq(
                    "The patient was asked 'How old are you?' and replied in " + lang + ".\n"
                    "Does their reply contain a number that represents an age (1-120)?\n"
                    "If YES: return ONLY that number (e.g. 25). No words, no explanation.\n"
                    "If NO (random words, name, movie title, unclear): return exactly: Unknown\n\n"
                    "Number words - Telugu: okati=1,rendu=2,madu=3,nalugu=4,ayidu=5,"
                    "aaru=6,edu=7,enimidi=8,tommidi=9,padi=10,iravai=20,muppai=30,nalabhai=40,yabhai=50. "
                    "Tamil: onru=1,irandu=2,moondru=3,pathu=10,irupathu=20,muppathu=30. "
                    "Hindi: ek=1,do=2,teen=3,bees=20,tees=30,chalis=40.\n"
                    "IMPORTANT: Only return a number if the input is clearly an age response. "
                    "Do NOT extract numbers from unrelated words, names, or movie titles.",
                    "Patient said: " + transcript)
                digits_only = re.sub(r'\D','',raw)
                if digits_only and 1 <= int(digits_only) <= 120:
                    extracted = digits_only
                else:
                    extracted = 'Unknown'

    elif field == 'mobile':
        mobile = extract_mobile_from_text(transcript)
        if mobile and len(mobile) >= 8:
            extracted = mobile
        else:
            raw = ask_groq(
                "Convert this to phone number digits only. "
                "'nine'=9,'eight'=8,'seven'=7,'six'=6,'five'=5,'four'=4,'three'=3,'two'=2,'one'=1,'zero'=0. "
                "Return ONLY digits no spaces.", transcript)
            digits = re.sub(r'\D','',raw)
            extracted = digits[:10] if digits else 'Not provided'

    elif field == 'symptoms':
        extracted = ask_groq(
            "You are a medical transcription assistant. The patient spoke in " + lang + ".\n"
            "TASK: Translate ONLY what they said into 1-4 English medical keywords.\n\n"

            "=== TELUGU MEDICAL DICTIONARY ===\n"
            # Body pain
            "kadupu noppi/vayiru noppi/veepu noppi/belly noppi=stomach pain, "
            "nadumu noppi/naduma noppi=back pain, "
            "tala noppi/tala deba=headache, "
            "gunde noppi/chati noppi/gurra noppi=chest pain, "
            "gola noppi/ganthu noppi=throat pain, "
            "cheyyi noppi/chetu noppi=hand pain, "
            "kalu noppi/legs noppi=leg pain, "
            "motu noppi/mokkalu noppi=knee pain, "
            "kanna noppi/kannu noppi=eye pain, "
            "chevi noppi=ear pain, "
            "meda noppi/melam noppi=neck pain, "
            "chankalu noppi=hip pain, "
            "mokkal noppi/sandhi noppi=joint pain, "
            "bhuja noppi/melupu noppi=shoulder pain, "
            "mungu noppi/mukha noppi=face pain, "
            # Heart
            "gunde noppi/gunde vedana=heart pain, "
            "gunde moraipothundi/gunde strike aipothundi=heart attack, "
            "gunde dorikipothundi/gunde veganga kottukuntundi=heart palpitation, "
            "gunde aagipothundi=cardiac arrest, "
            "gunde pani cheyyatledu=heart failure, "
            "gunde block/arteries block=heart blockage, "
            "gunde vapu/chest heavy=chest heaviness, "
            "cheyyi numbness/cheyyi timmiraipothundi=arm numbness, "
            # Brain / Neurological
            "tala noppi/matham noppi=headache, "
            "tala tirugutundi/tala ghurugunna=dizziness, "
            "fits/mirgi/fits vachindi=seizure/epilepsy, "
            "paralisys/sarbhaga kottindi=paralysis/stroke, "
            "nerves weakness/naadi bayata pettindi=nerve weakness, "
            "maatalu raatledu/nalukanoppi=speech difficulty, "
            "kannu saraga kanpistundi ledu=vision problem, "
            "memory poindi/gurthu poyindi=memory loss, "
            "tala bharam/brain pressure=brain pressure, "
            "migraine/tala mantha noppi=migraine, "
            "unconscious/sense ledu/murchha=unconscious, "
            "hand foot timmiri/numbness=numbness, "
            "trembling/chetulu adugutunnai=trembling, "
            # Fever / infections
            "jwaram/jwarum/veyyi/vegam=fever, "
            "dengue jwaram/dengue=dengue fever, "
            "malaria jwaram/malaria=malaria, "
            "typhoid/typhoid jwaram=typhoid, "
            "corona/covid=covid, "
            "chikkenpox/annapurna/murichalu=chickenpox, "
            "jaundice/kamala vyadhi/kannu pacchabadiindi=jaundice, "
            "TB/tuberculosis/daggulu blood vastundi=tuberculosis, "
            "jadam/chali jwaram=chills, "
            "daggulu/khanam=cough, "
            "tummulu=sneezing, "
            "mukku kaaram/mukku padam=runny nose, "
            "gola naripothundi=sore throat, "
            # Stomach / digestion
            "vanthi/vomit aipothundi=vomiting, "
            "vanthi bhavana/vankara=nausea, "
            "bathukamma/belly burning=acidity, "
            "bathrooms ekkuva/loose motions=diarrhea, "
            "malabandham/pottu kaadu=constipation, "
            "gas problem/vayu=gas, "
            "aakali ledu=loss of appetite, "
            "liver problem/yakrit vyadhi=liver problem, "
            "piles/mulavyadhi/gudda blood=piles/hemorrhoids, "
            "appendix noppi=appendix pain, "
            "hernia=hernia, "
            "ulcer/kadupu lo puta=stomach ulcer, "
            # Breathing / lungs
            "usmiri aadustundi/usmiri tirugutundi=breathlessness, "
            "asthma/dama=asthma, "
            "chest tight=chest tightness, "
            "lungs infection/nippu tagu=lung infection, "
            "pneumonia=pneumonia, "
            "blood with cough/daggulu lo blood=coughing blood, "
            # Diabetes / BP / thyroid
            "sugar vyadhi/madhumeham=diabetes, "
            "blood sugar ekkuva=high blood sugar, "
            "blood sugar taggindi=low blood sugar, "
            "pressure ekkuva/BP ekkuva=high blood pressure, "
            "pressure taggindi/BP taggindi=low blood pressure, "
            "thyroid/thyroid problem=thyroid, "
            "weight ekkuva avuthundi=weight gain, "
            "weight taggindi=weight loss, "
            "cholesterol ekkuva=high cholesterol, "
            # Kidney / urinary
            "kidney problem/mootra pitham=kidney problem, "
            "kidney stone/kallu=kidney stone, "
            "mootram povatledu/mootram kashtam=urinary problem, "
            "mootram manta=burning urination, "
            "mootram ekkuva=frequent urination, "
            "mootram lo blood=blood in urine, "
            "dialysis=dialysis, "
            # Skin
            "charmavyadhi/gajji=skin rash, "
            "marugu/itching=itching, "
            "gaayal/puta=wound, "
            "vundlu=boils, "
            "psoriasis/charmavyadhi=psoriasis, "
            "allergy/allergy reaction=allergy, "
            # Eyes / ears / nose
            "kannu errabadiindi=red eye, "
            "kannu vadam=eye discharge, "
            "chevi paaduthundi=ear discharge, "
            "mukku moosukovatledu=blocked nose, "
            "cataract/kannu madhyalo tella=cataract, "
            "glaucoma/kannu pressure=glaucoma, "
            # Women's health
            "periods noppi/monthly noppi=menstrual pain, "
            "irregular periods=irregular periods, "
            "pregnancy problem=pregnancy complication, "
            "breast noppi=breast pain, "
            "white discharge=vaginal discharge, "
            # Mental health
            "depression/manasu bayam=depression, "
            "bayam/anxiety=anxiety, "
            "nidra lekapovudam=insomnia, "
            "stress ekkuva=stress, "
            # General
            "neradu/aayaasam=weakness/fatigue, "
            "tala tirugutundi=dizziness, "
            "muttukopovudam=fainting, "
            "body antha noppi=body pain, "
            "blood anaemia/rakt heenata=anaemia, "
            "swelling/veepu=swelling, "
            "accident/gaayal=injury/accident, "
            "fracture/elumbu virigindi=fracture, "

            "\n=== HINDI MEDICAL DICTIONARY ===\n"
            # Body pain
            "pet dard/pet mein dard/pait dard=stomach pain, "
            "kamar dard/peeth dard=back pain, "
            "sar dard/sir dard=headache, "
            "seene mein dard/chati mein dard=chest pain, "
            "gale mein dard/gala dard=throat pain, "
            "haath mein dard=hand pain, "
            "pair mein dard/taang dard=leg pain, "
            "ghutne mein dard=knee pain, "
            "aankh mein dard/aankh jalti hai=eye pain, "
            "kaan mein dard=ear pain, "
            "gardan dard=neck pain, "
            "jodon mein dard/haddi dard=joint pain, "
            "kandhe mein dard=shoulder pain, "
            "kamar neeche dard=lower back pain, "
            # Heart
            "dil mein dard/dil dukh raha=heart pain, "
            "heart attack/dil ka daura=heart attack, "
            "dil tez dhak raha/dhadkan tez hai=heart palpitation, "
            "dil band ho gaya/cardiac arrest=cardiac arrest, "
            "dil ki nali band/heart blockage=heart blockage, "
            "seene mein bhaari pan=chest heaviness, "
            "haath sone laga/haath sunn=arm numbness, "
            "dil kamzor hai=heart failure, "
            # Brain / Neurological
            "chakkar aana=dizziness, "
            "mirgi/fits aana=seizure/epilepsy, "
            "laqwa/paralysis/stroke=paralysis/stroke, "
            "yaaddasht kam ho gayi=memory loss, "
            "bolne mein takleef=speech difficulty, "
            "aankhon se dhundhla dikhta=vision problem, "
            "dimag mein dard/dimag bhaari=brain pressure, "
            "migraine/aadha sar dard=migraine, "
            "behoshi/hosh nahi=unconscious, "
            "haath pair sunn ho gaye=numbness, "
            "kaanpna/haath kaanpte hain=trembling, "
            "nerve dard/nason mein dard=nerve pain, "
            # Fever / infections
            "bukhar/tez bukhar/jwar=fever, "
            "dengue/dengue bukhar=dengue fever, "
            "malaria/thandi ke saath bukhar=malaria, "
            "typhoid=typhoid, "
            "corona/covid=covid, "
            "chechak/chickenpox=chickenpox, "
            "peelia/jaundice/aankhein peeli=jaundice, "
            "TB/tuberculosis/khansi mein khoon=tuberculosis, "
            "kaanpna/thand lagti hai=chills, "
            "khansi=cough, "
            "chheenk=sneezing, "
            "naak behna/naak band=runny nose, "
            "gala kharab=sore throat, "
            # Stomach / digestion
            "ulti/vomiting=vomiting, "
            "matli/ji machlana=nausea, "
            "seene mein jalan/khatti dakar=acidity, "
            "dast/loose motions=diarrhea, "
            "kabz/potty nahi hoti=constipation, "
            "gas problem/pet phoolna=gas, "
            "bhook nahi lagti=loss of appetite, "
            "liver kharab/jigar ki bimari=liver problem, "
            "bawaseer/piles/gudey mein khoon=piles/hemorrhoids, "
            "appendix dard=appendix pain, "
            "hernia=hernia, "
            "pet mein chhaale/ulcer=stomach ulcer, "
            # Breathing / lungs
            "saans nahi aata/saans fulna=breathlessness, "
            "dama/asthma=asthma, "
            "seene mein khinchav=chest tightness, "
            "phaiphdon mein infection=lung infection, "
            "pneumonia=pneumonia, "
            "khansi mein khoon=coughing blood, "
            # Diabetes / BP / thyroid
            "sugar/madhumeh/diabetes=diabetes, "
            "sugar zyada hai=high blood sugar, "
            "sugar kam ho gayi=low blood sugar, "
            "BP zyada/high BP=high blood pressure, "
            "BP kam/low BP=low blood pressure, "
            "thyroid=thyroid, "
            "cholesterol zyada=high cholesterol, "
            # Kidney / urinary
            "gurde ki takleef/kidney problem=kidney problem, "
            "gurde mein pathri/kidney stone=kidney stone, "
            "peshab nahi hota=urinary problem, "
            "peshab mein jalan=burning urination, "
            "baar baar peshab=frequent urination, "
            "peshab mein khoon=blood in urine, "
            # Skin
            "charm rog/khujli/daane=skin rash, "
            "khujli=itching, "
            "zakhm/chot=wound, "
            "allergy=allergy, "
            "psoriasis=psoriasis, "
            # Eyes / ears
            "aankhein laal=red eye, "
            "cataract/aankhon mein safedi=cataract, "
            # Women's health
            "mahawari mein dard/periods dard=menstrual pain, "
            "irregular mahawari=irregular periods, "
            "pregnancy mein takleef=pregnancy complication, "
            "safed paani aana=vaginal discharge, "
            # Mental health
            "depression/udaasi=depression, "
            "ghabrahat/anxiety=anxiety, "
            "neend nahi aati=insomnia, "
            "stress/tanav=stress, "
            # General
            "kamzori/thakan=weakness/fatigue, "
            "behoshi=fainting, "
            "body dard/pura badan dard=body pain, "
            "khoon ki kami/anaemia=anaemia, "
            "sujan/soojhan=swelling, "
            "haddi tooti/fracture=fracture, "
            "accident/chot lagi=injury/accident, "
            "wajan kam ho raha=weight loss, "

            "\n=== TAMIL MEDICAL DICTIONARY ===\n"
            # Body pain
            "vayiru vali/thopu vali=stomach pain, "
            "mughu vali/idupu vali=back pain, "
            "thalai vali=headache, "
            "nenja vali/maarbu vali=chest pain, "
            "tholai vali=throat pain, "
            "kai vali=hand pain, "
            "kaal vali=leg pain, "
            "muzhangaal vali=knee pain, "
            "kann vali=eye pain, "
            "sevvi vali=ear pain, "
            "kazhuththu vali=neck pain, "
            "sandhi vali/moopu vali=joint pain, "
            "thole vali=shoulder pain, "
            # Heart
            "idhaya vali/nenja vali=heart pain, "
            "heart attack/idhaya aappu=heart attack, "
            "idhayam vega thudithal=heart palpitation, "
            "idhaya nilai thevermai=cardiac arrest, "
            "idhaya blockage=heart blockage, "
            "nenja kanamai=chest heaviness, "
            "kai maraththu=arm numbness, "
            # Brain / Neurological
            "thalaisuzhhal=dizziness, "
            "valappu noi/fits=seizure/epilepsy, "
            "paralysis/stroke/udal oru palam=paralysis/stroke, "
            "ninaivagam kulainthal=memory loss, "
            "pesum thiramillai=speech difficulty, "
            "paarvai kuraippu=vision problem, "
            "thalai azhuttam=brain pressure, "
            "migraine/oru thalai vali=migraine, "
            "maychal/sothy ponal=unconscious, "
            "kai kaal maraththu=numbness, "
            "kai nadungal=trembling, "
            # Fever / infections
            "kaichal/juram=fever, "
            "dengue kaichal=dengue fever, "
            "malaria=malaria, "
            "typhoid=typhoid, "
            "corona/covid=covid, "
            "siththu ammai/chickenpox=chickenpox, "
            "kamaalai/jaundice/kann manjal=jaundice, "
            "TB/maarbagam/irumalil blood=tuberculosis, "
            "ndukkam=chills, "
            "irumal=cough, "
            "thummal=sneezing, "
            "mookku oothutal=runny nose, "
            "tholai noi=sore throat, "
            # Stomach / digestion
            "vanthi=vomiting, "
            "kuruttai=nausea, "
            "nenju erikal/aambam=acidity, "
            "vayitru oothal/loose motions=diarrhea, "
            "malachikkal=constipation, "
            "vatham/gas=gas, "
            "pasiyillai=loss of appetite, "
            "liver pirachchanai=liver problem, "
            "moolam/piles=piles/hemorrhoids, "
            "appendix vali=appendix pain, "
            "hernia=hernia, "
            "ulcer/vayiru punn=stomach ulcer, "
            # Breathing / lungs
            "moochu thirumbal=breathlessness, "
            "iral noi/asthma=asthma, "
            "nenja izhukku=chest tightness, "
            "neeraikal infection=lung infection, "
            "pneumonia=pneumonia, "
            "irumalil blood=coughing blood, "
            # Diabetes / BP / thyroid
            "sarkkarai noi/neerizhu/diabetes=diabetes, "
            "sarkkarai adhikam=high blood sugar, "
            "sarkkarai kuranthal=low blood sugar, "
            "rattham azhuththam adhigam/high BP=high blood pressure, "
            "rattham azhuththam kurangal/low BP=low blood pressure, "
            "thyroid=thyroid, "
            "cholesterol adhigam=high cholesterol, "
            # Kidney / urinary
            "siruneeragam pirachchanai/kidney problem=kidney problem, "
            "kidney kallu=kidney stone, "
            "saluval pirachchanai=urinary problem, "
            "saluval erikal=burning urination, "
            "adikhama saluval=frequent urination, "
            "saluvalil blood=blood in urine, "
            # Skin
            "tholnoi/thadippu/themal=skin rash, "
            "arippu=itching, "
            "kaayam/punn=wound, "
            "allergy=allergy, "
            # Eyes / ears
            "kann sivappu=red eye, "
            "kann padam/cataract=cataract, "
            # Women's health
            "maadhavidai vali/periods vali=menstrual pain, "
            "irregular periods=irregular periods, "
            "pregnancy pirachchanai=pregnancy complication, "
            "vella paduthal=vaginal discharge, "
            # Mental health
            "manam theivu/depression=depression, "
            "arimugiyamai/anxiety=anxiety, "
            "thoongamai=insomnia, "
            "stress=stress, "
            # General
            "udalsustu/thalarchi=weakness/fatigue, "
            "maychal=fainting, "
            "udal vali=body pain, "
            "rattham kudaiyamai/anaemia=anaemia, "
            "veekkam/sujai=swelling, "
            "eluumbu murivu/fracture=fracture, "
            "edai kurangal=weight loss, "

            "\n=== MALAYALAM MEDICAL DICTIONARY ===\n"
            # Body pain
            "vayaru veda/vayar vali=stomach pain, "
            "nada veda/mughu veda=back pain, "
            "thalavedan/thala veda=headache, "
            "nenja veda/maarbu veda=chest pain, "
            "tholai veda/gala veda=throat pain, "
            "kai veda=hand pain, "
            "kaal veda=leg pain, "
            "muthukaal veda=knee pain, "
            "kann veda=eye pain, "
            "chevy veda=ear pain, "
            "kazhuththu veda=neck pain, "
            "sandhiveda/moopu veda=joint pain, "
            "thole veda=shoulder pain, "
            # Heart
            "hridayaveda/maarbu veda=heart pain, "
            "heart attack/hridaya aappu=heart attack, "
            "hridayam vega thudikkunnu=heart palpitation, "
            "cardiac arrest/hridayam nilkkunnu=cardiac arrest, "
            "heart blockage=heart blockage, "
            "nenja bhaaram=chest heaviness, "
            "kai maraykkunnu=arm numbness, "
            "hridaya paripoorna=heart failure, "
            # Brain / Neurological
            "thalakanal/mathimutal=dizziness, "
            "fits/apasmaram=seizure/epilepsy, "
            "paralysis/stroke/shareeram thazharuka=paralysis/stroke, "
            "ormasakti kuranjal=memory loss, "
            "samsarikkan kashtam=speech difficulty, "
            "kaanaan kashtam=vision problem, "
            "thala pressure=brain pressure, "
            "migraine/oru thalavedan=migraine, "
            "behosha/ബോധം കെടൽ=unconscious, "
            "kai kaal marayuka=numbness, "
            "kai vayarkkunnu=trembling, "
            # Fever / infections
            "pani/jvaram=fever, "
            "dengue pani=dengue fever, "
            "malaria=malaria, "
            "typhoid=typhoid, "
            "corona/covid=covid, "
            "chickenpox/ammai=chickenpox, "
            "jaundice/manja pani/kann manjappam=jaundice, "
            "TB/tuberculosis/irumalil chora=tuberculosis, "
            "viryal/thanda=chills, "
            "irumal/chemal=cough, "
            "thummal=sneezing, "
            "mookku oothal=runny nose, "
            "tholai veda=sore throat, "
            # Stomach / digestion
            "oki/vanthi=vomiting, "
            "okkanam=nausea, "
            "nazhappu/amlam=acidity, "
            "vayyaru irakkam/loose motions=diarrhea, "
            "malachakku=constipation, "
            "vaayu/gas=gas, "
            "vishapilla=loss of appetite, "
            "liver prabhandam=liver problem, "
            "moolam/piles=piles/hemorrhoids, "
            "appendix veda=appendix pain, "
            "hernia=hernia, "
            "ulcer/vayar punn=stomach ulcer, "
            # Breathing / lungs
            "shwasam mudakkam=breathlessness, "
            "asthma/iral/dama=asthma, "
            "nenja izhukku=chest tightness, "
            "shwasakosha rogam=lung infection, "
            "pneumonia=pneumonia, "
            "irumalil chora=coughing blood, "
            # Diabetes / BP / thyroid
            "pramehm/sugar/diabetes=diabetes, "
            "sugar koothi=high blood sugar, "
            "sugar kuranja=low blood sugar, "
            "BP koothi/high BP=high blood pressure, "
            "BP kuranja/low BP=low blood pressure, "
            "thyroid=thyroid, "
            "cholesterol koothi=high cholesterol, "
            # Kidney / urinary
            "kidney prabhandam=kidney problem, "
            "kidney kallu=kidney stone, "
            "mutram prabhandam=urinary problem, "
            "mutram erikal=burning urination, "
            "mutram adikham=frequent urination, "
            "mutram chora=blood in urine, "
            # Skin
            "tvacha rogam/charma rogam/themal=skin rash, "
            "cheyyichil=itching, "
            "muram/punn=wound, "
            "allergy=allergy, "
            # Eyes / ears
            "kann chuvappu=red eye, "
            "cataract/kann velupp=cataract, "
            # Women's health
            "masika veda/periods veda=menstrual pain, "
            "irregular masikam=irregular periods, "
            "pregnancy prabhandam=pregnancy complication, "
            "vella sraavam=vaginal discharge, "
            # Mental health
            "vishada rogam/depression=depression, "
            "utkantha/anxiety=anxiety, "
            "urakkamedukkal=insomnia, "
            "stress=stress, "
            # General
            "ksheenatha/thalarcha=weakness/fatigue, "
            "behosha=fainting, "
            "udal veda=body pain, "
            "anaemia/raktha darbhalyam=anaemia, "
            "veekkam/neer ketti=swelling, "
            "elumbu murivu/fracture=fracture, "
            "accident/petti=injury/accident, "
            "thookam kurangal=weight loss\n\n"

            "STRICT RULES:\n"
            "- Return ONLY English keywords, comma-separated\n"
            "- DO NOT add symptoms the patient did not mention\n"
            "- DO NOT include any Indian language words in the output\n"
            "- Translate exactly what they said — do not change or expand it\n"
            "- Maximum 4 keywords",
            "Patient said: " + transcript)
        if not extracted or len(extracted) > 100 or 'no medical' in extracted.lower():
            extracted = ask_groq(
                "What body part or symptom is the patient describing? Return 1-3 English words only. "
                "Do not guess or add extra symptoms.",
                transcript)
        if not extracted or len(extracted) > 60:
            extracted = 'general complaint'

    elif field == 'days':
        extracted = ask_groq(
            "Convert this patient's duration statement to English. "
            "Telugu: okati roju=1 day, rendu rojulu=2 days, madu rojulu=3 days, "
            "oka vaaram=1 week, rendu vaaram=2 weeks, oka nela=1 month. "
            "Tamil: oru naal=1 day, irandu naal=2 days, oru vaaram=1 week, oru madam=1 month. "
            "Hindi: ek din=1 day, do din=2 days, ek hafte=1 week, ek mahina=1 month. "
            "Return ONLY the English duration like '2 days' or '1 week'. Nothing else.",
            "Patient said: " + transcript)
        # Clean up
        if not extracted or len(extracted) > 25 or 'no duration' in extracted.lower():
            nums = re.findall(r'\d+', words_to_digits(transcript))
            extracted = nums[0] + ' days' if nums else '1 day'
        # Remove any extra text
        extracted = extracted.strip().split('\n')[0][:25]

    return jsonify({'extracted': extracted.strip()})

# ─────────────────────────────
#  PROCESS & SAVE
# ─────────────────────────────
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

    dept_name, dept_info = map_department(symptoms, emergency)
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
        'priority':priority,'registration_number':reg_no,'emergency':emergency,'token_number':token
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
@app.route('/admin')
def admin_page():
    import os as _os
    for d in ['../frontend','frontend','.']:
        p = _os.path.join(d,'admin.html')
        if _os.path.exists(p):
            return send_from_directory(d,'admin.html')
    return "admin.html not found",404

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
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=False)