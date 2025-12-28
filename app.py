import datetime
import json
import os
import re
import time
from functools import wraps
from datetime import datetime, timedelta

from flask import (
    Flask,
    flash,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
import requests
from bs4 import BeautifulSoup

# --- App 和数据库配置 ---
basedir = os.path.abspath(os.path.dirname(__file__))
app = Flask(__name__)
app.config["SECRET_KEY"] = "a_much_more_secret_key_for_sessions"
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///" + os.path.join(
    basedir, "instance", "portfolio.db"
)
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
db = SQLAlchemy(app)
migrate = Migrate(app, db)

# --- 登录配置 ---
CONFIG_USERNAME = "Fred"
CONFIG_PASSWORD = "Woshiliyuan12@."


# --- 数据库模型 ---
class DailyPrice(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.Date, nullable=False, index=True)
    metal_type = db.Column(db.String(10), nullable=False)
    price = db.Column(db.Float, nullable=False)
    __table_args__ = (db.UniqueConstraint("date", "metal_type", name="_date_metal_uc"),)


class Purchase(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    description = db.Column(db.String(100), nullable=False, default="持仓")
    metal_type = db.Column(db.String(10), nullable=False)
    grams = db.Column(db.Float, nullable=False)
    amount = db.Column(db.Float, nullable=False)
    transaction_date = db.Column(db.Date, nullable=False)
    creation_date = db.Column(db.DateTime, default=datetime.utcnow)


# --- 装饰器 ---
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if "logged_in" not in session:
            return redirect(url_for("login", next=request.url))
        return f(*args, **kwargs)

    return decorated_function


def get_price_data(start_date, end_date):
    """根据指定的日期范围从数据库获取价格数据"""

    def get_metal_data(metal):
        # 获取该金属类型的最新价格记录
        latest_price_obj = (
            DailyPrice.query.filter_by(metal_type=metal)
            .order_by(DailyPrice.date.desc())
            .first()
        )
        current_price = latest_price_obj.price if latest_price_obj else 0.0

        # 获取指定日期范围内的历史记录
        historical_records = (
            DailyPrice.query.filter(
                DailyPrice.metal_type == metal,
                DailyPrice.date >= start_date,
                DailyPrice.date <= end_date,
            )
            .order_by(DailyPrice.date.asc())
            .all()
        )

        return {"price": current_price, "historical_records": historical_records}

    return {"gold": get_metal_data("gold"), "silver": get_metal_data("silver")}



def calculate_range_analytics(price_records):
    """计算指定价格记录列表的均价和最低价"""
    if not price_records:
        return {"avg": "N/A", "min": "N/A"}

    prices = [p.price for p in price_records]

    avg = round(sum(prices) / len(prices), 2)
    min_price = min(prices)

    return {"avg": avg, "min": min_price}


# --- 爬虫函数 ---
def fetch_and_update_price():
    print(f"[{datetime.now()}] Running JS API scraper job...")
    timestamp = int(time.time() * 1000)
    url = f"http://res.huangjinjiage.com.cn/jin.js?t={timestamp}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36",
        "Referer": "http://www.huangjinjiage.cn/",
        "accept-language": "en",
    }
    try:
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        response.encoding = "GBK"
        js_content = response.text
        gold_match = re.search(r'hq_str_gds_AUTD="([\d.]+),', js_content)
        if not gold_match:
            raise ValueError("Could not parse gold price")
        gold_price = float(gold_match.group(1))

        silver_match = re.search(r'hq_str_gds_AGTD="([\d.]+),', js_content)
        if not silver_match:
            raise ValueError("Could not parse silver price")
        silver_price = round(float(silver_match.group(1)) / 1000, 4)

        today = datetime.today().date()
        for metal, price in [("gold", gold_price), ("silver", silver_price)]:
            record = DailyPrice.query.filter_by(date=today, metal_type=metal).first()
            if record:
                record.price = price
            else:
                db.session.add(DailyPrice(date=today, metal_type=metal, price=price))
        db.session.commit()
        print(f"Database updated: Gold {gold_price}, Silver {silver_price}")
    except Exception as e:
        print(f"An error occurred: {e}")
        db.session.rollback()


