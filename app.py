import streamlit as st
import psycopg2
from psycopg2 import IntegrityError
import hashlib
import smtplib
import math
import cloudinary
import cloudinary.uploader
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timedelta, date

# --- CONFIGURATION & SECRETS ---
st.set_page_config(page_title="UniUyo Academic Hub", page_icon="🎓", layout="wide")

SENDER_EMAIL = "capzi01c@gmail.com"
SENDER_PASSWORD = st.secrets.get("EMAIL_PASS", "")
ADMIN_USERNAME = "caleb"

DB_URL = st.secrets.get("DB_URL", "")

cloudinary.config(
    cloud_name="dycllasey",
    api_key="582982192356838",
    api_secret="qReAT87xhDkf9OLvvTT6CgDcRgk",
    secure=True
)

# --- CACHED DATABASE CONNECTIONS (SPEED OPTIMIZATION) ---
def get_connection():
    return psycopg2.connect(DB_URL)

@st.cache_resource
def initialize_db_tables():
    conn = get_connection()
    c = conn.cursor()
    
    c.execute('''CREATE TABLE IF NOT EXISTS users (
                    id SERIAL PRIMARY KEY, 
                    username TEXT UNIQUE, 
                    email TEXT UNIQUE, 
                    password TEXT, 
                    department TEXT, 
                    usage_count INTEGER DEFAULT 0, 
                    profile_pic_url TEXT, 
                    points INTEGER DEFAULT 0,
                    last_calculated_gpa NUMERIC DEFAULT 0.00
                )''')

    c.execute('''ALTER TABLE users ADD COLUMN IF NOT EXISTS last_calculated_gpa NUMERIC DEFAULT 0.00''')

    c.execute('''CREATE TABLE IF NOT EXISTS tasks (
                    id SERIAL PRIMARY KEY, 
                    username TEXT, 
                    email TEXT, 
                    description TEXT, 
                    deadline TIMESTAMP, 
                    reminded_2d INTEGER DEFAULT 0, 
                    reminded_1d INTEGER DEFAULT 0, 
                    reminded_0d INTEGER DEFAULT 0
                )''')

    c.execute('''CREATE TABLE IF NOT EXISTS course_grades (
                    id SERIAL PRIMARY KEY, 
                    username TEXT, 
                    course_code TEXT, 
                    grade TEXT, 
                    credit INTEGER
                )''')

    c.execute('''CREATE TABLE IF NOT EXISTS study_resources (
                    id SERIAL PRIMARY KEY, 
                    uploader TEXT, 
                    uploader_dept TEXT, 
                    title TEXT, 
                    file_name TEXT, 
                    file_url TEXT, 
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )''')

    c.execute('''CREATE TABLE IF NOT EXISTS brain_games (
                    id SERIAL PRIMARY KEY, 
                    title TEXT, 
                    category TEXT, 
                    question TEXT, 
                    correct_answer TEXT, 
                    points INTEGER, 
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )''')

    c.execute('''CREATE TABLE IF NOT EXISTS game_submissions (
                    id SERIAL PRIMARY KEY, 
                    game_id INTEGER, 
                    username TEXT, 
                    is_correct INTEGER, 
                    UNIQUE(game_id, username)
                )''')

    conn.commit()
    conn.close()
    return True

# --- HELPER FUNCTIONS ---
def hash_password(password):
    return hashlib.sha256(str.encode(password)).hexdigest()

def truncate_gpa(value):
    return math.floor(value * 100) / 100.0

def calculate_points(grade, credit):
    grade_map = {'A': 5, 'B': 4, 'C': 3, 'D': 2, 'E': 1, 'F': 0}
    return grade_map.get(grade.upper(), 0) * credit

def get_class_of_degree(cgpa):
    if cgpa >= 4.50:
        return "First Class", "🥇", "success"
    elif cgpa >= 3.50:
        return "Second Class Upper", "🥈", "success"
    elif cgpa >= 2.40:
        return "Second Class Lower", "🥉", "info"
    elif cgpa >= 1.50:
        return "Third Class", "📜", "warning"
    else:
        return "Pass / Probation", "⚠️", "error"

# --- EMAIL LOGIC & REMINDERS ---
def send_uni_email(receiver_email, subject, body):
    if not SENDER_PASSWORD:
        return False
    try:
        msg = MIMEMultipart()
        msg['From'] = f"UniUyo Academic Hub <{SENDER_EMAIL}>"
        msg['To'] = receiver_email
        msg['Subject'] = subject
        msg.attach(MIMEText(body, 'plain'))
        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()
        server.login(SENDER_EMAIL, SENDER_PASSWORD)
        server.sendmail(SENDER_EMAIL, receiver_email, msg.as_string())
        server.quit()
        return True
    except Exception as e:
        print(f"Email notification failed: {e}")
        return False

