from flask import Flask, render_template, request, redirect, url_for, session, jsonify, flash
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timedelta
import qrcode
import qrcode.image.svg
import io
import base64
import uuid
import os
from functools import wraps

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'resiconnect-secret-key-2024')
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///resiconnect.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

# ──────────────────────────────
# MODELS
# ──────────────────────────────

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)
    role = db.Column(db.String(20), nullable=False)  # admin, member, security
    flat_number = db.Column(db.String(20))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    is_active = db.Column(db.Boolean, default=True)

class GuestPass(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    token = db.Column(db.String(64), unique=True, nullable=False)
    member_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    guest_name = db.Column(db.String(100), nullable=False)
    guest_phone = db.Column(db.String(20))
    purpose = db.Column(db.String(200))
    valid_from = db.Column(db.DateTime, nullable=False)
    valid_until = db.Column(db.DateTime, nullable=False)
    status = db.Column(db.String(20), default='pending')  # pending, approved, denied, expired
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    scanned_at = db.Column(db.DateTime)
    scanned_by = db.Column(db.Integer, db.ForeignKey('user.id'))
    member = db.relationship('User', foreign_keys=[member_id], backref='guest_passes')
    security = db.relationship('User', foreign_keys=[scanned_by])

class ActivityLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    action = db.Column(db.String(200), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    guest_pass_id = db.Column(db.Integer, db.ForeignKey('guest_pass.id'))
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    details = db.Column(db.String(500))

class Notice(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    body = db.Column(db.Text, nullable=False)
    urgency = db.Column(db.String(20), default='normal')  # low, normal, high, urgent
    audience = db.Column(db.String(20), default='all')    # all, member, security
    created_by = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    is_active = db.Column(db.Boolean, default=True)
    author = db.relationship('User', foreign_keys=[created_by])

class WalkInRequest(db.Model):
    """Unregistered walk-in guest — security captures photo, notifies member."""
    id = db.Column(db.Integer, primary_key=True)
    token = db.Column(db.String(64), unique=True, nullable=False)
    member_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    security_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    guest_name = db.Column(db.String(100), nullable=False)
    guest_phone = db.Column(db.String(20))
    purpose = db.Column(db.String(200))
    photo_data = db.Column(db.Text)          # base64 JPEG
    status = db.Column(db.String(20), default='pending')  # pending, approved, denied, expired
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    responded_at = db.Column(db.DateTime)
    member = db.relationship('User', foreign_keys=[member_id])
    security_staff = db.relationship('User', foreign_keys=[security_id])

class DailyWorker(db.Model):
    """A recurring daily worker registered by a member (maid, cook, driver, etc.)"""
    id = db.Column(db.Integer, primary_key=True)
    member_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    phone = db.Column(db.String(20))
    work_type = db.Column(db.String(50), nullable=False)
    photo_data = db.Column(db.Text)
    allowed_days = db.Column(db.String(20), default='1234567')  # 1=Mon to 7=Sun
    entry_start = db.Column(db.String(5), default='06:00')
    entry_end = db.Column(db.String(5), default='20:00')
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    member = db.relationship('User', foreign_keys=[member_id], backref='daily_workers')
    entries = db.relationship('DailyWorkerEntry', backref='worker', lazy='dynamic')

class DailyWorkerEntry(db.Model):
    """Log of each time a daily worker entered the society."""
    id = db.Column(db.Integer, primary_key=True)
    worker_id = db.Column(db.Integer, db.ForeignKey('daily_worker.id'), nullable=False)
    security_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    entry_date = db.Column(db.Date, nullable=False)
    entry_time = db.Column(db.DateTime, default=datetime.utcnow)
    status = db.Column(db.String(20), default='entered')  # entered, denied
    security_user = db.relationship('User', foreign_keys=[security_id])


  
# ──────────────────────────────
# HELPERS
# ──────────────────────────────

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated

def role_required(*roles):
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            if 'user_id' not in session:
                return redirect(url_for('login'))
            user = User.query.get(session['user_id'])
            if user.role not in roles:
                flash('Access denied.', 'error')
                return redirect(url_for('dashboard'))
            return f(*args, **kwargs)
        return decorated
    return decorator

def generate_qr_base64(data):
    qr = qrcode.QRCode(version=1, box_size=8, border=3,
                       error_correction=qrcode.constants.ERROR_CORRECT_H)
    qr.add_data(data)
    qr.make(fit=True)
    img = qr.make_image(fill_color="#0f172a", back_color="white")
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    return base64.b64encode(buf.getvalue()).decode('utf-8')

def log_activity(action, user_id=None, guest_pass_id=None, details=None):
    log = ActivityLog(action=action, user_id=user_id,
                      guest_pass_id=guest_pass_id, details=details)
    db.session.add(log)
    db.session.commit()

# ──────────────────────────────
# AUTH ROUTES
# ──────────────────────────────

@app.route('/')
def index():
    if 'user_id' in session:
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email', '').strip()
        password = request.form.get('password', '')
        user = User.query.filter_by(email=email, is_active=True).first()
        if user and check_password_hash(user.password, password):
            session['user_id'] = user.id
            session['user_role'] = user.role
            session['user_name'] = user.name
            log_activity('LOGIN', user_id=user.id, details=f'{user.role} logged in')
            return redirect(url_for('dashboard'))
        flash('Invalid email or password.', 'error')
    return render_template('login.html')

@app.route('/logout')
def logout():
    log_activity('LOGOUT', user_id=session.get('user_id'))
    session.clear()
    return redirect(url_for('login'))

# ──────────────────────────────
# DASHBOARD
# ──────────────────────────────

@app.route('/dashboard')
@login_required
def dashboard():
    user = User.query.get(session['user_id'])
    if user.role == 'admin':
        return redirect(url_for('admin_dashboard'))
    elif user.role == 'member':
        return redirect(url_for('member_dashboard'))
    elif user.role == 'security':
        return redirect(url_for('security_dashboard'))
    return redirect(url_for('login'))

# ──────────────────────────────
# ADMIN ROUTES
# ──────────────────────────────

@app.route('/admin')
@role_required('admin')
def admin_dashboard():
    total_members = User.query.filter_by(role='member', is_active=True).count()
    total_security = User.query.filter_by(role='security', is_active=True).count()
    today = datetime.utcnow().date()
    today_passes = GuestPass.query.filter(
        db.func.date(GuestPass.created_at) == today).count()
    approved_today = GuestPass.query.filter(
        db.func.date(GuestPass.scanned_at) == today,
        GuestPass.status == 'approved').count()
    recent_logs = ActivityLog.query.order_by(
        ActivityLog.timestamp.desc()).limit(10).all()
    members = User.query.filter_by(role='member').order_by(User.name).all()
    security_staff = User.query.filter_by(role='security').order_by(User.name).all()
    return render_template('admin_dashboard.html',
        user=User.query.get(session['user_id']),
        total_members=total_members, total_security=total_security,
        today_passes=today_passes, approved_today=approved_today,
        recent_logs=recent_logs, members=members, security_staff=security_staff)

@app.route('/admin/add-user', methods=['POST'])
@role_required('admin')
def add_user():
    name = request.form.get('name', '').strip()
    email = request.form.get('email', '').strip()
    password = request.form.get('password', '')
    role = request.form.get('role', '')
    flat_number = request.form.get('flat_number', '').strip()
    if User.query.filter_by(email=email).first():
        flash('Email already registered.', 'error')
        return redirect(url_for('admin_dashboard'))
    user = User(name=name, email=email,
                password=generate_password_hash(password),
                role=role, flat_number=flat_number)
    db.session.add(user)
    db.session.commit()
    log_activity('ADD_USER', user_id=session['user_id'],
                 details=f'Added {role}: {name}')
    flash(f'{role.capitalize()} "{name}" added successfully.', 'success')
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/toggle-user/<int:uid>', methods=['POST'])
@role_required('admin')
def toggle_user(uid):
    user = User.query.get_or_404(uid)
    user.is_active = not user.is_active
    db.session.commit()
    status = 'activated' if user.is_active else 'deactivated'
    flash(f'User {user.name} {status}.', 'success')
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/all-passes')
@role_required('admin')
def admin_all_passes():
    passes = GuestPass.query.order_by(GuestPass.created_at.desc()).all()
    return render_template('admin_passes.html',
        user=User.query.get(session['user_id']), passes=passes)

# ──────────────────────────────
# MEMBER ROUTES
# ──────────────────────────────

@app.route('/member')
@role_required('member')
def member_dashboard():
    user = User.query.get(session['user_id'])
    passes = GuestPass.query.filter_by(member_id=user.id).order_by(
        GuestPass.created_at.desc()).limit(20).all()
    active_passes = GuestPass.query.filter_by(
        member_id=user.id, status='pending').filter(
        GuestPass.valid_until >= datetime.utcnow()).count()
    return render_template('member_dashboard.html',
        user=user, passes=passes, active_passes=active_passes)

@app.route('/member/create-pass', methods=['POST'])
@role_required('member')
def create_pass():
    guest_name = request.form.get('guest_name', '').strip()
    guest_phone = request.form.get('guest_phone', '').strip()
    purpose = request.form.get('purpose', '').strip()
    valid_hours = int(request.form.get('valid_hours', 24))
    valid_from = datetime.utcnow()
    valid_until = valid_from + timedelta(hours=valid_hours)
    token = str(uuid.uuid4()).replace('-', '')
    gp = GuestPass(token=token, member_id=session['user_id'],
                   guest_name=guest_name, guest_phone=guest_phone,
                   purpose=purpose, valid_from=valid_from,
                   valid_until=valid_until)
    db.session.add(gp)
    db.session.commit()
    log_activity('CREATE_PASS', user_id=session['user_id'],
                 guest_pass_id=gp.id, details=f'Pass for {guest_name}')
    flash(f'Guest pass created for {guest_name}.', 'success')
    return redirect(url_for('view_pass', token=token))

@app.route('/pass/<token>')
@login_required
def view_pass(token):
    gp = GuestPass.query.filter_by(token=token).first_or_404()
    # Update expired passes
    if gp.status == 'pending' and gp.valid_until < datetime.utcnow():
        gp.status = 'expired'
        db.session.commit()
    scan_url = request.host_url + 'security/scan/' + token
    qr_image = generate_qr_base64(scan_url)
    user = User.query.get(session['user_id'])
    return render_template('view_pass.html', gp=gp, qr_image=qr_image,
                           scan_url=scan_url, user=user)

@app.route('/member/revoke-pass/<int:pass_id>', methods=['POST'])
@role_required('member')
def revoke_pass(pass_id):
    gp = GuestPass.query.get_or_404(pass_id)
    if gp.member_id != session['user_id']:
        flash('Unauthorized.', 'error')
        return redirect(url_for('member_dashboard'))
    gp.status = 'expired'
    db.session.commit()
    flash('Guest pass revoked.', 'success')
    return redirect(url_for('member_dashboard'))

# ──────────────────────────────
# SECURITY ROUTES
# ──────────────────────────────

@app.route('/security')
@role_required('security')
def security_dashboard():
    user = User.query.get(session['user_id'])
    today = datetime.utcnow().date()
    today_scans = GuestPass.query.filter(
        GuestPass.scanned_by == user.id,
        db.func.date(GuestPass.scanned_at) == today).all()
    approved = sum(1 for p in today_scans if p.status == 'approved')
    denied = sum(1 for p in today_scans if p.status == 'denied')
    recent = GuestPass.query.filter_by(scanned_by=user.id).order_by(
        GuestPass.scanned_at.desc()).limit(15).all()
    # Walk-in requests submitted by this security officer (all time, latest 15)
    recent_walkins = WalkInRequest.query.filter_by(
        security_id=user.id).order_by(
        WalkInRequest.created_at.desc()).limit(15).all()
    # Today's walk-in counts
    today_walkins = WalkInRequest.query.filter(
        WalkInRequest.security_id == user.id,
        db.func.date(WalkInRequest.created_at) == today).all()
    walkin_approved = sum(1 for w in today_walkins if w.status == 'approved')
    walkin_denied = sum(1 for w in today_walkins if w.status == 'denied')
    walkin_pending = sum(1 for w in today_walkins if w.status == 'pending')
    return render_template('security_dashboard.html',
        user=user, today_scans=len(today_scans),
        approved=approved + walkin_approved,
        denied=denied + walkin_denied,
        recent=recent,
        recent_walkins=recent_walkins,
        walkin_pending=walkin_pending)

@app.route('/api/security/walkin-feed')
@role_required('security')
def security_walkin_feed():
    """Live feed of walk-in requests for this security officer."""
    user = User.query.get(session['user_id'])
    walkins = WalkInRequest.query.filter_by(
        security_id=user.id).order_by(
        WalkInRequest.created_at.desc()).limit(15).all()
    result = []
    for w in walkins:
        result.append({
            'id': w.id,
            'guest_name': w.guest_name,
            'guest_phone': w.guest_phone or '',
            'purpose': w.purpose or '',
            'member_name': w.member.name,
            'flat_number': w.member.flat_number or '—',
            'status': w.status,
            'created_at': w.created_at.strftime('%I:%M %p'),
            'responded_at': w.responded_at.strftime('%I:%M %p') if w.responded_at else None,
        })
    return jsonify({'ok': True, 'walkins': result})

@app.route('/security/scan/<token>')
@role_required('security')
def security_scan(token):
    gp = GuestPass.query.filter_by(token=token).first()
    user = User.query.get(session['user_id'])
    if not gp:
        return render_template('scan_result.html', user=user,
            result='invalid', message='Invalid QR code. No pass found.')
    # Check expiry
    if gp.valid_until < datetime.utcnow():
        if gp.status == 'pending':
            gp.status = 'expired'
            db.session.commit()
        return render_template('scan_result.html', user=user,
            result='expired', gp=gp,
            message='This pass has expired.')
    if gp.status == 'approved':
        return render_template('scan_result.html', user=user,
            result='already_used', gp=gp,
            message='This pass has already been used.')
    if gp.status in ('denied', 'expired'):
        return render_template('scan_result.html', user=user,
            result=gp.status, gp=gp,
            message=f'This pass is {gp.status}.')
    return render_template('scan_result.html', user=user,
        result='valid', gp=gp, message='Valid pass. Approve or deny entry.')

@app.route('/security/action/<token>/<action>', methods=['POST'])
@role_required('security')
def security_action(token, action):
    gp = GuestPass.query.filter_by(token=token).first_or_404()
    if action == 'approve':
        gp.status = 'approved'
        gp.scanned_at = datetime.utcnow()
        gp.scanned_by = session['user_id']
        db.session.commit()
        log_activity('APPROVE_ENTRY', user_id=session['user_id'],
                     guest_pass_id=gp.id, details=f'Approved {gp.guest_name}')
        flash(f'Entry approved for {gp.guest_name}.', 'success')
    elif action == 'deny':
        gp.status = 'denied'
        gp.scanned_at = datetime.utcnow()
        gp.scanned_by = session['user_id']
        db.session.commit()
        log_activity('DENY_ENTRY', user_id=session['user_id'],
                     guest_pass_id=gp.id, details=f'Denied {gp.guest_name}')
        flash(f'Entry denied for {gp.guest_name}.', 'error')
    return redirect(url_for('security_dashboard'))

# ──────────────────────────────
# API ENDPOINTS (for live scan)
# ──────────────────────────────

@app.route('/api/scan/<token>')
@login_required
def api_scan(token):
    gp = GuestPass.query.filter_by(token=token).first()
    if not gp:
        return jsonify({'status': 'invalid', 'message': 'Pass not found'})
    if gp.valid_until < datetime.utcnow():
        return jsonify({'status': 'expired', 'message': 'Pass expired'})
    if gp.status != 'pending':
        return jsonify({'status': gp.status, 'message': f'Pass is {gp.status}'})
    member = User.query.get(gp.member_id)
    return jsonify({
        'status': 'valid',
        'guest_name': gp.guest_name,
        'guest_phone': gp.guest_phone,
        'purpose': gp.purpose,
        'member_name': member.name,
        'flat_number': member.flat_number,
        'valid_until': gp.valid_until.strftime('%d %b %Y, %I:%M %p'),
        'token': token
    })

# ──────────────────────────────
# NOTICE BOARD ROUTES
# ──────────────────────────────

@app.route('/notices')
@login_required
def notice_board():
    user = User.query.get(session['user_id'])
    role = user.role
    # Fetch notices relevant to this user's role
    if role == 'admin':
        notices = Notice.query.filter_by(is_active=True).order_by(
            Notice.created_at.desc()).all()
    elif role == 'member':
        notices = Notice.query.filter(
            Notice.is_active == True,
            Notice.audience.in_(['all', 'member'])
        ).order_by(Notice.created_at.desc()).all()
    elif role == 'security':
        notices = Notice.query.filter(
            Notice.is_active == True,
            Notice.audience.in_(['all', 'security'])
        ).order_by(Notice.created_at.desc()).all()
    else:
        notices = []
    return render_template('notice_board.html', user=user, notices=notices)

@app.route('/admin/notices/add', methods=['POST'])
@role_required('admin')
def add_notice():
    title = request.form.get('title', '').strip()
    body = request.form.get('body', '').strip()
    urgency = request.form.get('urgency', 'normal')
    audience = request.form.get('audience', 'all')
    if not title or not body:
        flash('Title and body are required.', 'error')
        return redirect(url_for('notice_board'))
    notice = Notice(title=title, body=body, urgency=urgency,
                    audience=audience, created_by=session['user_id'])
    db.session.add(notice)
    db.session.commit()
    log_activity('ADD_NOTICE', user_id=session['user_id'],
                 details=f'Posted notice: {title}')
    flash(f'Notice "{title}" posted successfully.', 'success')
    return redirect(url_for('notice_board'))

@app.route('/admin/notices/edit/<int:nid>', methods=['POST'])
@role_required('admin')
def edit_notice(nid):
    notice = Notice.query.get_or_404(nid)
    notice.title = request.form.get('title', '').strip()
    notice.body = request.form.get('body', '').strip()
    notice.urgency = request.form.get('urgency', 'normal')
    notice.audience = request.form.get('audience', 'all')
    notice.updated_at = datetime.utcnow()
    db.session.commit()
    log_activity('EDIT_NOTICE', user_id=session['user_id'],
                 details=f'Edited notice: {notice.title}')
    flash('Notice updated successfully.', 'success')
    return redirect(url_for('notice_board'))

@app.route('/admin/notices/delete/<int:nid>', methods=['POST'])
@role_required('admin')
def delete_notice(nid):
    notice = Notice.query.get_or_404(nid)
    notice.is_active = False
    db.session.commit()
    log_activity('DELETE_NOTICE', user_id=session['user_id'],
                 details=f'Removed notice: {notice.title}')
    flash('Notice removed.', 'success')
    return redirect(url_for('notice_board'))

# ──────────────────────────────
# WALK-IN GUEST ROUTES
# ──────────────────────────────

@app.route('/security/walkin', methods=['POST'])
@role_required('security')
def create_walkin():
    """Security creates a walk-in request with photo → notifies member."""
    data = request.get_json()
    member_id = data.get('member_id')
    guest_name = data.get('guest_name', '').strip()
    guest_phone = data.get('guest_phone', '').strip()
    purpose = data.get('purpose', '').strip()
    photo_data = data.get('photo_data', '')   # base64 JPEG from webcam

    if not member_id or not guest_name:
        return jsonify({'ok': False, 'error': 'Member and guest name required'}), 400

    member = User.query.get(member_id)
    if not member or member.role != 'member':
        return jsonify({'ok': False, 'error': 'Invalid member'}), 400

    token = str(uuid.uuid4()).replace('-', '')
    req = WalkInRequest(
        token=token,
        member_id=member_id,
        security_id=session['user_id'],
        guest_name=guest_name,
        guest_phone=guest_phone,
        purpose=purpose,
        photo_data=photo_data,
        status='pending'
    )
    db.session.add(req)
    db.session.commit()
    log_activity('WALKIN_REQUEST', user_id=session['user_id'],
                 details=f'Walk-in request for {guest_name} → {member.name} (Flat {member.flat_number})')
    return jsonify({'ok': True, 'token': token, 'request_id': req.id})

@app.route('/api/walkin/status/<token>')
@role_required('security')
def walkin_status(token):
    """Security polls this to see if member has responded."""
    req = WalkInRequest.query.filter_by(token=token).first()
    if not req:
        return jsonify({'ok': False, 'error': 'Not found'}), 404
    # Auto-expire after 5 minutes with no response
    if req.status == 'pending':
        age = (datetime.utcnow() - req.created_at).total_seconds()
        if age > 300:
            req.status = 'expired'
            db.session.commit()
    return jsonify({'ok': True, 'status': req.status,
                    'guest_name': req.guest_name,
                    'member_name': req.member.name,
                    'flat_number': req.member.flat_number or '—'})

@app.route('/api/walkin/pending')
@role_required('member')
def walkin_pending():
    """Member polls for pending walk-in requests directed at them."""
    user = User.query.get(session['user_id'])
    reqs = WalkInRequest.query.filter_by(
        member_id=user.id, status='pending'
    ).order_by(WalkInRequest.created_at.desc()).all()
    result = []
    for r in reqs:
        # auto-expire stale ones (> 5 min)
        age = (datetime.utcnow() - r.created_at).total_seconds()
        if age > 300:
            r.status = 'expired'
            db.session.commit()
            continue
        result.append({
            'id': r.id,
            'token': r.token,
            'guest_name': r.guest_name,
            'guest_phone': r.guest_phone or '',
            'purpose': r.purpose or '',
            'photo_data': r.photo_data or '',
            'created_at': r.created_at.strftime('%I:%M %p'),
            'expires_in': max(0, int(300 - age))
        })
    return jsonify({'ok': True, 'requests': result})

@app.route('/api/walkin/respond/<int:req_id>/<action>', methods=['POST'])
@role_required('member')
def walkin_respond(req_id, action):
    """Member approves or denies a walk-in request."""
    req = WalkInRequest.query.get_or_404(req_id)
    if req.member_id != session['user_id']:
        return jsonify({'ok': False, 'error': 'Unauthorized'}), 403
    if req.status != 'pending':
        return jsonify({'ok': False, 'error': 'Request already resolved'}), 400
    if action not in ('approve', 'deny'):
        return jsonify({'ok': False, 'error': 'Invalid action'}), 400

    req.status = 'approved' if action == 'approve' else 'denied'
    req.responded_at = datetime.utcnow()
    db.session.commit()
    log_activity(
        'WALKIN_APPROVED' if action == 'approve' else 'WALKIN_DENIED',
        user_id=session['user_id'],
        details=f'{req.guest_name} {"approved" if action == "approve" else "denied"} by {req.member.name}'
    )
    return jsonify({'ok': True, 'status': req.status})

@app.route('/api/members')
@role_required('security')
def api_members():
    """Return list of active members for walk-in dropdown."""
    members = User.query.filter_by(role='member', is_active=True).order_by(User.name).all()
    return jsonify([{
        'id': m.id,
        'name': m.name,
        'flat_number': m.flat_number or '—'
    } for m in members])


# ──────────────────────────────
# DAILY WORKER ROUTES
# ──────────────────────────────

DAY_NAMES = {1:'Mon',2:'Tue',3:'Wed',4:'Thu',5:'Fri',6:'Sat',7:'Sun'}

def worker_allowed_today(worker):
    """Check if worker is allowed today and within time window."""
    now = datetime.utcnow()
    today_dow = now.isoweekday()  # 1=Mon, 7=Sun
    if str(today_dow) not in worker.allowed_days:
        return False, 'Not scheduled today'
    # Time check
    try:
        sh, sm = map(int, worker.entry_start.split(':'))
        eh, em = map(int, worker.entry_end.split(':'))
        start = now.replace(hour=sh, minute=sm, second=0)
        end   = now.replace(hour=eh, minute=em, second=0)
        if not (start <= now <= end):
            return False, f'Outside allowed hours ({worker.entry_start}–{worker.entry_end})'
    except Exception:
        pass
    return True, 'OK'

# Member: list their daily workers
@app.route('/member/workers')
@role_required('member')
def member_workers():
    user = User.query.get(session['user_id'])
    workers = DailyWorker.query.filter_by(member_id=user.id).order_by(DailyWorker.name).all()
    return render_template('member_workers.html', user=user, workers=workers, day_names=DAY_NAMES)

# Member: add daily worker
@app.route('/member/workers/add', methods=['POST'])
@role_required('member')
def add_daily_worker():
    name       = request.form.get('name', '').strip()
    phone      = request.form.get('phone', '').strip()
    work_type  = request.form.get('work_type', '').strip()
    photo_data = request.form.get('photo_data', '').strip()
    allowed_days = ''.join(request.form.getlist('allowed_days'))
    entry_start  = request.form.get('entry_start', '06:00')
    entry_end    = request.form.get('entry_end', '20:00')
    if not name or not work_type:
        flash('Name and work type are required.', 'error')
        return redirect(url_for('member_workers'))
    worker = DailyWorker(
        member_id=session['user_id'],
        name=name, phone=phone, work_type=work_type,
        photo_data=photo_data if photo_data else None,
        allowed_days=allowed_days or '1234567',
        entry_start=entry_start, entry_end=entry_end
    )
    db.session.add(worker)
    db.session.commit()
    log_activity('ADD_DAILY_WORKER', user_id=session['user_id'],
                 details=f'Added daily worker: {name} ({work_type})')
    flash(f'Daily worker "{name}" registered.', 'success')
    return redirect(url_for('member_workers'))

# Member: toggle active/inactive
@app.route('/member/workers/toggle/<int:wid>', methods=['POST'])
@role_required('member')
def toggle_daily_worker(wid):
    worker = DailyWorker.query.get_or_404(wid)
    if worker.member_id != session['user_id']:
        flash('Unauthorized.', 'error')
        return redirect(url_for('member_workers'))
    worker.is_active = not worker.is_active
    db.session.commit()
    flash(f'Worker {"activated" if worker.is_active else "deactivated"}.', 'success')
    return redirect(url_for('member_workers'))

# Member: delete worker
@app.route('/member/workers/delete/<int:wid>', methods=['POST'])
@role_required('member')
def delete_daily_worker(wid):
    worker = DailyWorker.query.get_or_404(wid)
    if worker.member_id != session['user_id']:
        flash('Unauthorized.', 'error')
        return redirect(url_for('member_workers'))
    db.session.delete(worker)
    db.session.commit()
    flash('Worker removed.', 'success')
    return redirect(url_for('member_workers'))

# Security: list today's expected daily workers
@app.route('/security/workers')
@role_required('security')
def security_workers():
    user = User.query.get(session['user_id'])
    today = datetime.utcnow().date()
    today_dow = str(datetime.utcnow().isoweekday())
    # All active workers scheduled for today
    all_workers = DailyWorker.query.filter_by(is_active=True).all()
    todays_workers = [w for w in all_workers if today_dow in w.allowed_days]
    # Check which ones have already entered today
    entered_ids = {e.worker_id for e in DailyWorkerEntry.query.filter_by(entry_date=today).all()}
    return render_template('security_workers.html',
        user=user, workers=todays_workers,
        entered_ids=entered_ids, day_names=DAY_NAMES, today=today)

# Security: mark worker entry
@app.route('/security/workers/entry/<int:wid>/<action>', methods=['POST'])
@role_required('security')
def worker_entry(wid, action):
    worker = DailyWorker.query.get_or_404(wid)
    today = datetime.utcnow().date()
    # Prevent duplicate entry log for today
    existing = DailyWorkerEntry.query.filter_by(worker_id=wid, entry_date=today).first()
    if existing:
        flash(f'{worker.name} already logged today.', 'error')
        return redirect(url_for('security_workers'))
    allowed, reason = worker_allowed_today(worker)
    status = 'entered' if action == 'enter' else 'denied'
    entry = DailyWorkerEntry(
        worker_id=wid,
        security_id=session['user_id'],
        entry_date=today,
        status=status
    )
    db.session.add(entry)
    db.session.commit()
    log_activity(
        'WORKER_ENTRY' if status == 'entered' else 'WORKER_DENIED',
        user_id=session['user_id'],
        details=f'{worker.name} ({worker.work_type}) — Flat {worker.member.flat_number}'
    )
    flash(f'{"Entry logged" if status == "entered" else "Entry denied"} for {worker.name}.', 'success')
    return redirect(url_for('security_workers'))

# API: today's worker list for live refresh
@app.route('/api/security/workers-today')
@role_required('security')
def api_workers_today():
    today = datetime.utcnow().date()
    today_dow = str(datetime.utcnow().isoweekday())
    all_workers = DailyWorker.query.filter_by(is_active=True).all()
    todays = [w for w in all_workers if today_dow in w.allowed_days]
    entered_ids = {e.worker_id for e in DailyWorkerEntry.query.filter_by(entry_date=today).all()}
    result = []
    for w in todays:
        allowed, reason = worker_allowed_today(w)
        entry = DailyWorkerEntry.query.filter_by(worker_id=w.id, entry_date=today).first()
        result.append({
            'id': w.id,
            'name': w.name,
            'phone': w.phone or '',
            'work_type': w.work_type,
            'photo_data': w.photo_data or '',
            'flat': w.member.flat_number or '—',
            'member_name': w.member.name,
            'entry_start': w.entry_start,
            'entry_end': w.entry_end,
            'entered': w.id in entered_ids,
            'entry_status': entry.status if entry else None,
            'entry_time': entry.entry_time.strftime('%I:%M %p') if entry else None,
            'allowed_now': allowed,
            'reason': reason,
        })
    return jsonify({'ok': True, 'workers': result})

# Admin: view all daily workers
@app.route('/admin/workers')
@role_required('admin')
def admin_workers():
    workers = DailyWorker.query.order_by(DailyWorker.name).all()
    today = datetime.utcnow().date()
    entered_today = {e.worker_id for e in DailyWorkerEntry.query.filter_by(entry_date=today).all()}
    return render_template('admin_workers.html',
        user=User.query.get(session['user_id']),
        workers=workers, entered_today=entered_today, day_names=DAY_NAMES)

# ──────────────────────────────
# INIT DB + SEED
# ──────────────────────────────

def init_db():
    with app.app_context():
        db.create_all()
        if not User.query.filter_by(email='admin@resiconnect.com').first():
            admin = User(name='Admin', email='admin@resiconnect.com',
                         password=generate_password_hash('admin123'),
                         role='admin')
            member = User(name='Rajesh Sharma', email='member@resiconnect.com',
                          password=generate_password_hash('member123'),
                          role='member', flat_number='A-101')
            security = User(name='Ramesh Guard', email='security@resiconnect.com',
                            password=generate_password_hash('security123'),
                            role='security')
            db.session.add_all([admin, member, security])
            db.session.commit()
            print("✅ Database initialized with demo accounts.")

@app.route('/api/latest-notice')
@login_required
def latest_notice():
    user = User.query.get(session['user_id'])

    # filter based on audience
    query = Notice.query.filter_by(is_active=True)

    if user.role == 'member':
        query = query.filter(Notice.audience.in_(['all', 'member']))
    elif user.role == 'security':
        query = query.filter(Notice.audience.in_(['all', 'security']))

    notice = query.order_by(Notice.created_at.desc()).first()

    if not notice:
        return jsonify({'id': None})

    return jsonify({
        'id': notice.id,
        'title': notice.title,
        'body': notice.body,
        'urgency': notice.urgency
    })

if __name__ == '__main__':
    init_db()
    app.run(host="0.0.0.0", port=5000, debug=True)    