# --- Flask 路由 ---
@app.route("/")
@login_required
def index():
    end_date_str = request.args.get("end_date", datetime.today().strftime("%Y-%m-%d"))
    default_start_date = (datetime.today() - timedelta(days=29)).strftime("%Y-%m-%d")
    start_date_str = request.args.get("start_date", default_start_date)

    try:
        start_date = datetime.strptime(start_date_str, "%Y-%m-%d").date()
        end_date = datetime.strptime(end_date_str, "%Y-%m-%d").date()
    except ValueError:
        flash("日期格式不正确，已重置为默认范围。", "warning")
        end_date = datetime.today().date()
        start_date = end_date - timedelta(days=29)
        end_date_str = end_date.strftime("%Y-%m-%d")
        start_date_str = start_date.strftime("%Y-%m-%d")

    price_data = get_price_data(start_date, end_date)

    gold_analytics = calculate_range_analytics(price_data["gold"]["historical_records"])
    silver_analytics = calculate_range_analytics(
        price_data["silver"]["historical_records"]
    )

    gold_chart_labels = json.dumps(
        [r.date.strftime("%m-%d") for r in price_data["gold"]["historical_records"]]
    )
    gold_chart_data = json.dumps(
        [r.price for r in price_data["gold"]["historical_records"]]
    )
    silver_chart_labels = json.dumps(
        [r.date.strftime("%m-%d") for r in price_data["silver"]["historical_records"]]
    )
    silver_chart_data = json.dumps(
        [r.price for r in price_data["silver"]["historical_records"]]
    )

    return render_template(
        "index.html",
        price_data=price_data,
        gold_analytics=gold_analytics,
        silver_analytics=silver_analytics,
        gold_chart_labels=gold_chart_labels,
        gold_chart_data=gold_chart_data,
        silver_chart_labels=silver_chart_labels,
        silver_chart_data=silver_chart_data,
        start_date=start_date_str,
        end_date=end_date_str,
    )


@app.route("/portfolio")
@login_required
def portfolio():
    today = datetime.today().date()
    thirty_days_ago = today - timedelta(days=29)
    price_data_full = get_price_data(thirty_days_ago, today)
    current_prices = {
        "gold": price_data_full["gold"]["price"],
        "silver": price_data_full["silver"]["price"],
    }

    sort_by = request.args.get("sort_by", "date_desc")
    start_date_str = request.args.get("start_date")
    end_date_str = request.args.get("end_date")

    query = Purchase.query

    if start_date_str:
        start_date = datetime.strptime(start_date_str, "%Y-%m-%d").date()
        query = query.filter(Purchase.transaction_date >= start_date)
    if end_date_str:
        end_date = datetime.strptime(end_date_str, "%Y-%m-%d").date()
        query = query.filter(Purchase.transaction_date <= end_date)

    if sort_by == "date_desc":
        query = query.order_by(Purchase.transaction_date.desc())
    elif sort_by == "date_asc":
        query = query.order_by(Purchase.transaction_date.asc())
    elif sort_by == "weight_desc":
        query = query.order_by(Purchase.grams.desc())
    elif sort_by == "weight_asc":
        query = query.order_by(Purchase.grams.asc())

    purchases = query.all()

    total_grams = 0
    total_amount = 0
    total_current_value = 0

    for p in purchases:
        p.cost_per_gram = round(p.amount / p.grams, 2) if p.grams > 0 else 0
        current_price = current_prices.get(p.metal_type, 0)
        p.current_value = round(p.grams * current_price, 2)
        p.profit_loss = round(p.current_value - p.amount, 2)
        total_grams += p.grams
        total_amount += p.amount
        total_current_value += p.current_value

    total_profit_loss = round(total_current_value - total_amount, 2)

    return render_template(
        "portfolio.html",
        purchases=purchases,
        total_grams=round(total_grams, 2),
        total_amount=round(total_amount, 2),
        total_current_value=round(total_current_value, 2),
        total_profit_loss=total_profit_loss,
        current_sort=sort_by,
        start_date=start_date_str,
        end_date=end_date_str,
    )