@st.cache_data(ttl=300)
def check_task_reminders(username):
    conn = get_connection()
    c = conn.cursor()
    c.execute('SELECT id, email, description, deadline, reminded_2d, reminded_1d, reminded_0d FROM tasks WHERE username = %s', (username,))
    tasks = c.fetchall()
    now = datetime.now()
    for task in tasks:
        task_id, email, desc, deadline, r_2d, r_1d, r_0d = task
        time_left = deadline - now
        if timedelta(days=1) < time_left <= timedelta(days=2) and not r_2d:
            send_uni_email(email, "Task Reminder: 2 Days Left!", f"Reminder: '{desc}' is due in 2 days on {deadline}.")
            c.execute('UPDATE tasks SET reminded_2d = 1 WHERE id = %s', (task_id,))
        elif timedelta(hours=0) < time_left <= timedelta(days=1) and not r_1d:
            send_uni_email(email, "Task Reminder: 1 Day Left!", f"Urgent: '{desc}' is due tomorrow at {deadline}.")
            c.execute('UPDATE tasks SET reminded_1d = 1 WHERE id = %s', (task_id,))
        elif time_left <= timedelta(hours=0) and not r_0d:
            send_uni_email(email, "Task Deadline Reached!", f"Alert: The deadline for '{desc}' is right now ({deadline}).")
            c.execute('UPDATE tasks SET reminded_0d = 1 WHERE id = %s', (task_id,))
    conn.commit()
    conn.close()

def get_user_cgpa(username):
    conn = get_connection()
    c = conn.cursor()
    c.execute('SELECT grade, credit FROM course_grades WHERE username = %s', (username,))
    courses = c.fetchall()
    conn.close()
    if not courses: return 0.00
    total_points = sum(calculate_points(g, c) for g, c in courses)
    total_credits = sum(c for g, c in courses)
    if total_credits == 0: return 0.00
    return truncate_gpa(total_points / total_credits)

def save_last_calculated_gpa(username, gpa_val):
    conn = get_connection()
    conn.cursor().execute('UPDATE users SET last_calculated_gpa = %s WHERE username = %s', (gpa_val, username))
    conn.commit()
    conn.close()

def get_last_calculated_gpa(username):
    conn = get_connection()
    c = conn.cursor()
    c.execute('SELECT last_calculated_gpa FROM users WHERE username = %s', (username,))
    row = c.fetchone()
    conn.close()
    return float(row[0]) if row and row[0] is not None else 0.00

# --- MODERN UI STYLING ---
def local_css():
    st.markdown("""
        <meta http-equiv="Cache-Control" content="no-cache, no-store, must-revalidate">
        <meta http-equiv="Pragma" content="no-cache">
        <meta http-equiv="Expires" content="0">
        <style>
        @import url('https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&display=swap');
        
        * { font-family: 'Plus Jakarta Sans', sans-serif; }
        
        /* Dark Gradient Canvas */
        .stApp { 
            background: linear-gradient(135deg, #0b0f19 0%, #111827 50%, #0f172a 100%); 
            color: #f8fafc; 
        }

        /* Top Padding Adjustment */
        .block-container {
            padding-top: 1rem !important;
            padding-bottom: 2rem !important;
        }

        /* Hide Default Sidebar Completely for Clean Mobile View */
        [data-testid="stSidebar"], [data-testid="collapsedControl"] {
            display: none !important;
        }

        /* Modern Custom Nav Card */
        .nav-card {
            background: rgba(30, 41, 59, 0.7) !important;
            backdrop-filter: blur(12px) !important;
            padding: 16px 20px !important;
            border-radius: 16px !important;
            border: 1px solid rgba(99, 102, 241, 0.3) !important;
            margin-bottom: 20px !important;
        }

        /* ENHANCED TAB NAVIGATION SEPARATION */
        .stTabs [data-baseweb="tab-list"] {
            gap: 16px !important;
            background: rgba(15, 23, 42, 0.6) !important;
            padding: 8px !important;
            border-radius: 14px !important;
            border: 1px solid rgba(255, 255, 255, 0.08) !important;
        }

        .stTabs [data-baseweb="tab"] {
            height: 48px !important;
            border-radius: 10px !important;
            padding: 0px 20px !important;
            background-color: rgba(30, 41, 59, 0.5) !important;
            color: #94a3b8 !important;
            font-weight: 700 !important;
            font-size: 0.92rem !important;
            border: 1px solid rgba(255, 255, 255, 0.05) !important;
        }

        .stTabs [aria-selected="true"] {
            background: linear-gradient(90deg, #6366f1 0%, #a855f7 100%) !important;
            color: #ffffff !important;
            border: none !important;
            box-shadow: 0 4px 12px rgba(99, 102, 241, 0.4) !important;
        }

        /* Typography Highlights */
        h1, h2, h3, h4, h5, h6 { 
            color: #ffffff !important; 
            font-weight: 700 !important;
            letter-spacing: -0.02em;
        }
        
        /* Glass Cards */
        .post-box, [data-testid="stForm"], .opp-box {
            background: rgba(30, 41, 59, 0.6) !important;
            backdrop-filter: blur(16px) !important;
            padding: 24px !important;
            border-radius: 16px !important;
            margin-bottom: 20px !important;
            border: 1px solid rgba(255, 255, 255, 0.08) !important;
            box-shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.3) !important;
        }

        /* GRADIENT ACCENT BUTTONS */
        .stButton>button, 
        .stDownloadButton>button,
        [data-testid="stFormSubmitButton"]>button {
            border-radius: 12px !important; 
            background: linear-gradient(90deg, #6366f1 0%, #a855f7 100%) !important; 
            color: #ffffff !important;
            border: none !important; 
            font-weight: 700 !important; 
            padding: 0.65rem 1.2rem !important; 
            box-shadow: 0 4px 14px 0 rgba(99, 102, 241, 0.35) !important;
            transition: all 0.25s ease-in-out !important;
        }

        .stButton>button:hover, 
        .stDownloadButton>button:hover,
        [data-testid="stFormSubmitButton"]>button:hover {
            transform: translateY(-2px) !important;
            box-shadow: 0 6px 20px 0 rgba(168, 85, 247, 0.45) !important;
        }

        /* Inputs */
        .stTextInput>div>div>input, .stSelectbox>div>div>div, .stTextArea>div>div>textarea, .stNumberInput>div>div>input {
            background-color: rgba(15, 23, 42, 0.7) !important; 
            color: #ffffff !important;
            border: 1px solid rgba(255, 255, 255, 0.12) !important; 
            border-radius: 10px !important;
        }

        .tag-badge { 
            background-color: rgba(99, 102, 241, 0.15); 
            color: #818cf8 !important; 
            padding: 4px 12px; 
            border-radius: 20px; 
            font-size: 0.8em; 
            font-weight: 600; 
            border: 1px solid rgba(99, 102, 241, 0.3); 
        }

        #MainMenu { visibility: hidden; }
        footer { visibility: hidden; }
        header { background: transparent !important; }
        </style>
    """, unsafe_allow_html=True)

