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
import pickle
from pathlib import Path
# 邮件发送相关导入
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.utils import formataddr

from flask_mail import Mail, Message

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

ALERT_COOLDOWN_FILE = Path(basedir) / "instance" / "alert_cooldown.pkl"
ALERT_COOLDOWN_HOURS = 4  # 同一预警4小时内只发送一次

# --- 邮件配置 ---
MAIL_CONFIG = {
    "smtp_server": "smtp.qq.com",
    "smtp_port": 465,
    "sender_email": "1040001060@qq.com",  # ← 替换为您的QQ邮箱
    "sender_password": "gezwtfwxnksubbjj",  # ← 替换为您的授权码
    "sender_name": "黄金持仓系统",
    "recipients": ["2240912272@qq.com", "1040001060@qq.com"]
}

mail = Mail(app)

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

        # === 新增：价格预警检查 ===
        # 检查黄金价格
        gold_alerts = check_price_alert("gold", gold_price)
        if gold_alerts:
            send_price_alert_email("gold", gold_alerts)

        # 检查白银价格
        silver_alerts = check_price_alert("silver", silver_price)
        if silver_alerts:
            send_price_alert_email("silver", silver_alerts)
        # === 预警检查结束 ===

    except Exception as e:
        print(f"An error occurred: {e}")
        db.session.rollback()


def check_price_alert(metal_type, current_price):
    """检查价格是否触发预警条件"""
    alerts = []

    today = datetime.today().date()
    periods = {
        "7日": 7,
        "15日": 15,
        "30日": 30
    }

    for period_name, days in periods.items():
        start_date = today - timedelta(days=days - 1)
        records = (
            DailyPrice.query.filter(
                DailyPrice.metal_type == metal_type,
                DailyPrice.date >= start_date,
                DailyPrice.date <= today
            )
            .all()
        )

        if records:
            prices = [r.price for r in records]
            min_price = min(prices)

            # 如果当前价格等于或低于该区间最低价，触发预警
            if current_price <= min_price:
                alerts.append({
                    "period": period_name,
                    "min_price": min_price,
                    "current_price": current_price
                })

    return alerts


