# app.py
import datetime
import json
import os
import re
import time
from functools import wraps
from datetime import datetime, timedelta  # 确保 timedelta 已导入

from flask import (Flask, flash, redirect, render_template, request, session,
                   url_for)
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
import requests
from bs4 import BeautifulSoup

# --- App 和数据库配置 ---
basedir = os.path.abspath(os.path.dirname(__file__))
app = Flask(__name__)
app.config['SECRET_KEY'] = 'a_much_more_secret_key_for_sessions'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(
    basedir, 'instance', 'portfolio.db'
)
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)
migrate = Migrate(app, db)

# --- 登录配置 ---
CONFIG_USERNAME = 'Fred'
CONFIG_PASSWORD = 'Woshiliyuan12@.'


# --- 数据库模型 ---
class DailyPrice(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.Date, nullable=False, index=True)
    metal_type = db.Column(db.String(10), nullable=False)
    price = db.Column(db.Float, nullable=False)
    __table_args__ = (db.UniqueConstraint('date', 'metal_type', name='_date_metal_uc'),)


class Purchase(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    description = db.Column(db.String(100), nullable=False, default='持仓')
    metal_type = db.Column(db.String(10), nullable=False)
    grams = db.Column(db.Float, nullable=False)
    amount = db.Column(db.Float, nullable=False)
    transaction_date = db.Column(db.Date, nullable=False)
    creation_date = db.Column(db.DateTime, default=datetime.utcnow)


# --- 装饰器和辅助函数 ---
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'logged_in' not in session:
            return redirect(url_for('login', next=request.url))
        return f(*args, **kwargs)

    return decorated_function


# --- 辅助函数 (已修正和整合) ---
def get_price_data():
    """从数据库获取价格数据"""
    today = datetime.today().date()
    thirty_days_ago = today - timedelta(days=29)

    def get_metal_data(metal):
        # 获取当日价格
        today_price_obj = DailyPrice.query.filter_by(date=today, metal_type=metal).first()
        current_price = today_price_obj.price if today_price_obj else 0.0

        # 获取过去30天的历史记录 (返回原始对象列表)
        historical_records = DailyPrice.query.filter(
            DailyPrice.metal_type == metal,
            DailyPrice.date >= thirty_days_ago,
            DailyPrice.date <= today
        ).order_by(DailyPrice.date.asc()).all()

        return {"price": current_price, "historical_records": historical_records}

    return {'gold': get_metal_data('gold'), 'silver': get_metal_data('silver')}


def analyze_prices(price_records):
    """根据数据库对象列表，计算分析指标。"""
    if not price_records:
        return {'avg_7': 'N/A', 'min_7': 'N/A',
                'avg_15': 'N/A', 'min_15': 'N/A',
                'avg_30': 'N/A', 'min_30': 'N/A'}

    today = datetime.utcnow().date()

    # 筛选不同时间段的价格数据
    prices_7_days = [p.price for p in price_records if p.date >= today - timedelta(days=6)]
    prices_15_days = [p.price for p in price_records if p.date >= today - timedelta(days=14)]
    all_prices_30 = [p.price for p in price_records]

    # 分别计算均价
    avg_7 = round(sum(prices_7_days) / len(prices_7_days), 2) if prices_7_days else 'N/A'
    avg_15 = round(sum(prices_15_days) / len(prices_15_days), 2) if prices_15_days else 'N/A'
    avg_30 = round(sum(all_prices_30) / len(all_prices_30), 2) if all_prices_30 else 'N/A'

    # --- 关键新增：分别计算最低价 ---
    min_7 = min(prices_7_days) if prices_7_days else 'N/A'
    min_15 = min(prices_15_days) if prices_15_days else 'N/A'
    min_30 = min(all_prices_30) if all_prices_30 else 'N/A'

    return {
        'avg_7': avg_7, 'min_7': min_7,
        'avg_15': avg_15, 'min_15': min_15,
        'avg_30': avg_30, 'min_30': min_30
    }


# ... (fetch_and_update_price 函数保持不变) ...
def fetch_and_update_price():
    """通过调用JS接口获取价格并更新数据库"""
    print(f"[{datetime.now()}] Running JS API scraper job...")

    # --- 1. 构造带有时间戳的URL ---
    # time.time() 返回秒，乘以1000得到毫秒，再取整
    timestamp = int(time.time() * 1000)
    url = f"http://res.huangjinjiage.com.cn/jin.js?t={timestamp}"

    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36',
        'Referer': 'http://www.huangjinjiage.cn/',  # 模拟来源页，更像真实请求
        'intervention': '<https://www.chromestatus.com/feature/5718547946799104>; level="warning"',  # 模拟来源页，更像真实请求
        'accept-language': 'en'  # 模拟来源页，更像真实请求
    }

    try:
        print(f"Fetching data from {url}...")
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        response.encoding = 'GBK'
        # JS文件内容是文本
        js_content = response.text

        # --- 2. 使用正则表达式解析黄金价格 ---
        # 匹配 hq_str_gds_AUTD = " 开头的字符串，并提取第一个数字
        gold_match = re.search(r'hq_str_gds_AUTD="([\d.]+),', js_content)
        if not gold_match:
            raise ValueError("Could not find or parse hq_str_gds_AUTD in JS content.")

        gold_price_str = gold_match.group(1)
        gold_price = float(gold_price_str)
        print(f"Found Gold (AUTD) price string: {gold_price_str}")

        # --- 3. 使用正则表达式解析白银价格 ---
        # 匹配 hq_str_gds_AGTD = " 开头的字符串，并提取第一个数字
        silver_match = re.search(r'hq_str_gds_AGTD="([\d.]+),', js_content)
        if not silver_match:
            raise ValueError("Could not find or parse hq_str_gds_AGTD in JS content.")

        silver_price_str = silver_match.group(1)
        # 按照您的要求，将原始价格除以1000
        silver_price = round(float(silver_price_str) / 1000, 4)
        print(f"Found Silver (AGTD) price string: {silver_price_str}, calculated price: {silver_price}")

        print(f"Scraped Prices -> Gold: {gold_price}, Silver: {silver_price}")

        # --- 4. 更新数据库 (逻辑不变) ---
        today = datetime.today().date()
        # 更新黄金
        gold_record = DailyPrice.query.filter_by(date=today, metal_type='gold').first()
        if gold_record:
            gold_record.price = gold_price
        else:
            gold_record = DailyPrice(date=today, metal_type='gold', price=gold_price)
            db.session.add(gold_record)
        # 更新白银
        silver_record = DailyPrice.query.filter_by(date=today, metal_type='silver').first()
        if silver_record:
            silver_record.price = silver_price
        else:
            silver_record = DailyPrice(date=today, metal_type='silver', price=silver_price)
            db.session.add(silver_record)
        db.session.commit()
        print("Database updated successfully.")

    except requests.exceptions.RequestException as e:
        print(f"A network error occurred: {e}")
        db.session.rollback()
    except Exception as e:
        print(f"An error occurred during scraping or DB update: {e}")
        db.session.rollback()


