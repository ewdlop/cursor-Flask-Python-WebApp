from flask import Flask, render_template, request, redirect, url_for, flash, send_file
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timedelta
from apscheduler.schedulers.background import BackgroundScheduler
import pandas as pd
import os
import json

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///todo.db'
app.config['SECRET_KEY'] = 'your-secret-key'  # 在生产环境中使用安全的密钥
db = SQLAlchemy(app)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

# 创建调度器
scheduler = BackgroundScheduler()
scheduler.start()

# 标签关联表
todo_tags = db.Table('todo_tags',
    db.Column('todo_id', db.Integer, db.ForeignKey('todo.id'), primary_key=True),
    db.Column('tag_id', db.Integer, db.ForeignKey('tag.id'), primary_key=True)
)

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    todos = db.relationship('Todo', backref='user', lazy=True)
    tags = db.relationship('Tag', backref='user', lazy=True)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password, method='pbkdf2:sha256')

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

class Tag(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False)
    color = db.Column(db.String(7), default='#6c757d')  # 默认灰色
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    todos = db.relationship('Todo', secondary=todo_tags, backref=db.backref('tags', lazy='dynamic'))

class Category(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    todos = db.relationship('Todo', backref='category', lazy=True)

class Todo(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text)
    complete = db.Column(db.Boolean, default=False)
    priority = db.Column(db.Integer, default=0)  # 0: 低, 1: 中, 2: 高
    due_date = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    category_id = db.Column(db.Integer, db.ForeignKey('category.id'))
    
    # 新增字段
    repeat_type = db.Column(db.String(20))  # daily, weekly, monthly, none
    repeat_interval = db.Column(db.Integer, default=1)  # 重复间隔
    reminder_time = db.Column(db.DateTime)  # 提醒时间
    parent_id = db.Column(db.Integer, db.ForeignKey('todo.id'))  # 用于重复任务
    subtasks = db.relationship('Todo', backref=db.backref('parent', remote_side=[id]))

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

def check_reminders():
    with app.app_context():
        now = datetime.utcnow()
        upcoming_todos = Todo.query.filter(
            Todo.reminder_time <= now + timedelta(minutes=30),
            Todo.reminder_time > now,
            Todo.complete == False
        ).all()
        
        for todo in upcoming_todos:
            # 这里可以添加发送提醒的逻辑，比如发送邮件或推送通知
            print(f"提醒：任务 '{todo.title}' 即将到期")

# 设置定时任务
scheduler.add_job(check_reminders, 'interval', minutes=30)

with app.app_context():
    db.create_all()

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        email = request.form.get('email')
        
        if User.query.filter_by(username=username).first():
            flash('用户名已存在')
            return redirect(url_for('register'))
        
        if User.query.filter_by(email=email).first():
            flash('邮箱已被注册')
            return redirect(url_for('register'))
        
        user = User(username=username, email=email)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        
        return redirect(url_for('login'))
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        user = User.query.filter_by(username=username).first()
        
        if user and user.check_password(password):
            login_user(user)
            return redirect(url_for('home'))
        flash('用户名或密码错误')
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

@app.route('/')
@login_required
def home():
    search_query = request.args.get('search', '')
    category_id = request.args.get('category', type=int)
    priority = request.args.get('priority', type=int)
    tag_id = request.args.get('tag', type=int)
    
    query = Todo.query.filter_by(user_id=current_user.id)
    
    if search_query:
        query = query.filter(Todo.title.ilike(f'%{search_query}%'))
    if category_id:
        query = query.filter_by(category_id=category_id)
    if priority is not None:
        query = query.filter_by(priority=priority)
    if tag_id:
        query = query.filter(Todo.tags.any(Tag.id == tag_id))
    
    todo_list = query.order_by(Todo.due_date.asc(), Todo.priority.desc()).all()
    categories = Category.query.filter_by(user_id=current_user.id).all()
    tags = Tag.query.filter_by(user_id=current_user.id).all()
    
    return render_template('index.html', 
                         todo_list=todo_list, 
                         categories=categories,
                         tags=tags,
                         search_query=search_query,
                         selected_category=category_id,
                         selected_priority=priority,
                         selected_tag=tag_id)

@app.route('/add', methods=['POST'])
@login_required
def add():
    title = request.form.get('title')
    description = request.form.get('description')
    category_id = request.form.get('category_id', type=int)
    priority = request.form.get('priority', type=int, default=0)
    due_date_str = request.form.get('due_date')
    repeat_type = request.form.get('repeat_type')
    repeat_interval = request.form.get('repeat_interval', type=int, default=1)
    reminder_time_str = request.form.get('reminder_time')
    tag_ids = request.form.getlist('tag_ids')
    
    if title:
        due_date = datetime.strptime(due_date_str, '%Y-%m-%d') if due_date_str else None
        reminder_time = datetime.strptime(reminder_time_str, '%Y-%m-%dT%H:%M') if reminder_time_str else None
        
        new_todo = Todo(
            title=title,
            description=description,
            priority=priority,
            due_date=due_date,
            user_id=current_user.id,
            category_id=category_id,
            repeat_type=repeat_type,
            repeat_interval=repeat_interval,
            reminder_time=reminder_time
        )
        
        # 添加标签
        if tag_ids:
            for tag_id in tag_ids:
                tag = Tag.query.get(tag_id)
                if tag and tag.user_id == current_user.id:
                    new_todo.tags.append(tag)
        
        db.session.add(new_todo)
        db.session.commit()
        
        # 如果是重复任务，创建后续任务
        if repeat_type and repeat_type != 'none':
            create_recurring_todos(new_todo)
    
    return redirect(url_for('home'))

def create_recurring_todos(parent_todo):
    if parent_todo.repeat_type == 'daily':
        delta = timedelta(days=parent_todo.repeat_interval)
    elif parent_todo.repeat_type == 'weekly':
        delta = timedelta(weeks=parent_todo.repeat_interval)
    elif parent_todo.repeat_type == 'monthly':
        delta = timedelta(days=30 * parent_todo.repeat_interval)
    else:
        return
    
    # 创建未来3个重复任务
    for i in range(3):
        due_date = parent_todo.due_date + delta * (i + 1)
        reminder_time = parent_todo.reminder_time + delta * (i + 1) if parent_todo.reminder_time else None
        
        new_todo = Todo(
            title=parent_todo.title,
            description=parent_todo.description,
            priority=parent_todo.priority,
            due_date=due_date,
            user_id=parent_todo.user_id,
            category_id=parent_todo.category_id,
            repeat_type=parent_todo.repeat_type,
            repeat_interval=parent_todo.repeat_interval,
            reminder_time=reminder_time,
            parent_id=parent_todo.id
        )
        
        # 复制标签
        for tag in parent_todo.tags:
            new_todo.tags.append(tag)
        
        db.session.add(new_todo)
    
    db.session.commit()

@app.route('/add_category', methods=['POST'])
@login_required
def add_category():
    name = request.form.get('name')
    if name:
        category = Category(name=name, user_id=current_user.id)
        db.session.add(category)
        db.session.commit()
    return redirect(url_for('home'))

@app.route('/add_tag', methods=['POST'])
@login_required
def add_tag():
    name = request.form.get('name')
    color = request.form.get('color', '#6c757d')
    if name:
        tag = Tag(name=name, color=color, user_id=current_user.id)
        db.session.add(tag)
        db.session.commit()
    return redirect(url_for('home'))

@app.route('/complete/<int:todo_id>')
@login_required
def complete(todo_id):
    todo = Todo.query.get_or_404(todo_id)
    if todo.user_id == current_user.id:
        todo.complete = not todo.complete
        db.session.commit()
    return redirect(url_for('home'))

@app.route('/delete/<int:todo_id>')
@login_required
def delete(todo_id):
    todo = Todo.query.get_or_404(todo_id)
    if todo.user_id == current_user.id:
        db.session.delete(todo)
        db.session.commit()
    return redirect(url_for('home'))

@app.route('/export')
@login_required
def export_todos():
    todos = Todo.query.filter_by(user_id=current_user.id).all()
    
    # 准备数据
    data = []
    for todo in todos:
        data.append({
            '标题': todo.title,
            '描述': todo.description,
            '优先级': ['低', '中', '高'][todo.priority],
            '状态': '已完成' if todo.complete else '未完成',
            '分类': todo.category.name if todo.category else '',
            '标签': ', '.join(tag.name for tag in todo.tags),
            '截止日期': todo.due_date.strftime('%Y-%m-%d') if todo.due_date else '',
            '创建时间': todo.created_at.strftime('%Y-%m-%d %H:%M'),
            '重复类型': todo.repeat_type if todo.repeat_type else '不重复'
        })
    
    # 创建DataFrame并导出为Excel
    df = pd.DataFrame(data)
    excel_file = 'todos_export.xlsx'
    df.to_excel(excel_file, index=False)
    
    return send_file(excel_file, as_attachment=True)

if __name__ == '__main__':
    app.run(debug=True) 