# --- APP INITIALIZATION ---
try:
    initialize_db_tables()
except Exception as e:
    st.error(f"Database error. Check DB_URL secret. Error: {e}")

local_css()

DEPTS_LIST = [
    "Accounting", "Actuarial Science", "Agriculture", "Agricultural Economics And Extension",
    "Agricultural Engineering", "Agricultural Education", "Agronomy", "Agro Forestry",
    "Animal Science", "Animal and Environmental Biology", "Anatomy", "Architecture",
    "Banking And Finance", "Biochemistry", "Biology", "Botany And Ecological Studies",
    "Brewing Science And Technology", "Building", "Business Administration", "Business Management",
    "Chemical Engineering", "Chemistry", "Civil Engineering", "Communication Arts",
    "Computer Engineering", "Computer Science", "Crop Science", "Dentistry And Dental Surgery",
    "Economics", "Electrical/Electronics Engineering", "English", "Environmental Management",
    "Estate Management", "Fine And Industrial Arts", "Food Engineering", "Food Science And Technology",
    "Geology", "Geophysics", "Guidance and Counseling", "History And International Studies",
    "Human Anatomy", "Law", "Marketing", "Mass Communication", "Mathematics", "Mechanical Engineering",
    "Medical Laboratory Science", "Medicine And Surgery", "Microbiology", "Nursing / Nursing Science",
    "Petroleum Engineering", "Pharmacology And Toxicology", "Pharmacy", "Doctor of Pharmacy",
    "Physics", "Physiology", "Political Science", "Psychology", "Quantity Surveying",
    "Sociology And Anthropology", "Software Engineering", "Statistics", "Theatre Arts", "Zoology"
]

# --- REFRESH SESSION PERSISTENCE LOGIC ---
if 'logged_in' not in st.session_state: 
    st.session_state['logged_in'] = False
if 'user_info' not in st.session_state: 
    st.session_state['user_info'] = None

# Auto-restore session on page refresh if URL contains ?user=...
if not st.session_state['logged_in'] and "user" in st.query_params:
    saved_username = st.query_params["user"]
    conn = get_connection()
    c = conn.cursor()
    c.execute('SELECT * FROM users WHERE username = %s', (saved_username,))
    recovered_user = c.fetchone()
    conn.close()
    if recovered_user:
        st.session_state['logged_in'] = True
        st.session_state['user_info'] = recovered_user

