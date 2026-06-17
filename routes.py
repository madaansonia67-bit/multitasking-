import os
import json
import random
import datetime
from flask import Blueprint, render_init_template, render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_user, logout_user, login_required, current_user
from werkzeug.utils import secure_filename
from models import (db, User, Profile, Wallet, Transaction, Asset, Holding, 
                    AssetTransaction, CurrencyRates, CurrencyConversions, 
                    ScratchCard, LotteryHistory, Message, Friendship, Follow, 
                    Post, Comment, Notification, Achievement, AdminLog)

main_bp = Blueprint('main', __name__)

ALLOWED_IMAGE = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
ALLOWED_VIDEO = {'mp4', 'webm'}

def allowed_file(filename, allowed_set):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in allowed_set

def add_xp(user, amount):
    p = user.profile
    p.xp += amount
    next_lvl = p.level * 100
    if p.xp >= next_lvl:
        p.xp -= next_lvl
        p.level += 1
        create_notification(user.id, f"Level Up! You reached level {p.level}!", "level")
    db.session.commit()

def create_notification(user_id, message, ntype="general"):
    notif = Notification(user_id=user_id, message=message, ntype=ntype)
    db.session.add(notif)
    db.session.commit()

def trigger_achievement(user_id, title, desc):
    exists = Achievement.query.filter_by(user_id=user_id, title=title).first()
    if not exists:
        ach = Achievement(user_id=user_id, title=title, description=desc)
        db.session.add(ach)
        db.session.commit()
        create_notification(user_id, f"Achievement Unlocked: {title}!", "achievement")
        add_xp(User.query.get(user_id), 50)

@main_bp.route('/')
def index():
    if current_user.is_authenticated:
        return redirect(url_for('main.dashboard'))
    return render_template('auth.html')

@main_bp.route('/register', methods=['POST'])
def register():
    username = request.form.get('username', '').strip()
    email = request.form.get('email', '').strip()
    password = request.form.get('password')
    ref_by = request.form.get('referred_by', '').strip()

    if not username or not email or not password:
        flash("All fields are mandatory.")
        return redirect(url_for('main.index'))

    if User.query.filter_by(username=username).first() or User.query.filter_by(email=email).first():
        flash("Username or Email already taken.")
        return redirect(url_for('main.index'))

    new_user = User(username=username, email=email, referral_code=f"REF-{random.randint(1000,9999)}")
    if ref_by and User.query.filter_by(referral_code=ref_by).first():
        new_user.referred_by = ref_by
    new_user.set_password(password)
    
    db.session.add(new_user)
    db.session.commit()

    prof = Profile(user_id=new_user.id)
    wal = Wallet(user_id=new_user.id, balance_inr=0.0)
    db.session.add_all([prof, wal])
    db.session.commit()

    trigger_achievement(new_user.id, "First Login", "Welcome to the simulation platform!")
    if new_user.referred_by:
        referrer = User.query.filter_by(referral_code=new_user.referred_by).first()
        referrer.wallet.balance_inr += 50.0
        create_notification(referrer.id, f"Referral Reward! ₹50 added for referring {username}.", "referral")

    login_user(new_user)
    return redirect(url_for('main.dashboard'))

@main_bp.route('/login', methods=['POST'])
def login():
    username = request.form.get('username', '').strip()
    password = request.form.get('password')
    user = User.query.filter_by(username=username).first()
    if user and user.check_password(password):
        if user.is_banned:
            flash("Your account has been banned.")
            return redirect(url_for('main.index'))
        login_user(user)
        return redirect(url_for('main.dashboard'))
    flash("Invalid credentials setup.")
    return redirect(url_for('main.index'))

@main_bp.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('main.index'))

@main_bp.route('/dashboard')
@login_required
def dashboard():
    txs = Transaction.query.filter((Transaction.sender_id == current_user.id) | (Transaction.receiver_id == current_user.id)).order_index_by(Transaction.timestamp.desc()).limit(5).all()
    notifs = Notification.query.filter_by(user_id=current_user.id, is_read=False).order_by(Notification.timestamp.desc()).all()
    assets = Asset.query.limit(4).all()
    return render_template('dashboard.html', txs=txs, notifs=notifs, assets=assets)

@main_bp.route('/set-theme', methods=['POST'])
@login_required
def set_theme():
    theme = request.json.get('theme')
    if theme in ['cyberpunk', 'dark', 'light', 'dark-neon', 'light-neon', 'dark-premium', 'ocean', 'emerald', 'galaxy']:
        current_user.wallet.theme_preference = theme
        db.session.commit()
        return jsonify({"status": "success"})
    return jsonify({"status": "error"}), 400

