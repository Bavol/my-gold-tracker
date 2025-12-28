# -*- coding: utf-8 -*-
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.utils import formataddr
from datetime import datetime


def send_test_email():
    # 邮箱配置（请替换为您的真实信息）
    smtp_server = "smtp.qq.com"
    smtp_port = 465
    sender_email = "1040001060@qq.com"  # ← 替换为您的QQ邮箱
    sender_password = "gezwtfwxnksubbjj"  # ← 替换为授权码
    recipients = ["2240912272@qq.com", "1040001060@qq.com"]

    # 创建邮件
    msg = MIMEMultipart('alternative')

    # 使用 formataddr 正确格式化发件人（符合 RFC5322 标准）
    msg['From'] = formataddr(("黄金持仓系统", sender_email))
    msg['To'] = ", ".join(recipients)
    msg['Subject'] = "测试邮件 - 黄金持仓追踪系统"

    # 邮件正文（HTML格式）
    html_content = """
    <html>
    <head>
        <meta charset="UTF-8">
    </head>
    <body style="font-family: Arial, sans-serif; padding: 20px;">
        <h2 style="color: #333;">✓ 邮件配置测试成功</h2>
        <p>这是一封测试邮件，如果您收到此邮件，说明邮件配置已成功！</p>
        <p style="background-color: #d1ecf1; padding: 10px; border-radius: 5px;">
            <strong>提示：</strong>您的黄金持仓追踪系统已准备就绪，价格预警功能正常工作。
        </p>
        <p style="color: #666; font-size: 12px;">发送时间：{}</p>
    </body>
    </html>
    """.format(datetime.now().strftime('%Y-%m-%d %H:%M:%S'))

    html_part = MIMEText(html_content, 'html', 'utf-8')
    msg.attach(html_part)

    # 发送邮件
    try:
        print("正在连接邮件服务器...")
        server = smtplib.SMTP_SSL(smtp_server, smtp_port)
        print("正在登录...")
        server.login(sender_email, sender_password)
        print("正在发送邮件...")
        server.sendmail(sender_email, recipients, msg.as_string())
        server.quit()
        print("✓ 测试邮件发送成功！请检查收件箱（包括垃圾邮件文件夹）。")
    except Exception as e:
        print(f"✗ 邮件发送失败：{e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    send_test_email()