# --- AUTHENTICATION SCREEN ---
if not st.session_state['logged_in']:
    st.markdown("<h1 style='text-align: center; color: #818cf8; font-weight: 800; font-size: 2.2rem; margin-top: 10px;'>🎓 UniUyo Academic Hub</h1>", unsafe_allow_html=True)
    st.markdown("<p style='text-align: center; color: #94a3b8; font-size: 1rem;'>Your personal CGPA engine, study materials, and academic task manager.</p>", unsafe_allow_html=True)
    st.write("---")
    
    auth_mode = st.tabs(["🔐 Login", "📝 Register Account"])

    with auth_mode[0]:
        with st.form("login_form"):
            st.subheader("Welcome Back")
            login_user = st.text_input("Username").strip()
            login_pw = st.text_input("Password", type="password")
            submit_login = st.form_submit_button("Access Dashboard", use_container_width=True)

            if submit_login:
                with st.spinner("Authenticating..."):
                    conn = get_connection()
                    c = conn.cursor()
                    c.execute('SELECT * FROM users WHERE username = %s AND password = %s', (login_user, hash_password(login_pw)))
                    user_data = c.fetchone()
                    if user_data:
                        c.execute('UPDATE users SET usage_count = usage_count + 1 WHERE username = %s', (login_user,))
                        conn.commit()
                        st.session_state['logged_in'] = True
                        st.session_state['user_info'] = user_data
                        # PERSIST USERNAME IN URL FOR REFRESHES
                        st.query_params["user"] = login_user
                        st.success(f"Welcome back, {login_user}!")
                        st.rerun()
                    else:
                        st.error("Invalid Username or Password.")
                    conn.close()

    with auth_mode[1]:
        with st.form("signup_form"):
            st.subheader("Create Account")
            new_user = st.text_input("Choose Username").strip()
            new_email = st.text_input("University Email").strip()
            new_dept = st.selectbox("Select Your Department", DEPTS_LIST)
            new_pw = st.text_input("Create Password", type="password")
            confirm_pw = st.text_input("Confirm Password", type="password")
            submit_signup = st.form_submit_button("Register Account", use_container_width=True)

            if submit_signup:
                if new_pw != confirm_pw:
                    st.warning("Passwords do not match.")
                elif not new_user or not new_email:
                    st.warning("Please fill in all fields.")
                else:
                    with st.spinner("Creating account & setting up your dashboard..."):
                        conn = get_connection()
                        try:
                            c = conn.cursor()
                            c.execute(
                                'INSERT INTO users(username, email, password, department, usage_count) VALUES (%s,%s,%s,%s,%s)',
                                (new_user, new_email, hash_password(new_pw), new_dept, 1))
                            conn.commit()

                            c.execute('SELECT * FROM users WHERE username = %s', (new_user,))
                            created_user_data = c.fetchone()

                            st.session_state['logged_in'] = True
                            st.session_state['user_info'] = created_user_data
                            # PERSIST USERNAME IN URL FOR REFRESHES
                            st.query_params["user"] = new_user

                            send_uni_email(new_email, "Welcome to UniUyo Academic Hub!", f"Hello {new_user},\n\nWelcome to the platform! We are thrilled to support your academic journey.")

                            st.rerun()

                        except IntegrityError:
                            st.error("Username or Email already exists.")
                        finally:
                            conn.close()