@main_bp.route('/daily-reward', methods=['POST'])
@login_required
def daily_reward():
    prof = current_user.profile
    now = datetime.datetime.utcnow()
    if prof.last_reward_claim:
        diff = now - prof.last_reward_claim
        if diff.total_seconds() < 86400:
            return jsonify({"status": "error", "message": f"Try again in {str(datetime.timedelta(seconds=int(86400 - diff.total_seconds())))}"}), 400
        if diff.total_seconds() < 172800:
            prof.streak_count += 1
        else:
            prof.streak_count = 1
    else:
        prof.streak_count = 1

    reward = random.randint(1, 15)
    bonus = min(prof.streak_count * 2, 30)
    total = reward + bonus
    
    current_user.wallet.balance_inr += total
    prof.last_reward_claim = now
    
    tx = Transaction(receiver_id=current_user.id, amount=total, tx_type='reward')
    db.session.add(tx)
    db.session.commit()
    
    trigger_achievement(current_user.id, "Daily Reward Master", "Claimed daily rewards successfully.")
    add_xp(current_user, 20)
    
    return jsonify({"status": "success", "reward": reward, "bonus": bonus, "total": total, "streak": prof.streak_count})

@main_bp.route('/transfer', methods=['POST'])
@login_required
def transfer():
    target_username = request.form.get('username', '').strip()
    amount_str = request.form.get('amount')
    mode = request.form.get('type') # 'money', 'asset', 'scratch_card'
    
    target_user = User.query.filter_by(username=target_username).first()
    if not target_user or target_user.id == current_user.id:
        flash("Invalid target account.")
        return redirect(url_for('main.dashboard'))

    if mode == 'money':
        try:
            amount = float(amount_str)
        except:
            flash("Invalid financial allocation amount.")
            return redirect(url_for('main.dashboard'))
        if amount <= 0 or current_user.wallet.balance_inr < amount:
            flash("Insufficient virtual resources or bad amount.")
            return redirect(url_for('main.dashboard'))
        
        current_user.wallet.balance_inr -= amount
        target_user.wallet.balance_inr += amount
        
        tx = Transaction(sender_id=current_user.id, receiver_id=target_user.id, amount=amount, tx_type='transfer')
        db.session.add(tx)
        db.session.commit()
        
        create_notification(target_user.id, f"Received ₹{amount} from {current_user.username}", "transfer")
        trigger_achievement(current_user.id, "First Transfer", "Sent virtual resources to a friend.")
        
    elif mode == 'asset':
        asset_code = request.form.get('asset_code')
        qty = float(request.form.get('quantity', 0))
        asset = Asset.query.filter_by(code=asset_code).first()
        if not asset or qty <= 0:
            flash("Invalid assets target configuration.")
            return redirect(url_for('main.dashboard'))
        
        hold = Holding.query.filter_by(user_id=current_user.id, asset_id=asset.id).first()
        if not hold or hold.quantity < qty:
            flash("Insufficient asset quantities.")
            return redirect(url_for('main.dashboard'))
        
        hold.quantity -= qty
        target_hold = Holding.query.filter_by(user_id=target_user.id, asset_id=asset.id).first()
        if not target_hold:
            target_hold = Holding(user_id=target_user.id, asset_id=asset.id, quantity=0, avg_purchase_price=asset.current_price)
            db.session.add(target_hold)
        target_hold.quantity += qty
        
        tx_out = AssetTransaction(user_id=current_user.id, asset_id=asset.id, tx_type='TRANSFER_OUT', quantity=qty, price_per_unit=asset.current_price)
        tx_in = AssetTransaction(user_id=target_user.id, asset_id=asset.id, tx_type='TRANSFER_IN', quantity=qty, price_per_unit=asset.current_price)
        db.session.add_all([tx_out, tx_in])
        db.session.commit()
        create_notification(target_user.id, f"Received {qty} units of {asset.name} from {current_user.username}", "asset")

    elif mode == 'scratch_card':
        card = ScratchCard.query.filter_by(user_id=current_user.id, is_scratched=False).first()
        if not card:
            flash("No intact scratch cards to transfer.")
            return redirect(url_for('main.dashboard'))
        card.user_id = target_user.id
        db.session.commit()
        create_notification(target_user.id, f"Received a custom scratch card from {current_user.username}", "lottery")

    flash("Transfer run completed successfully.")
    return redirect(url_for('main.dashboard'))

@main_bp.route('/currency')
@login_required
def currency_page():
    rates = CurrencyRates.query.all()
    return render_template('investment.html', rates=rates)

