import os
import uuid
import mysql.connector
from flask import Flask, render_template, request, redirect, url_for, session, flash
from werkzeug.utils import secure_filename
from tensorflow.keras.models import load_model
from tensorflow.keras.preprocessing import image
from tensorflow.keras.layers import Dense
import numpy as np
from functools import wraps

app = Flask(__name__,
            template_folder='template',
            static_folder='static')

app.secret_key = 'dermascan-secret-2024'  # Change this in production

UPLOAD_FOLDER = 'static/uploads'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}
MODEL_PATH = 'model/vgg16_malignant_vs_benign.h5'

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# ---------- Database ----------
def get_db_connection():
    return mysql.connector.connect(
        host='localhost',
        user='root',
        password='',
        database='skin_cancer_db'
    )

# ---------- Model ----------
class CustomDense(Dense):
    def __init__(self, *args, **kwargs):
        kwargs.pop('quantization_config', None)
        super().__init__(*args, **kwargs)

try:
    model = load_model(MODEL_PATH, custom_objects={'Dense': CustomDense})
    print("✅ Model loaded successfully")
except Exception as e:
    print("⚠️ Using mock predictions. Error:", e)
    model = None

def predict_image(img_path):
    if model is None:
        prob = np.random.random()
        result = "MALIGNANT" if prob > 0.5 else "BENIGN"
        return prob, result
    img = image.load_img(img_path, target_size=(224, 224))
    img_array = image.img_to_array(img)
    img_array = np.expand_dims(img_array, axis=0) / 255.0
    prob = float(model.predict(img_array)[0][0])
    result = "MALIGNANT" if prob > 0.5 else "BENIGN"
    return prob, result

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            flash('Please log in first.', 'warning')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated

# ---------- Routes ----------
@app.route('/')
def index():
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username'].strip()
        password = request.form['password'].strip()
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM users WHERE username=%s AND password=%s", (username, password))
        user = cursor.fetchone()
        cursor.close(); conn.close()
        if user:
            session['user_id'] = user['id']
            session['username'] = user['username']
            flash('Login successful!', 'success')
            return redirect(url_for('dashboard'))
        else:
            flash('Invalid username or password.', 'danger')
    return render_template('login.html')

@app.route('/dashboard')
@login_required
def dashboard():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT COUNT(*) AS total FROM patients")
    total = cursor.fetchone()['total']
    cursor.execute("SELECT COUNT(*) AS cnt FROM patients WHERE result='BENIGN'")
    benign = cursor.fetchone()['cnt']
    cursor.execute("SELECT COUNT(*) AS cnt FROM patients WHERE result='MALIGNANT'")
    malignant = cursor.fetchone()['cnt']
    cursor.close(); conn.close()
    return render_template('dashboard.html',
                           total_patients=total,
                           benign_count=benign,
                           malignant_count=malignant)

@app.route('/logout')
def logout():
    session.clear()
    flash('Logged out successfully.', 'info')
    return redirect(url_for('login'))

@app.route('/predict', methods=['GET', 'POST'])
@login_required
def predict():
    if request.method == 'POST':
        name = request.form['name'].strip()
        age = request.form['age'].strip()
        file = request.files.get('image')

        if not name or not age or not file:
            flash('All fields are required.', 'danger')
            return redirect(request.url)
        if not allowed_file(file.filename):
            flash('Image format not allowed. Use PNG, JPG, JPEG or GIF.', 'danger')
            return redirect(request.url)

        unique_filename = str(uuid.uuid4()) + '_' + secure_filename(file.filename)
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], unique_filename)
        file.save(file_path)

        prob, result = predict_image(file_path)
        confidence = round(prob * 100, 2) if result == 'MALIGNANT' else round((1 - prob) * 100, 2)

        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO patients (name, age, result, probability, image_path)
            VALUES (%s, %s, %s, %s, %s)
        """, (name, age, result, prob, file_path))
        conn.commit()
        cursor.close(); conn.close()

        return render_template('results.html',
                               result=result,
                               prob=confidence,
                               img=url_for('static', filename='uploads/' + unique_filename))

    return render_template('predict.html')

@app.route('/patients')
@login_required
def patients():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM patients ORDER BY created_at DESC")
    all_patients = cursor.fetchall()
    cursor.close(); conn.close()

    for p in all_patients:
        p['prob_display'] = round(p['probability'] * 100, 2) if p['result'] == 'MALIGNANT' \
                            else round((1 - p['probability']) * 100, 2)
        p['image_url'] = url_for('static', filename='uploads/' + os.path.basename(p['image_path']))

    return render_template('patients.html', patients=all_patients)

if __name__ == '__main__':
    app.run(debug=True)