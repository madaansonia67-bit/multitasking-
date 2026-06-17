import os
import random
import datetime
from flask import Flask, send_from_directory
from flask_login import LoginManager
from flask_socketio import SocketIO, emit, join_room
from models import db, User, Asset, CurrencyRates, Message
from routes import main_bp

app = Flask(__name__)
app.config['SECRET_KEY'] = 'SUPER_SECRET_SIMULATION_KEY_12345'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///simulation_platform.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db.init_app(app)
socketio = SocketIO(
    app,
    cors_allowed_origins="*",
    async_mode="threading"
)

login_manager = LoginManager()
login_manager.login_view = 'main.index'
login_manager.init_app(app)

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

app.register_blueprint(main_bp)

@app.route('/uploads/<filename>')
def uploaded_file(filename):
    return send_from_directory('uploads', filename)

# Simulated Price Mechanics Task Ticks run natively inside background sockets loop
def background_market_ticks():
    while True:
        socketio.sleep(0.5)
        with app.app_context():
            assets = Asset.query.all()
            trends = ['bull', 'bear', 'crash', 'recovery', 'volatile']
            current_trend = random.choices(trends, weights=[0.4, 0.3, 0.05, 0.1, 0.15])[0]
            
            updates = []
            for asset in assets:
                change_pct = random.uniform(-0.02, 0.02)
                if current_trend == 'bull': change_pct += random.uniform(0.001, 0.01)
                elif current_trend == 'bear': change_pct -= random.uniform(0.001, 0.01)
                elif current_trend == 'crash': change_pct -= random.uniform(0.05, 0.15)
                elif current_trend == 'recovery': change_pct += random.uniform(0.03, 0.08)
                
                asset.current_price = max(0.01, asset.current_price * (1 + change_pct))
                updates.append({"code": asset.code, "price": round(asset.current_price, 2)})
            
            db.session.commit()
            socketio.emit('market_update', {"trend": current_trend, "assets": updates})

def background_daily_currency_reset():
    while True:
        socketio.sleep(86400) # Re-runs daily
        with app.app_context():
            rates = CurrencyRates.query.all()
            for r in rates:
                r.rate_to_inr *= random.uniform(0.95, 1.05)
            db.session.commit()

@socketio.on('join_global')
def on_join_global(data):
    join_room('global')

@socketio.on('send_global_msg')
def handle_global_msg(data):
    uid = data.get('user_id')
    msg_txt = data.get('content', '').strip()
    if msg_txt:
        user = User.query.get(uid)
        msg = Message(sender_id=uid, content=msg_txt)
        db.session.add(msg)
        db.session.commit()
        emit('receive_global_msg', {
            "username": user.username,
            "content": msg_txt,
            "timestamp": datetime.datetime.utcnow().strftime('%H:%M')
        }, room='global')

if __name__ == '__main__':
    if not os.path.exists('uploads'):
        os.makedirs('uploads')
        
    with app.app_context():
        db.create_all()
        
        # Seed Assets
        if not Asset.query.first():
            assets_list = [
                ('Bitcoin', 'BTC', 8500000.0), ('Ethereum', 'ETH', 310000.0),
                ('Gold', 'XAU', 7200.0), ('Silver', 'XAG', 92.0),
                ('Platinum', 'XPT', 2800.0), ('Oil', 'CRUDE', 6200.0),
                ('Copper', 'HG', 780.0), ('Lithium', 'LIT', 14000.0)
            ]
            for name, code, price in assets_list:
                db.session.add(Asset(name=name, code=code, current_price=price))
                
        # Seed Currency Conversion Rates
        if not CurrencyRates.query.first():
            currencies = [
                ('USD', 87.5), ('EUR', 93.2), ('GBP', 111.4), ('JPY', 0.56),
                ('AUD', 57.2), ('CAD', 63.8), ('CHF', 98.1), ('SGD', 64.9), ('AED', 23.8)
            ]
            for code, rate in currencies:
                db.session.add(CurrencyRates(code=code, rate_to_inr=rate))
                
        # Super Admin Seeding Context
        if not User.query.filter_by(username='admin').first():
            adm = User(username='admin', email='admin@virtualbank.sim', is_admin=True)
            adm.set_password('admin123')
            db.session.add(adm)
            db.session.flush()
            db.session.add(User.query.get(adm.id).profile or db.session.add(User.query.get(adm.id).wallet or Wallet(user_id=adm.id)))
        
        db.session.commit()
        
    socketio.start_background_task(background_market_ticks)
    socketio.start_background_task(background_daily_currency_reset)
    socketio.run(app, debug=True, host='0.0.0.0', port=5000)