@main_bp.route('/currency-convert', methods=['POST'])
@login_required
def currency_convert():
    from_c = request.form.get('from_currency')
    to_c = request.form.get('to_currency')
    amount = float(request.form.get('amount', 0))
    
    if amount <= 0:
        flash("Invalid operation values.")
        return redirect(url_for('main.currency_page'))

    wallet = current_user.wallet
    
    # Simple architecture conversion mechanism using standard rates to INR
    if from_c == 'INR':
        from_rate = 1.0
    else:
        from_rate = CurrencyRates.query.filter_by(code=from_c).first().rate_to_inr
        
    if to_c == 'INR':
        to_rate = 1.0
    else:
        to_rate = CurrencyRates.query.filter_by(code=to_c).first().rate_to_inr

    # Fetch source balance dynamically
    src_balance = getattr(wallet, from_c.lower() if from_c != 'INR' else 'balance_inr')
    if src_balance < amount:
        flash("Insufficient funds in source currency.")
        return redirect(url_for('main.currency_page'))

    amount_in_inr = amount * from_rate
    target_amount = amount_in_inr / to_rate

    setattr(wallet, from_c.lower() if from_c != 'INR' else 'balance_inr', src_balance - amount)
    dest_balance = getattr(wallet, to_c.lower() if to_c != 'INR' else 'balance_inr')
    setattr(wallet, to_c.lower() if to_c != 'INR' else 'balance_inr', dest_balance + target_amount)

    conv = CurrencyConversions(user_id=current_user.id, from_currency=from_c, to_currency=to_c, from_amount=amount, to_amount=target_amount)
    db.session.add(conv)
    db.session.commit()
    
    flash("Currency conversion successfully verified.")
    return redirect(url_for('main.currency_page'))

@main_bp.route('/market')
@login_required
def market():
    assets = Asset.query.all()
    holdings = Holding.query.filter_by(user_id=current_user.id).all()
    return render_template('market.html', assets=assets, holdings=holdings)

@main_bp.route('/market/trade', methods=['POST'])
@login_required
def trade_asset():
    asset_id = int(request.form.get('asset_id'))
    action = request.form.get('action') # 'BUY' or 'SELL'
    qty = float(request.form.get('quantity', 0))
    
    asset = Asset.query.get_or_404(asset_id)
    if qty <= 0:
        flash("Quantity must be positive.")
        return redirect(url_for('main.market'))

    total_cost = asset.current_price * qty
    wallet = current_user.wallet
    hold = Holding.query.filter_by(user_id=current_user.id, asset_id=asset.id).first()

    if action == 'BUY':
        if wallet.balance_inr < total_cost:
            flash("Insufficient balance to buy asset.")
            return redirect(url_for('main.market'))
        wallet.balance_inr -= total_cost
        if not hold:
            hold = Holding(user_id=current_user.id, asset_id=asset.id, quantity=0, avg_purchase_price=0)
            db.session.add(hold)
        
        total_qty = hold.quantity + qty
        hold.avg_purchase_price = ((hold.avg_purchase_price * hold.quantity) + total_cost) / total_qty
        hold.quantity = total_qty
        
        trigger_achievement(current_user.id, "First Investment", "Purchased your first asset.")
        
    elif action == 'SELL':
        if not hold or hold.quantity < qty:
            flash("You do not hold enough units to sell.")
            return redirect(url_for('main.market'))
        
        hold.quantity -= qty
        wallet.balance_inr += total_cost
        
        if hold.avg_purchase_price < asset.current_price:
            trigger_achievement(current_user.id, "First Profit", "Sold an asset above purchase price.")

    tx = AssetTransaction(user_id=current_user.id, asset_id=asset.id, tx_type=action, quantity=qty, price_per_unit=asset.current_price)
    db.session.add(tx)
    db.session.commit()
    
    flash(f"Trade successfully processed: {action} {qty} units.")
    return redirect(url_for('main.market'))

@main_bp.route('/lottery')
@login_required
def lottery():
    history = LotteryHistory.query.filter_by(user_id=current_user.id).order_by(LotteryHistory.timestamp.desc()).all()
    return render_template('lottery.html', history=history)

@main_bp.route('/lottery/buy', methods=['POST'])
@login_required
def buy_lottery():
    cost = float(request.form.get('cost', 0))
    if cost not in [5.0, 10.0, 20.0, 50.0]:
        return jsonify({"status": "error", "message": "Invalid configuration choice."}), 400
        
    if current_user.wallet.balance_inr < cost:
        return jsonify({"status": "error", "message": "Insufficient resources balance."}), 400

    current_user.wallet.balance_inr -= cost
    
    pos_pools = [1, 2, 5, 10, 20, 50, 100]
    neg_pools = [1, 2, 5, 10, 20]
    
    cells = []
    for _ in range(16):
        if random.random() > 0.4:
            cells.append(random.choice(pos_pools))
        else:
            cells.append(-random.choice(neg_pools))
            
    card = ScratchCard(cost=cost, cell_values=json.dumps(cells), is_scratched=False, user_id=current_user.id)
    db.session.add(card)
    db.session.commit()
    
    return jsonify({"status": "success", "card_id": card.id, "cells": cells})