# --- Flask 路由 ---
@app.route('/')
@login_required
def index():
    price_data = get_price_data()

    # --- 关键修改：调用正确的分析函数 ---
    gold_analytics = analyze_prices(price_data['gold']['historical_records'])
    silver_analytics = analyze_prices(price_data['silver']['historical_records'])

    # --- 准备图表数据 ---
    gold_chart_labels = json.dumps([r.date.strftime('%m-%d') for r in price_data['gold']['historical_records']])
    gold_chart_data = json.dumps([r.price for r in price_data['gold']['historical_records']])
    silver_chart_labels = json.dumps([r.date.strftime('%m-%d') for r in price_data['silver']['historical_records']])
    silver_chart_data = json.dumps([r.price for r in price_data['silver']['historical_records']])

    return render_template('index.html',
                           price_data=price_data,
                           gold_analytics=gold_analytics,
                           silver_analytics=silver_analytics,
                           gold_chart_labels=gold_chart_labels,
                           gold_chart_data=gold_chart_data,
                           silver_chart_labels=silver_chart_labels,
                           silver_chart_data=silver_chart_data)


# ... (portfolio, add_purchase, manage_prices 等其他路由保持不变) ...
@app.route('/portfolio')
@login_required
def portfolio():
    # 1. 获取最新价格
    price_data = get_price_data()
    current_prices = {
        'gold': price_data['gold']['price'],
        'silver': price_data['silver']['price']
    }

    # 2. 获取筛选和排序参数
    sort_by = request.args.get('sort_by', 'date_desc')  # 默认按日期降序
    start_date_str = request.args.get('start_date')
    end_date_str = request.args.get('end_date')

    # 3. 构建基础查询
    query = Purchase.query

    # 4. 应用日期筛选
    if start_date_str:
        start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
        query = query.filter(Purchase.transaction_date >= start_date)
    if end_date_str:
        end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
        query = query.filter(Purchase.transaction_date <= end_date)

    # 5. 应用排序
    if sort_by == 'date_desc':
        query = query.order_by(Purchase.transaction_date.desc())
    elif sort_by == 'date_asc':
        query = query.order_by(Purchase.transaction_date.asc())
    elif sort_by == 'weight_desc':
        query = query.order_by(Purchase.grams.desc())
    elif sort_by == 'weight_asc':
        query = query.order_by(Purchase.grams.asc())

    purchases = query.all()

    # 6. 计算页面所需的所有数据
    total_grams = 0
    total_amount = 0
    total_current_value = 0

    for p in purchases:
        # 计算单项成本
        p.cost_per_gram = round(p.amount / p.grams, 2) if p.grams > 0 else 0

        # 计算单项当前价值和收益
        current_price = current_prices.get(p.metal_type, 0)
        p.current_value = round(p.grams * current_price, 2)
        p.profit_loss = round(p.current_value - p.amount, 2)

        # 累加总计
        total_grams += p.grams
        total_amount += p.amount
        total_current_value += p.current_value

    total_profit_loss = round(total_current_value - total_amount, 2)

    return render_template('portfolio.html',
                           purchases=purchases,
                           total_grams=round(total_grams, 2),
                           total_amount=round(total_amount, 2),
                           total_current_value=round(total_current_value, 2),
                           total_profit_loss=total_profit_loss,
                           current_sort=sort_by,  # 用于在模板中回显当前排序方式
                           start_date=start_date_str,
                           end_date=end_date_str)


