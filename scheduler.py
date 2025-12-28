# scheduler.py (For Production Background Tasks - With Time Window and Randomized Interval)
import time
import os
from apscheduler.schedulers.background import BackgroundScheduler

# 从 app 模块导入所需的对象
from app import app, db, fetch_and_update_price


def run_job_with_context():
    """
    为后台任务提供Flask的应用上下文，确保能访问数据库和应用配置。
    """
    with app.app_context():
        fetch_and_update_price()


def main():
    # 确保 instance 目录存在
    basedir = os.path.abspath(os.path.dirname(__file__))
    instance_path = os.path.join(basedir, 'instance')
    if not os.path.exists(instance_path):
        os.makedirs(instance_path)
        print("Created instance folder.")

    # 初始化数据库 (如果不存在)
    with app.app_context():
        db.create_all()
        print("Database tables ensured.")

    print("Starting scheduler...")

    # 立即执行一次，确保启动时就有数据
    # 注意：如果是在夜间启动，这次初始任务也会执行
    print("Running initial scrape job...")
    try:
        run_job_with_context()
    except Exception as e:
        print(f"Initial job failed: {e}")

    # --- KEY CHANGE: Configure scheduler with a cron trigger for the time window ---
    # 创建并配置调度器
    scheduler = BackgroundScheduler(daemon=True, timezone='Asia/Shanghai') # 建议明确设置时区
    scheduler.add_job(
        func=run_job_with_context,
        trigger='cron',
        hour='8-21',        # 只在8点到21点之间触发 (覆盖8:00-21:59)
        minute='*/20',      # 每40分钟为一个基础触发周期
        jitter=1200         # 在基础周期上增加±20分钟 (1200秒) 的随机抖动
    )
    scheduler.start()

    print("Scheduler started. Jobs will run randomly every 20-60 minutes between 08:00 and 22:00.")
    print("This process will keep running. Press Ctrl+C to exit.")

    # 让主线程保持运行
    try:
        while True:
            time.sleep(3600)
    except (KeyboardInterrupt, SystemExit):
        print("Shutting down scheduler...")
        scheduler.shutdown()
        print("Scheduler shut down.")


if __name__ == '__main__':
    main()