def send_price_alert_email(metal_type, alerts):
    """发送价格预警邮件（HTML格式，UTF-8编码）"""
    if not alerts:
        return

    # 加载上次发送记录（冷却期检查）
    cooldown_data = {}
    if ALERT_COOLDOWN_FILE.exists():
        try:
            with open(ALERT_COOLDOWN_FILE, "rb") as f:
                cooldown_data = pickle.load(f)
        except:
            pass

    # 检查冷却期
    now = datetime.now()
    alert_key = f"{metal_type}_{'_'.join([a['period'] for a in alerts])}"

    if alert_key in cooldown_data:
        last_sent = cooldown_data[alert_key]
        if (now - last_sent).total_seconds() < ALERT_COOLDOWN_HOURS * 3600:
            print(f"[{now}] 预警 {alert_key} 在冷却期内，跳过发送")
            return

    metal_name = "黄金" if metal_type == "gold" else "白银"
    periods = "、".join([a["period"] for a in alerts])

    # 构建预警表格行
    alert_rows = ""
    for alert in alerts:
        alert_rows += f"""
        <tr>
            <td style="padding: 10px; border: 1px solid #ddd; text-align: center;">{alert['period']}</td>
            <td style="padding: 10px; border: 1px solid #ddd; text-align: center; color: #d9534f; font-weight: bold;">{alert['current_price']} 元/克</td>
            <td style="padding: 10px; border: 1px solid #ddd; text-align: center;">{alert['min_price']} 元/克</td>
        </tr>
        """

    # 构建HTML邮件内容
    html_content = f"""
    <html>
    <head>
        <meta charset="UTF-8">
        <style>
            body {{ font-family: Arial, 'Microsoft YaHei', sans-serif; line-height: 1.6; color: #333; }}
            .container {{ max-width: 600px; margin: 0 auto; padding: 20px; background-color: #f9f9f9; }}
            .header {{ background-color: #f8d7da; padding: 20px; border-radius: 5px; margin-bottom: 20px; text-align: center; }}
            .header h2 {{ margin: 0; color: #721c24; }}
            .content {{ background-color: white; padding: 20px; border-radius: 5px; }}
            table {{ width: 100%; border-collapse: collapse; margin: 20px 0; }}
            th {{ background-color: #f2f2f2; padding: 12px; border: 1px solid #ddd; text-align: center; font-weight: bold; }}
            .tip-box {{ background-color: #d1ecf1; padding: 15px; border-radius: 5px; border-left: 4px solid #0c5460; margin: 20px 0; }}
            .footer {{ margin-top: 30px; padding-top: 20px; border-top: 1px solid #ddd; font-size: 12px; color: #666; text-align: center; }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h2>⚠️ {metal_name}价格预警</h2>
            </div>

            <div class="content">
                <p>尊敬的用户，您好！</p>

                <p>系统检测到<strong style="color: #d9534f;">{metal_name}</strong>价格已触发预警条件，当前价格已达到或低于以下时间段的最低价：</p>

                <table>
                    <thead>
                        <tr>
                            <th>时间段</th>
                            <th>当前价格</th>
                            <th>区间最低价</th>
                        </tr>
                    </thead>
                    <tbody>
                        {alert_rows}
                    </tbody>
                </table>

                <div class="tip-box">
                    💡 <strong>提示：</strong>这可能是一个较好的购买时机，请您关注市场动态，结合自身情况做出决策。
                </div>

                <div class="footer">
                    <p>此邮件由黄金持仓追踪系统自动发送</p>
                    <p>发送时间：{now.strftime('%Y-%m-%d %H:%M:%S')}</p>
                </div>
            </div>
        </div>
    </body>
    </html>
    """

    # 创建邮件
    msg = MIMEMultipart('alternative')
    msg['From'] = formataddr((MAIL_CONFIG["sender_name"], MAIL_CONFIG["sender_email"]))
    msg['To'] = ", ".join(MAIL_CONFIG["recipients"])
    msg['Subject'] = f"{metal_name}价格预警：达到{periods}最低点"

    html_part = MIMEText(html_content, 'html', 'utf-8')
    msg.attach(html_part)

    # 发送邮件（关键修改：使用 as_bytes() 而不是 as_string()）
    try:
        server = smtplib.SMTP_SSL(
            MAIL_CONFIG["smtp_server"],
            MAIL_CONFIG["smtp_port"]
        )
        server.login(
            MAIL_CONFIG["sender_email"],
            MAIL_CONFIG["sender_password"]
        )
        # ===== 关键修改：使用 send_message() 方法 =====
        server.send_message(msg)
        # ===== 或者使用 sendmail() + as_bytes() =====
        # server.sendmail(
        #     MAIL_CONFIG["sender_email"],
        #     MAIL_CONFIG["recipients"],
        #     msg.as_bytes()  # 改为 as_bytes()
        # )
        server.quit()
        print(f"[{now}] ✓ 价格预警邮件已发送：{metal_name} - {periods}")

        # 记录发送时间（冷却期）
        cooldown_data[alert_key] = now
        ALERT_COOLDOWN_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(ALERT_COOLDOWN_FILE, "wb") as f:
            pickle.dump(cooldown_data, f)

    except Exception as e:
        print(f"[{now}] ✗ 邮件发送失败：{e}")
        import traceback
        traceback.print_exc()


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


@app.route("/test-email")
@login_required
def test_email_route():
    """测试邮件发送功能"""
    try:
        # 创建模拟预警数据
        test_alerts = [
            {"period": "7日", "current_price": 685.50, "min_price": 685.50},
            {"period": "15日", "current_price": 685.50, "min_price": 687.20}
        ]
        send_price_alert_email("gold", test_alerts)
        flash("测试邮件已发送，请检查收件箱！", "success")
    except Exception as e:
        flash(f"邮件发送失败：{str(e)}", "danger")

    return redirect(url_for("index"))


if __name__ == "__main__":
    instance_path = os.path.join(basedir, "instance")
    if not os.path.exists(instance_path):
        os.makedirs(instance_path)
    with app.app_context():
        db.create_all()
    app.run(debug=True, host="0.0.0.0", port=5000)