@app.route("/add", methods=["POST"])
@login_required
def add_purchase():
    try:
        description = request.form.get("description", "持仓")
        metal_type = request.form.get("metal_type")
        grams = float(request.form.get("grams"))
        amount = float(request.form.get("amount"))
        date_str = request.form.get("transaction_date")
        transaction_date = datetime.strptime(date_str, "%Y-%m-%d").date()

        if metal_type not in ["gold", "silver"] or grams <= 0 or amount <= 0:
            flash("输入数据无效！", "danger")
        else:
            new_purchase = Purchase(
                description=description,
                metal_type=metal_type,
                grams=grams,
                amount=amount,
                transaction_date=transaction_date,
            )
            db.session.add(new_purchase)
            db.session.commit()
            flash(f'添加 "{description}" 成功！', "success")
    except (ValueError, TypeError):
        flash("输入数据格式不正确！", "danger")
    return redirect(url_for("portfolio"))


@app.route("/admin/prices", methods=["GET", "POST"])
@login_required
def manage_prices():
    if request.method == "POST":
        try:
            date_str = request.form.get("date")
            metal_type = request.form.get("metal_type")
            price = float(request.form.get("price"))
            date = datetime.strptime(date_str, "%Y-%m-%d").date()
            record_id = request.form.get("record_id")
            if record_id:
                record = DailyPrice.query.get(int(record_id))
                if record:
                    record.date = date
                    record.metal_type = metal_type
                    record.price = price
                    flash(f"更新 {date_str} 的 {metal_type} 价格成功！", "success")
                else:
                    flash("未找到要更新的记录！", "danger")
            else:
                existing_record = DailyPrice.query.filter_by(
                    date=date, metal_type=metal_type
                ).first()
                if existing_record:
                    flash(f"{date_str} 的 {metal_type} 价格已存在，请使用编辑功能更新。", "warning")
                else:
                    new_price = DailyPrice(
                        date=date, metal_type=metal_type, price=price
                    )
                    db.session.add(new_price)
                    flash(f"添加 {date_str} 的 {metal_type} 价格成功！", "success")
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            flash(f"操作失败: {e}", "danger")
        return redirect(url_for("manage_prices"))

    prices = (
        DailyPrice.query.order_by(DailyPrice.date.desc(), DailyPrice.metal_type.asc())
        .all()
    )
    return render_template("manage_prices.html", prices=prices)


@app.route("/admin/prices/delete/<int:price_id>")
@login_required
def delete_price(price_id):
    price_to_delete = DailyPrice.query.get_or_404(price_id)
    try:
        db.session.delete(price_to_delete)
        db.session.commit()
        flash("价格记录删除成功！", "success")
    except Exception as e:
        db.session.rollback()
        flash(f"删除失败: {e}", "danger")
    return redirect(url_for("manage_prices"))


@app.route("/delete/<int:id>")
@login_required
def delete_purchase(id):
    purchase_to_delete = Purchase.query.get_or_404(id)
    try:
        db.session.delete(purchase_to_delete)
        db.session.commit()
        flash("删除成功！", "info")
    except Exception as e:
        flash(f"删除失败！错误: {e}", "danger")
    return redirect(url_for("portfolio"))


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")
        if username == CONFIG_USERNAME and password == CONFIG_PASSWORD:
            session["logged_in"] = True
            flash("登录成功！", "success")
            return redirect(url_for("index"))
        else:
            flash("用户名或密码错误！", "danger")
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.pop("logged_in", None)
    flash("您已成功登出。", "info")
    return redirect(url_for("login"))


@app.cli.command("init-db")
def init_db_command():
    instance_path = os.path.join(basedir, "instance")
    if not os.path.exists(instance_path):
        os.makedirs(instance_path)
    db.create_all()
    print("Initialized the database.")


if __name__ == "__main__":
    instance_path = os.path.join(basedir, "instance")
    if not os.path.exists(instance_path):
        os.makedirs(instance_path)
    with app.app_context():
        db.create_all()
    app.run(debug=True, host="0.0.0.0", port=5000)