# --- MAIN APP (LOGGED IN) ---
else:
    user = st.session_state['user_info']
    username, user_email, user_dept = user[1], user[2], user[4]

    check_task_reminders(username)
    cgpa = get_user_cgpa(username)
    last_gpa = get_last_calculated_gpa(username)

    conn = get_connection()
    c = conn.cursor()
    c.execute('SELECT points FROM users WHERE username = %s', (username,))
    my_points = c.fetchone()[0] or 0
    conn.close()

    # --- MAIN SCREEN NAVIGATION BAR ---
    st.markdown(f"""
        <div class="nav-card">
            <div style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 10px;">
                <div>
                    <h3 style="margin: 0; color: #818cf8; font-size: 1.3rem;">👋 Welcome, {username}</h3>
                    <small style="color: #94a3b8;">📍 {user_dept} | <span class="tag-badge">🌟 {my_points} Brain Pts</span></small>
                </div>
            </div>
        </div>
    """, unsafe_allow_html=True)

    nav_col1, nav_col2 = st.columns([3, 1])
    with nav_col1:
        menu_options = [
            "📊 Dashboard", 
            "📈 GPA/CGPA Tracker", 
            "🧠 Brain Games", 
            "📚 Study Resources", 
            "📅 Task Reminders", 
            "👨‍💻 About Developer"
        ]
        
        # RESTORE PAGE FROM URL IF IT WAS SAVED
        default_idx = 0
        if "page" in st.query_params:
            saved_p = st.query_params["page"]
            for idx, opt in enumerate(menu_options):
                if saved_p in opt:
                    default_idx = idx
                    break

        choice_raw = st.selectbox("📍 Select Navigation Page:", menu_options, index=default_idx, label_visibility="collapsed")
        choice = choice_raw.split(" ", 1)[1] if " " in choice_raw else choice_raw
        
        # SAVE ACTIVE PAGE IN URL QUERY PARAMETER
        st.query_params["page"] = choice

    with nav_col2:
        if st.button("🚪 Log Out", use_container_width=True):
            st.session_state['logged_in'] = False
            st.session_state['user_info'] = None
            # CLEAR URL QUERY PARAMETERS ON LOGOUT
            st.query_params.clear()
            st.rerun()

    st.write("---")

    # --- 1. DASHBOARD ---
    if choice == "Dashboard":
        st.title("📊 Academic Dashboard")
        st.write("Overview of your academic standing, usage metrics, and smart performance insights.")
        
        conn = get_connection()
        c = conn.cursor()

        c.execute("SELECT COUNT(*) FROM tasks WHERE username = %s AND reminded_0d = 0", (username,))
        pending_tasks = c.fetchone()[0]
        c.execute("SELECT usage_count FROM users WHERE username = %s", (username,))
        current_usage = c.fetchone()[0]

        col1, col2, col3, col4 = st.columns(4)
        deg_class, icon, _ = get_class_of_degree(cgpa)
        col1.metric("Overall CGPA", f"{cgpa:.2f}")
        col2.metric("Last Term GPA", f"{last_gpa:.2f}" if last_gpa > 0 else "N/A")
        col3.metric("Active Reminders", pending_tasks)
        col4.metric("Platform Visits", current_usage)
        
        st.info(f"**Current Standing:** {icon} {deg_class}")

        # --- SMART PREDICTOR & ADVISOR ---
        st.write("---")
        st.subheader("🤖 Smart Academic Advisor & Target Predictor")

        # A. LAST SEMESTER GPA ADVICE
        if last_gpa > 0:
            last_class, last_icon, _ = get_class_of_degree(last_gpa)
            st.markdown(f"""
            <div class="post-box" style="border-left: 5px solid #818cf8;">
                <h4 style="color: #818cf8;">⚡ Last Calculated Semester Performance: {last_gpa:.2f} ({last_icon} {last_class})</h4>
                <p style="color: #cbd5e1; margin-bottom: 0;">
                {"🔥 Outstanding semester! Keep up your study habits and maintain this pace." if last_gpa >= 4.50 else
                 "👍 Great semester performance! Focus on turning your B grades into A grades next term." if last_gpa >= 3.50 else
                 "📈 Fair semester result. Concentrate on 3-credit courses and review past questions to boost your GPA next term." if last_gpa >= 2.40 else
                 "⚠️ Semester performance fell below expectations. Utilize study resources and create structured task reminders to recover."}
                </p>
            </div>
            """, unsafe_allow_html=True)

        # B. DYNAMIC TARGET PREDICTOR
        st.markdown("### 🔮 Target CGPA Predictor")
        c.execute('SELECT grade, credit FROM course_grades WHERE username = %s', (username,))
        saved_courses = c.fetchall()

        total_earned_points = sum(calculate_points(g, cr) for g, cr in saved_courses) if saved_courses else 0
        total_passed_credits = sum(cr for _, cr in saved_courses) if saved_courses else 0

        p_col1, p_col2 = st.columns(2)
        with p_col1:
            target_cgpa_goal = st.number_input("Desired Graduation CGPA Goal", min_value=1.50, max_value=5.00, value=4.50, step=0.05)
        with p_col2:
            rem_credits_input = st.text_input("Estimated Remaining Credit Units", placeholder="e.g. 60...").strip()

        if rem_credits_input and rem_credits_input.isdigit() and int(rem_credits_input) > 0:
            rem_credits = int(rem_credits_input)
            total_projected_credits = total_passed_credits + rem_credits
            needed_total_points = target_cgpa_goal * total_projected_credits
            needed_future_points = needed_total_points - total_earned_points
            req_future_gpa = needed_future_points / rem_credits

            if req_future_gpa > 5.00:
                st.error(f"⚠️ **Target Unattainable:** To reach **{target_cgpa_goal:.2f} CGPA**, you would need an average of **{req_future_gpa:.2f} GPA** across remaining credits. Consider setting a revised realistic target (e.g., Second Class Upper).")
            elif req_future_gpa <= 0:
                st.success(f"🎉 **Target Secured!** Your current point ledger already locks in a **{target_cgpa_goal:.2f} CGPA**!")
            else:
                deg_class_target, target_icon, _ = get_class_of_degree(target_cgpa_goal)
                st.success(f"🎯 To graduate with a **{target_cgpa_goal:.2f} CGPA** ({target_icon} {deg_class_target}), you must maintain an average GPA of **{req_future_gpa:.2f}** across your remaining **{rem_credits} credit units**.")

        # C. CGPA STRATEGY ADVISOR
        st.markdown("### 💡 Academic Growth Advisor")
        if cgpa >= 4.50:
            st.markdown("""
            <div class="post-box" style="border-left: 5px solid #22c55e;">
                <h4 style="color: #22c55e;">🥇 Outstanding Momentum (First Class Standing)</h4>
                <ul>
                    <li><b>Prioritize Heavy Credit Courses:</b> Focus your main study hours on 3 & 4 credit courses.</li>
                    <li><b>Active Recall:</b> Practice past question papers from the Resource Vault rather than re-reading slides.</li>
                    <li><b>Consistency:</b> Maintain steady daily study sessions to prevent exam burnout.</li>
                </ul>
            </div>
            """, unsafe_allow_html=True)
        elif cgpa >= 3.50:
            st.markdown("""
            <div class="post-box" style="border-left: 5px solid #6366f1;">
                <h4 style="color: #818cf8;">🥈 Strong Academic Standing (Second Class Upper)</h4>
                <ul>
                    <li><b>Push B's to A's:</b> Target courses where you score 65–69%. Shifting 2 courses per term pushes you into First Class range.</li>
                    <li><b>Continuous Assessment (CA) Buffer:</b> Aim for 25+/30 in CA and lab tests to lighten final exam pressure.</li>
                </ul>
            </div>
            """, unsafe_allow_html=True)
        elif cgpa >= 2.40:
            st.markdown("""
            <div class="post-box" style="border-left: 5px solid #f59e0b;">
                <h4 style="color: #f59e0b;">🥉 Growth Opportunity (Second Class Lower)</h4>
                <ul>
                    <li><b>Eliminate F & E Grades:</b> Aim for a minimum of C grade across all registered subjects.</li>
                    <li><b>Task Reminders:</b> Use Task Reminders to submit assignments early for maximum CA points.</li>
                </ul>
            </div>
            """, unsafe_allow_html=True)
        else:
            st.markdown("""
            <div class="post-box" style="border-left: 5px solid #ef4444;">
                <h4 style="color: #ef4444;">⚠️ Academic Recovery Guidance</h4>
                <ul>
                    <li><b>Consult Course Lecturers:</b> Meet your departmental advisors for direct academic guidance.</li>
                    <li><b>Daily Study Routine:</b> Commit 2 uninterrupted hours daily to foundational topics.</li>
                </ul>
            </div>
            """, unsafe_allow_html=True)

        if username == ADMIN_USERNAME:
            st.write("---")
            st.subheader("👑 Admin Overview")
            c.execute("SELECT COUNT(*) FROM users")
            total_users = c.fetchone()[0]
            c.execute("SELECT SUM(usage_count) FROM users")
            total_app_usages = c.fetchone()[0] or 0
            admin_col1, admin_col2 = st.columns(2)
            admin_col1.metric("Registered Students", total_users)
            admin_col2.metric("Total App Visits", total_app_usages)

        conn.close()

    # --- 2. GPA / CGPA TRACKER ---
    elif choice == "GPA/CGPA Tracker":
        st.title("📊 Result & Performance Engine")
        
        tab1, tab2 = st.tabs([
            "⚡ Semester GPA Calculator", 
            "🎓 Cumulative GPA (CGPA) Calculator"
        ])

        with tab1:
            st.subheader("Semester GPA Calculator")
            st.info("💡 **Quick Calculation:** Enter the number of courses taken this semester to compute your single-semester Grade Point Average (GPA).")
            
            num_courses_input = st.text_input("Enter Number of Courses Taken", placeholder="Type number of courses (e.g., 5)...").strip()
            
            if num_courses_input and num_courses_input.isdigit() and int(num_courses_input) > 0:
                num_courses = int(num_courses_input)
                grades, credits = [], []
                cols = st.columns(2)
                
                for i in range(num_courses):
                    with cols[0]: 
                        grades.append(st.selectbox(f"Course {i + 1} Grade", ['A', 'B', 'C', 'D', 'E', 'F'], key=f"g_{i}"))
                    with cols[1]: 
                        c_unit = st.text_input(f"Course {i + 1} Credit Units", placeholder="e.g., 3", key=f"c_{i}").strip()
                        credits.append(int(c_unit) if c_unit.isdigit() else 0)

                if st.button("Calculate Semester GPA", use_container_width=True):
                    if any(c == 0 for c in credits):
                        st.warning("⚠️ Please fill in valid credit units for all courses above.")
                    else:
                        st.balloons()
                        total_pts = sum(calculate_points(g, c) for g, c in zip(grades, credits))
                        total_cr = sum(credits)
                        res = truncate_gpa(total_pts / total_cr) if total_cr > 0 else 0.00
                        
                        save_last_calculated_gpa(username, res)
                        
                        deg_class, icon, msg_type = get_class_of_degree(res)
                        st.success(f"**Calculated Semester GPA: {res:.2f}** | {icon} {deg_class}")
            elif num_courses_input:
                st.error("Please enter a valid positive number for courses.")
            else:
                st.caption("👈 Type the number of courses taken above to reveal the grade inputs.")

        with tab2:
            st.subheader("Cumulative GPA (CGPA) Ledger")
            st.info("📌 **How to build your official CGPA:** Save all your registered courses from both 1st and 2nd semesters (across 100L, 200L, etc.) below. The system automatically calculates and updates your overall Cumulative GPA (CGPA) in real time.")
            
            with st.form("add_course"):
                st.markdown("##### ➕ Record Course Grade")
                c_code = st.text_input("Course Code (e.g., MTH111, CHM101)")
                c1, c2 = st.columns(2)
                c_grade = c1.selectbox("Grade Obtained", ['A', 'B', 'C', 'D', 'E', 'F'])
                c_credit = c2.number_input("Credit Unit", 1, 6, 3)
                
                if st.form_submit_button("Save Course to CGPA Ledger", use_container_width=True):
                    if c_code.strip():
                        conn = get_connection()
                        conn.cursor().execute(
                            'INSERT INTO course_grades (username, course_code, grade, credit) VALUES (%s,%s,%s,%s)',
                            (username, c_code.strip().upper(), c_grade, c_credit))
                        conn.commit()
                        conn.close()
                        st.success(f"Successfully saved {c_code.upper()} to your academic record!")
                        st.rerun()
                    else:
                        st.error("Please enter a valid Course Code.")

            conn = get_connection()
            c = conn.cursor()
            c.execute('SELECT course_code, grade, credit FROM course_grades WHERE username = %s', (username,))
            saved = c.fetchall()
            conn.close()

            if saved:
                st.write("### 📖 Your Saved Courses Ledger")
                for crs in saved:
                    st.markdown(f"<div style='background: rgba(255,255,255,0.04); padding: 12px; border-radius: 8px; margin-bottom: 6px; border: 1px solid rgba(255,255,255,0.08);'>📖 <b>{crs[0]}</b> | Grade: <b>{crs[1]}</b> | Credit Units: <b>{crs[2]}</b></div>", unsafe_allow_html=True)
                
                deg_class, icon, _ = get_class_of_degree(cgpa)
                st.markdown(f"<div class='opp-box' style='margin-top: 20px;'><h3 style='color: #818cf8; margin: 0;'>Your Overall Cumulative GPA (CGPA): {cgpa:.2f}</h3><p style='color: #f1f5f9; margin-top: 5px; font-size: 1.1em;'>Class of Degree: {icon} {deg_class}</p></div>", unsafe_allow_html=True)
            else:
                st.warning("No courses saved yet. Enter and save your first course above to build your CGPA record.")

    # --- 3. BRAIN GAMES ---
    elif choice == "Brain Games":
        st.title("🧠 Daily Brain Games & Leaderboard")
        st.write("Solve daily challenges to climb the campus leaderboard!")

        tab1, tab2 = st.tabs(["🎮 Active Challenges", "🏆 Leaderboard"])

        with tab1:
            if username == ADMIN_USERNAME:
                with st.expander("🛠️ Admin: Post Challenge"):
                    g_title = st.text_input("Game Title")
                    g_cat = st.selectbox("Category", ["Logic Puzzle", "Coding Challenge", "Math Problem", "Brain Teaser"])
                    g_q = st.text_area("Question Content")
                    g_ans = st.text_input("Exact Answer")
                    g_pts = st.number_input("Points", 10, 500, 50)
                    if st.button("Post Game"):
                        if g_title and g_q and g_ans:
                            conn = get_connection()
                            conn.cursor().execute('INSERT INTO brain_games (title, category, question, correct_answer, points) VALUES (%s,%s,%s,%s,%s)', (g_title, g_cat, g_q, g_ans, g_pts))
                            conn.commit()
                            conn.close()
                            st.success("Challenge posted!")
                            st.rerun()

            conn = get_connection()
            c = conn.cursor()
            c.execute('SELECT id, title, category, question, points, correct_answer, timestamp FROM brain_games ORDER BY timestamp DESC')
            games = c.fetchall()

            if not games:
                st.info("No active challenges right now. Check back soon!")

            for g in games:
                g_id, g_title, g_cat, g_q, g_pts, g_ans, g_ts = g
                c.execute('SELECT COUNT(*) FROM game_submissions WHERE game_id = %s AND is_correct = 1', (g_id,))
                winners_count = c.fetchone()[0]

                c.execute('SELECT is_correct FROM game_submissions WHERE game_id = %s AND username = %s', (g_id, username))
                sub = c.fetchone()

                status_badge = f"<span class='tag-badge'>⭐ {g_pts} Pts ({winners_count}/4 Winners)</span>"
                if winners_count >= 4:
                    status_badge = f"<span class='tag-badge' style='color: #ef4444; border-color: #ef4444;'>⏳ Expired</span>"

                st.markdown(f"<div class='post-box'><h3>{g_title} {status_badge}</h3><p style='font-size: 1.1em;'>{g_q}</p></div>", unsafe_allow_html=True)

                if not sub:
                    with st.expander(f"Submit Answer for {g_title}"):
                        user_ans = st.text_input("Your Answer", key=f"ans_{g_id}")
                        if st.button("Submit Answer", key=f"btn_{g_id}"):
                            is_correct = 1 if user_ans.strip().lower() == g_ans.strip().lower() else 0
                            try:
                                c.execute('INSERT INTO game_submissions (game_id, username, is_correct) VALUES (%s,%s,%s)', (g_id, username, is_correct))
                                if is_correct and winners_count < 4:
                                    c.execute('UPDATE users SET points = points + %s WHERE username = %s', (g_pts, username))
                                    st.balloons()
                                    st.success(f"🎉 Correct answer! You earned {g_pts} points!")
                                elif is_correct:
                                    st.info("✅ Correct answer! However, 4 students have already won for today.")
                                else:
                                    st.error("❌ Incorrect answer.")
                                conn.commit()
                                st.rerun()
                            except IntegrityError:
                                st.toast("Answer already submitted.")
                else:
                    if sub[0] == 1: st.success("✅ Solved successfully!")
                    else: st.error("❌ Attempted (Incorrect)")
                st.write("---")
            conn.close()

        with tab2:
            st.subheader("🏆 Campus Leaderboard")
            conn = get_connection()
            c = conn.cursor()
            c.execute('SELECT username, points FROM users WHERE points > 0 ORDER BY points DESC LIMIT 15')
            leaders = c.fetchall()
            conn.close()

            if not leaders: st.info("No points awarded yet. Be the first to solve a puzzle!")

            for i, (l_user, l_pts) in enumerate(leaders):
                medal = "🥇" if i == 0 else "🥈" if i == 1 else "🥉" if i == 2 else f"#{i + 1}"
                bg = "rgba(99, 102, 241, 0.15)" if l_user == username else "rgba(255, 255, 255, 0.03)"
                st.markdown(f"<div style='background: {bg}; padding: 14px; border-radius: 10px; margin-bottom: 8px; display: flex; justify-content: space-between;'><div><span class='medal-badge'>{medal}</span> <strong>{l_user}</strong></div><div style='font-weight: 800; color: #818cf8;'>{l_pts} pts</div></div>", unsafe_allow_html=True)

    # --- 4. STUDY RESOURCES ---
    elif choice == "Study Resources":
        st.title("📚 Resource Vault")
        st.write("Access departmental past questions, notes, and study guides.")

        with st.expander("📤 Upload Study Material"):
            res_title = st.text_input("Document Title")
            res_file = st.file_uploader("Choose PDF or File")

            if st.button("Upload Material") and res_title and res_file:
                with st.spinner("Uploading to cloud storage..."):
                    try:
                        res = cloudinary.uploader.upload(res_file.read(), resource_type="raw", folder="uniuyo_hub/resources", public_id=res_file.name)
                        file_url = res['secure_url']
                        conn = get_connection()
                        conn.cursor().execute('INSERT INTO study_resources (uploader, uploader_dept, title, file_name, file_url) VALUES (%s,%s,%s,%s,%s)', (username, user_dept, res_title, res_file.name, file_url))
                        conn.commit()
                        conn.close()
                        st.success("Material uploaded successfully!")
                        st.rerun()
                    except Exception:
                        st.error("Upload failed. Verify Cloudinary configurations.")

        st.subheader("📥 Department Materials")
        conn = get_connection()
        c = conn.cursor()
        c.execute('''SELECT id, uploader, title, file_name, file_url, timestamp FROM study_resources WHERE uploader_dept = %s OR uploader_dept = 'General' ORDER BY timestamp DESC''', (user_dept,))

        resources = c.fetchall()
        if not resources:
            st.info("No study materials uploaded for your department yet.")

        for res in resources:
            ts_formatted = res[5].strftime("%Y-%m-%d") if isinstance(res[5], datetime) else res[5]
            st.markdown(f"<div class='post-box'>📄 <strong>{res[2]}</strong><br><small style='color: #94a3b8;'>Uploaded by {res[1]} on {ts_formatted}</small></div>", unsafe_allow_html=True)
            st.link_button("⬇️ Download File", res[4])
            st.write("---")
        conn.close()

    # --- 5. TASK REMINDERS ---
    elif choice == "Task Reminders":
        st.title("📅 Automated Task Reminders")
        st.write("Set assignment or study deadlines. Automated email notifications will be sent to your inbox as the deadline approaches.")

        with st.form("task_form", clear_on_submit=True):
            desc = st.text_input("Task Description (e.g., Submit MTH111 Assignment)")
            c1, c2 = st.columns(2)
            date_val = c1.date_input("Deadline Date")
            time_val = c2.time_input("Deadline Time")
            if st.form_submit_button("Schedule Task Alert", use_container_width=True):
                deadline_dt = datetime.combine(date_val, time_val)
                if deadline_dt <= datetime.now():
                    st.error("Deadline date must be in the future!")
                else:
                    conn = get_connection()
                    conn.cursor().execute('INSERT INTO tasks (username, email, description, deadline) VALUES (%s,%s,%s,%s)', (username, user_email, desc, deadline_dt))
                    conn.commit()
                    conn.close()
                    st.success("Task scheduled! You will receive automated email alerts prior to the deadline.")
                    st.rerun()

        st.subheader("📌 Pending Reminders")
        conn = get_connection()
        c = conn.cursor()
        c.execute('SELECT description, deadline FROM tasks WHERE username = %s AND reminded_0d = 0 ORDER BY deadline ASC', (username,))
        tasks = c.fetchall()
        conn.close()

        if not tasks:
            st.info("No upcoming tasks scheduled.")

        for t in tasks:
            ts_formatted = t[1].strftime("%Y-%m-%d %H:%M") if isinstance(t[1], datetime) else t[1]
            st.info(f"⏳ **{t[0]}** — Due: `{ts_formatted}`")

    # --- 6. ABOUT DEVELOPER ---
    elif choice == "About Developer":
        st.title("👨‍💻 Developer Profile")
        st.markdown(f"""
        <div class="post-box" style="text-align: center;">
            <h2 style="color: #818cf8;">UniUyo Academic Support Hub</h2>
            <p style="font-size: 1.1em; color: #94a3b8;">Engineered by <b>Caleb Offiong James</b></p>
            <p style="color: #f1f5f9;">Department of Computer Engineering | University of Uyo</p>
            <hr style="border-color: rgba(255,255,255,0.08);">
            <p style="color: #94a3b8;">For feedback, bug reports, or feature suggestions, reach out via WhatsApp:</p>
            <h3 style="color: #818cf8;">📞 08075495390</h3>
        </div>
        """, unsafe_allow_html=True)
        st.success("Built for Nigerian students to achieve academic excellence! 💙💛")
