from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from datetime import datetime, timedelta
from werkzeug.security import generate_password_hash, check_password_hash
import secrets
from yookassa import Configuration, Payment, Payout
import uuid

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///Users.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.secret_key = 'your-secret-key-here'
db = SQLAlchemy(app)
migrate = Migrate(app, db)


# Модель для пользователей
class Users(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    login = db.Column(db.String(50), unique=True, nullable=False)
    password = db.Column(db.String(100), nullable=False)
    is_active = db.Column(db.Boolean, default=False) 
    last_activity = db.Column(db.DateTime) 
    registration_date = db.Column(db.DateTime, default=datetime.now)
    subscription = db.Column(db.String(20), server_default='Базовая', nullable=False)
    balance = db.Column(db.Integer, default=0, nullable=False)
    next_payment_date = db.Column(db.DateTime, nullable=True)

    def __repr__(self):
        return f'<User {self.login}>'


# Страница авторизации
@app.route('/', methods=['POST', 'GET'])
def my():
    if request.method == "POST":
        login = request.form.get('login')
        password = request.form.get('password')
        action = request.form.get('action')

        # 1. Логика ВХОДА
        if action == 'login':
            user = Users.query.filter_by(login=login).first()

            if not user:
                flash('Пользователь не найден. Зарегистрируйтесь', 'error')
            elif not check_password_hash(user.password, password):
                flash('Неверный пароль', 'error')
            else:
                user.is_active = True
                user.last_activity = datetime.now().replace(microsecond=0)
                db.session.commit()
                session['user_id'] = user.id
                if login == 'admin':
                    return redirect(url_for('admin'))
                else:
                    return redirect(url_for('head'))

        # 2. Логика РЕГИСТРАЦИИ
        elif action == 'register':
            if Users.query.filter_by(login=login).first():
                flash('Пользователь с таким логином уже существует', 'error')
            else:
                hashed_pw = generate_password_hash(password)
                new_user = Users(login=login, password=hashed_pw, subscription='Базовая')
                try:
                    db.session.add(new_user)
                    db.session.commit()
                    flash('Регистрация прошла успешно! Теперь вы можете войти.', 'success')
                except Exception as e:
                    db.session.rollback()
                    flash(f'Ошибка регистрации: {str(e)}', 'error')

        # 3. Логика ВОССТАНОВЛЕНИЯ ПАРОЛЯ
        elif action == 'forgot':
            user = Users.query.filter_by(login=login).first()
            if user:
                new_password = secrets.token_urlsafe(8)
                user.password = generate_password_hash(new_password)
                db.session.commit()
                flash(f'Ваш новый пароль: {new_password}', 'info')
            else:
                flash('Пользователь не найден', 'error')
                
    return render_template("my.html")


# Логика выхода из аккаунта
@app.route('/logout', methods=['POST'])
def logout():
    if 'user_id' in session:
        user = Users.query.get(session['user_id'])
        if user:
            user.is_active = False
            user.last_activity = datetime.now().replace(microsecond=0)
            db.session.commit()
        session.pop('user_id', None)
    flash('Вы успешно вышли', 'success')
    return redirect(url_for('my'))


# Главная страница
@app.route('/head')
def head():
    if 'user_id' not in session:
        flash('Требуется авторизация', 'error')
        return redirect(url_for('my'))
    
    user = Users.query.get(session['user_id'])
    movies = Movie.query.all()
    return render_template("head.html", movies=movies, user=user)


# Модель для истории транзакций
class Transaction(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    amount = db.Column(db.Integer, nullable=False)
    subscription = db.Column(db.String(100), nullable=False)
    transaction_date = db.Column(db.DateTime, default=datetime.now)
    operation_type = db.Column(db.String(20), nullable=False)

    user = db.relationship('Users', backref=db.backref('transactions', lazy=True))

    def __repr__(self):
        return f'<Transaction {self.id} - {self.subscription}>'
    

# Страница профиля
@app.route('/profile')
def profile():
    user = Users.query.get(session['user_id'])
    return render_template("profile.html", user=user)


# Страница меню
@app.route('/menu')
def menu():
    return render_template("menu.html")


# Модель для подписок
class Item(db.Model):
    id_sub = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(100), nullable=False )
    price = db.Column(db.Integer, nullable=False)
    isActive = db.Column(db.Boolean, default= True)
    text = db.Column(db.String(500), nullable= False)

    def __repr__(self):
        return f'Запись: {self.title}'


# Страница подписки
@app.route('/subscribe')
def subscribe():
    if 'user_id' not in session:
        flash('Требуется авторизация', 'error')
        return redirect(url_for('my'))
    
    user = Users.query.get(session['user_id'])
    subscriptions = Item.query.all()

    current_sub = next((sub for sub in subscriptions if sub.title == user.subscription), None)
    return render_template("subscribe.html", 
                         user=user, 
                         subscriptions=subscriptions,
                         current_sub=current_sub)


# Изменение подписки
@app.route('/change_subscription', methods=['POST'])
def change_subscription():
    data = request.get_json()
    subscription_name = data.get('subscription')
    price = data.get('price', 0)
    is_cancellation = data.get('cancel', False)
    
    if not subscription_name:
        return jsonify({'success': False, 'message': 'Не указана подписка'}), 400
    
    user = Users.query.get(session['user_id'])
    subscription = Item.query.filter_by(title=subscription_name).first()

    if user.subscription == subscription_name:
        return jsonify({
            'success': False, 
            'message': f'У вас уже приобретена подписка "{subscription_name}"'
        }), 400
    
    if not subscription:
        return jsonify({'success': False, 'message': 'Подписка не найдена'}), 404
    
    if user.balance < price:
        return jsonify({'success': False, 'message': 'Недостаточно средств на балансе'}), 400
    
    if is_cancellation and user.subscription != 'Базовая':
        try:
            current_sub = Item.query.filter_by(title=user.subscription).first()
            refund_amount = current_sub.price * 0.7 if current_sub else 0
            
            new_transaction = Transaction(
                user_id=user.id,
                amount=refund_amount,
                subscription=user.subscription,
                operation_type="refund"
            )
            
            user.balance += refund_amount
            user.subscription = 'Базовая'
            user.next_payment_date = None
            
            db.session.add(new_transaction)
            db.session.commit()
            
            return jsonify({'success': True})
        except Exception as e:
            db.session.rollback()
            return jsonify({'success': False, 'message': str(e)}), 500
    
    try:
        user.balance -= price
        user.subscription = subscription_name
        user.next_payment_date = datetime.now() + timedelta(days=30)
        new_transaction = Transaction(
            user_id=user.id,
            amount=price,
            subscription=subscription_name,
            operation_type="subscription"
        )
        db.session.add(new_transaction)
        db.session.commit()
        return jsonify({'success': True})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500


# Представление данных о подписке в JSON
@app.route('/get_subscription_info')
def get_subscription_info():
    name = request.args.get('name')
    subscription = Item.query.filter_by(title=name).first()
    
    return jsonify({
        'success': True,
        'subscription': {
            'title': subscription.title,
            'price': subscription.price,
            'text': subscription.text
        }
    })


# Страница баланса
Configuration.account_id = '1078879'
Configuration.secret_key = 'test_qi0U1HlAkUSahWXQA2FvdXHCQU-6hcRkB86t10EyDeE'
@app.route('/balance', methods=['GET', 'POST'])
def balance():
    user = Users.query.get(session['user_id'])
    if request.method  == 'POST':
        try:
            amount = float(request.form['amount'])
            action = request.form.get('action')
            idempotence_key = str(uuid.uuid4())
            payment = Payment.create({
            "amount": {
                "value": f"{amount:.2f}",
                "currency": "RUB"
            },
            "confirmation": {
                "type": "redirect",
                "return_url": url_for('balance', _external=True)
            },
            "capture": True,
        }, uuid.uuid4())
            
            if action == 'deposit':
                user.balance += amount
                flash(f'Баланс пополнен на {amount:.2f} рублей!' , 'success')
                new_transaction = Transaction(
                        user_id=user.id,
                        amount=amount,
                        subscription="-",
                        operation_type="deposit"
                )
                db.session.add(new_transaction)
            elif action == 'withdraw':
                if user.balance >= amount:
                    user.balance -= amount
                    flash(f'Средства выведены: {amount:.2f}', 'success')
                    new_transaction = Transaction(
                        user_id=user.id,
                        amount=amount,
                        subscription="-",
                        operation_type="withdrawal"
                    )
                    db.session.add(new_transaction)
                else:
                    flash('Ошибка. Недостаточно средств', 'error')
                    return redirect(url_for('balance'))

            db.session.commit()
            return redirect(payment.confirmation.confirmation_url)
        except Exception as e:
            flash(f'Ошибка при создании платежа: {str(e)}', 'error')
            db.session.rollback()
            return redirect(url_for('balance'))

    return render_template('balance.html', user=user)


@app.before_request
# Проверка активности пользователя
def check_session():
    if request.endpoint in ('my', 'static'):
        return
    if 'user_id' in session:
        user = Users.query.get(session['user_id'])
        if not user:
            session.clear()
            flash('Ваша сессия истекла', 'error')
            return redirect(url_for('my'))
        
        session_inactive = (user.last_activity is None or
                            user.last_activity < datetime.now().replace(microsecond=0) - timedelta(minutes=60))
        
        if session_inactive:
            user.is_active = False
            db.session.commit()
            session.clear()
            flash('Ваша сессия истекла из-за неактивности', 'error')
            return redirect(url_for('my'))
        
        # Автопродление подписки и уведомление пользователя
        if user.next_payment_date:
            time_until_expiry = user.next_payment_date - datetime.now()
            
            # Автопродление подписки при наступлении даты
            if user.next_payment_date <= datetime.now():
                current_sub = Item.query.filter_by(title=user.subscription).first()
                
                if current_sub and user.balance >= current_sub.price:
                    try:
                        user.balance -= current_sub.price
                        user.next_payment_date = datetime.now() + timedelta(days=30)
                        
                        new_transaction = Transaction(
                            user_id=user.id,
                            amount=current_sub.price,
                            subscription=user.subscription,
                            operation_type="deposit"
                        )
                        db.session.add(new_transaction)
                        db.session.commit()
                        
                        flash('Ваша подписка была автоматически продлена!', 'success')
                    except Exception as e:
                        db.session.rollback()
                        print(f"Ошибка при автоматическом продлении подписки: {str(e)}")
                        user.subscription = 'Базовая'
                        user.next_payment_date = None
                        db.session.commit()
                else:
                    user.subscription = 'Базовая'
                    user.next_payment_date = None
                    db.session.commit()
                    flash('Ваша подписка истекла. Недостаточно средств для продления. Установлена базовая подписка.', 'error')
            
            # Уведомление за 1 день до окончания
            elif timedelta(days=1) >= time_until_expiry > timedelta(0):
                if not hasattr(user, '_subscription_warning_shown') or not user._subscription_warning_shown:
                    flash(f'Ваша подписка истекает через 1 день! Пожалуйста, пополните баланс для автоматического продления.', 'error')
                    user._subscription_warning_shown = True 


# Страница админа с пользователями
@app.route('/admin', methods=['GET', 'POST'])
def admin():
    if request.method == 'POST' and 'reset_subscription' in request.form:
        user_id = request.form['user_id']
        user_to_reset = Users.query.get(user_id)
        if user_to_reset:
            user_to_reset.subscription = 'Базовая'
            user_to_reset.next_payment_date = None
            db.session.commit()
        return redirect(url_for('admin'))
    autorizations = Users.query.order_by(Users.id).all()
    return render_template("admin_head.html", data=autorizations)


# Страница админа добавление подписок
@app.route('/create_admin', methods=['POST', 'GET'])
def create():
    if request.method == 'POST':
        title = request.form['title']
        price = request.form['price']
        text = request.form['text']
        item = Item(title=title, price=price, text=text)
        try:
            db.session.add(item)
            db.session.commit()
            return redirect('/redact')
        except:
            return "Ошибка 228"
    else:
        return render_template('create_admin.html')


# Страница админа с подписками
@app.route('/redact')
def redact():
    subscriptions = Item.query.all()
    return render_template("admin_redact.html", subscriptions=subscriptions)


# Страница админа с редактированием подписок
@app.route('/admin_red/<int:id_sub>/update/', methods=['GET', 'POST'])
def update(id_sub):
    subscription = Item.query.get_or_404(id_sub)

    if request.method == 'POST':
        try:
            subscription.title = request.form['title']
            subscription.price = int(request.form['price'])
            subscription.text = request.form['text']
            db.session.commit()
            return redirect(url_for('redact'))
        except Exception as e:
            db.session.rollback()
            return redirect(url_for('update', id_sub=id_sub))
    return render_template('update_subscription.html', subscription=subscription)


# Страница админа удаления подписки
@app.route('/admin_red/<int:id_sub>/delete/', methods=['POST'])
def delete(id_sub):
    subscription = Item.query.get_or_404(id_sub)

    try:
        db.session.delete(subscription)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
    return redirect(url_for('redact'))


# Модель для фильмов
class Movie(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(100), nullable=False)
    genre = db.Column(db.String(50), nullable=False)
    year = db.Column(db.Integer, nullable=False)
    image_url = db.Column(db.String(255), nullable=False)
    watch_url = db.Column(db.String(255), nullable=False)
    age_rating = db.Column(db.String(1), nullable=False)  # Б, У, П
    subscription_required = db.Column(db.String(20), nullable=False, default='Базовая')

    def __repr__(self):
        return f'<Movie {self.title}>'


# Страница админа добавление фильмов
@app.route('/create_admin_movie', methods=['POST', 'GET'])
def create_movie():
    if request.method == 'POST':
        title = request.form['title']
        genre = request.form['genre']
        year = int(request.form['year'])
        image_url = request.form['image_url']
        watch_url = request.form['watch_url']
        age_rating = request.form['age_rating']
        subscription_required = request.form['subscription_required']
        movie = Movie(title=title, genre=genre, year=year, image_url=image_url, watch_url=watch_url, age_rating=age_rating, subscription_required=subscription_required)
        try:
            db.session.add(movie)
            db.session.commit()
            return redirect('/redact_movie')
        except:
            return "Ошибка 228"
    else:
        return render_template('create_admmov.html')


# Страница админа с подписками
@app.route('/redact_movie')
def redact_movie():
    movies = Movie.query.all()  # Получаем все фильмы из БД
    return render_template("admin_redmov.html", movies=movies)


# Страница админа с редактированием фильмов
@app.route('/admin_red_movie/<int:id>/update/', methods=['GET', 'POST'])
def update_movie(id):
    movie = Movie.query.get_or_404(id)
    if request.method == 'POST':
        try:
            movie.title = request.form['title']
            movie.genre = request.form['genre']
            movie.year = int(request.form['year'])
            movie.image_url = request.form['image_url']
            movie.watch_url = request.form['watch_url']
            movie.age_rating = request.form['age_rating']
            movie.subscription_required = request.form['subscription_required']
            db.session.commit()
            return redirect(url_for('redact_movie'))
        except Exception as e:
            db.session.rollback()
            return redirect(url_for('update_movie', id=id))
    return render_template('update_movie.html', movie=movie)


# Страница админа удаления фильма
@app.route('/admin_red_movie/<int:id>/delete/', methods=['POST'])
def delete_movie(id):
    movie = Movie.query.get_or_404(id)

    try:
        db.session.delete(movie)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
    return redirect(url_for('redact_movie'))


# Запуск приложения
if __name__ == "__main__":
    app.run(debug=True)