# --- 别忘了更新 /add 路由 ---
@app.route('/add', methods=['POST'])
@login_required
def add_purchase():
    try:
        # 获取新字段
        description = request.form.get('description', '持仓')
        metal_type = request.form.get('metal_type')
        grams = float(request.form.get('grams'))
        amount = float(request.form.get('amount'))
        date_str = request.form.get('transaction_date')
        transaction_date = datetime.strptime(date_str, '%Y-%m-%d').date()

        if metal_type not in ['gold', 'silver'] or grams <= 0 or amount <= 0:
            flash('输入数据无效！', 'danger')
        else:
            new_purchase = Purchase(
                description=description,  # 保存新字段
                metal_type=metal_type,
                grams=grams,
                amount=amount,
                transaction_date=transaction_date
            )
            db.session.add(new_purchase)
            db.session.commit()
            flash(f'添加 "{description}" 成功！', 'success')
    except (ValueError, TypeError):
        flash('输入数据格式不正确！', 'danger')
    return redirect(url_for('portfolio'))


@app.route('/admin/prices', methods=['GET', 'POST'])
@login_required
def manage_prices():
    if request.method == 'POST':
        try:
            date_str = request.form.get('date')
            metal_type = request.form.get('metal_type')
            price = float(request.form.get('price'))
            date = datetime.strptime(date_str, '%Y-%m-%d').date()
            record_id = request.form.get('record_id')
            if record_id:
                record = DailyPrice.query.get(int(record_id))
                if record:
                    record.date = date
                    record.metal_type = metal_type
                    record.price = price
                    flash(f'更新 {date_str} 的 {metal_type} 价格成功！', 'success')
                else:
                    flash('未找到要更新的记录！', 'danger')
            else:
                existing_record = DailyPrice.query.filter_by(date=date, metal_type=metal_type).first()
                if existing_record:
                    flash(f'{date_str} 的 {metal_type} 价格已存在，请使用编辑功能更新。', 'warning')
                else:
                    new_price = DailyPrice(date=date, metal_type=metal_type, price=price)
                    db.session.add(new_price)
                    flash(f'添加 {date_str} 的 {metal_type} 价格成功！', 'success')
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            flash(f'操作失败: {e}', 'danger')
        return redirect(url_for('manage_prices'))
    prices = DailyPrice.query.order_by(DailyPrice.date.desc(), DailyPrice.metal_type.asc()).all()
    return render_template('manage_prices.html', prices=prices)


@app.route('/admin/prices/delete/<int:price_id>')
@login_required
def delete_price(price_id):
    price_to_delete = DailyPrice.query.get_or_404(price_id)
    try:
        db.session.delete(price_to_delete)
        db.session.commit()
        flash('价格记录删除成功！', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'删除失败: {e}', 'danger')
    return redirect(url_for('manage_prices'))


@app.route('/delete/<int:id>')
@login_required
def delete_purchase(id):
    purchase_to_delete = Purchase.query.get_or_404(id)
    try:
        db.session.delete(purchase_to_delete)
        db.session.commit()
        flash('删除成功！', 'info')
    except Exception as e:
        flash(f'删除失败！错误: {e}', 'danger')
    return redirect(url_for('portfolio'))


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        if username == CONFIG_USERNAME and password == CONFIG_PASSWORD:
            session['logged_in'] = True
            flash('登录成功！', 'success')
            return redirect(url_for('index'))
        else:
            flash('用户名或密码错误！', 'danger')
    return render_template('login.html')


@app.route('/logout')
def logout():
    session.pop('logged_in', None)
    flash('您已成功登出。', 'info')
    return redirect(url_for('login'))


@app.cli.command("init-db")
def init_db_command():
    instance_path = os.path.join(basedir, 'instance')
    if not os.path.exists(instance_path):
        os.makedirs(instance_path)
    db.create_all()
    print("Initialized the database.")


# --- 本地开发测试入口 ---
if __name__ == '__main__':
    instance_path = os.path.join(basedir, 'instance')
    if not os.path.exists(instance_path):
        os.makedirs(instance_path)
    with app.app_context():
        db.create_all()
    app.run(debug=True, host='0.0.0.0', port=5000)