@main_bp.route('/lottery/scratch', methods=['POST'])
@login_required
def scratch_card_action():
    card_id = request.json.get('card_id')
    card = ScratchCard.query.filter_by(id=card_id, user_id=current_user.id, is_scratched=False).first()
    if not card:
        return jsonify({"status": "error", "message": "Invalid action execution target."}), 400

    cells = json.loads(card.cell_values)
    total_won = sum(cells)
    
    # Avoid overall negative balances from the transaction calculation rules
    if total_won < 0 and current_user.wallet.balance_inr + total_won < 0:
        total_won = -current_user.wallet.balance_inr

    current_user.wallet.balance_inr += total_won
    card.is_scratched = True
    
    lh = LotteryHistory(user_id=current_user.id, card_cost=card.cost, total_won=total_won)
    db.session.add(lh)
    db.session.commit()
    
    if total_won > card.cost:
        trigger_achievement(current_user.id, "Lottery Winner", "Won more than cost of scratch card!")

    return jsonify({"status": "success", "total_won": total_won, "new_balance": current_user.wallet.balance_inr})

@main_bp.route('/forum', methods=['GET', 'POST'])
@login_required
def forum():
    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        content = request.form.get('content', '').strip()
        category = request.form.get('category', 'General')
        
        if not title or not content:
            flash("Title and Content are mandatory components.")
            return redirect(url_for('main.forum'))
            
        file = request.files.get('media')
        media_url, media_type = None, None
        if file and file.filename != '':
            if allowed_file(file.filename, ALLOWED_IMAGE):
                filename = secure_filename(file.filename)
                file.save(os.path.join('uploads', filename))
                media_url = filename
                media_type = 'image'
            elif allowed_file(file.filename, ALLOWED_VIDEO):
                filename = secure_filename(file.filename)
                file.save(os.path.join('uploads', filename))
                media_url = filename
                media_type = 'video'

        post = Post(user_id=current_user.id, title=title, content=content, category=category, media_url=media_url, media_type=media_type)
        db.session.add(post)
        current_user.profile.reputation += 2
        db.session.commit()
        trigger_achievement(current_user.id, "Community Contributor", "Created a community forum article entry.")
        return redirect(url_for('main.forum'))

    posts = Post.query.order_by(Post.timestamp.desc()).all()
    return render_template('forum.html', posts=posts)

@main_bp.route('/forum/comment/<int:post_id>', methods=['POST'])
@login_required
def add_comment(post_id):
    content = request.form.get('content', '').strip()
    if content:
        comment = Comment(post_id=post_id, user_id=current_user.id, content=content)
        db.session.add(comment)
        post = Post.query.get(post_id)
        create_notification(post.user_id, f"{current_user.username} commented on your post.", "forum")
        db.session.commit()
    return redirect(url_for('main.forum'))

@main_bp.route('/chat')
@login_required
def chat():
    users = User.query.filter(User.id != current_user.id).all()
    return render_template('chat.html', users=users)

@main_bp.route('/profile/<username>')
@login_required
def view_profile(username):
    user = User.query.filter_by(username=username).first_or_404()
    is_following = Follow.query.filter_by(follower_id=current_user.id, followed_id=user.id).first() is not None
    is_friend = Friendship.query.filter_by(user_id=current_user.id, friend_id=user.id).first() is not None
    achievements = Achievement.query.filter_by(user_id=user.id).all()
    return render_template('profile.html', target_user=user, is_following=is_following, is_friend=is_friend, achievements=achievements)

@main_bp.route('/profile/edit', methods=['POST'])
@login_required
def edit_profile():
    avatar_file = request.files.get('avatar')
    banner_file = request.files.get('banner')
    
    if avatar_file and allowed_file(avatar_file.filename, ALLOWED_IMAGE):
        filename = secure_filename(avatar_file.filename)
        avatar_file.save(os.path.join('uploads', filename))
        current_user.profile.avatar = filename

    if banner_file and allowed_file(banner_file.filename, ALLOWED_IMAGE):
        filename = secure_filename(banner_file.filename)
        banner_file.save(os.path.join('uploads', filename))
        current_user.profile.banner = filename

    db.session.commit()
    return redirect(url_for('main.view_profile', username=current_user.username))

@main_bp.route('/follow/<int:user_id>', methods=['POST'])
@login_required
def follow_user(user_id):
    existing = Follow.query.filter_by(follower_id=current_user.id, followed_id=user_id).first()
    if not existing:
        f = Follow(follower_id=current_user.id, followed_id=user_id)
        db.session.add(f)
        db.session.commit()
    return redirect(request.referrer)

@main_bp.route('/unfollow/<int:user_id>', methods=