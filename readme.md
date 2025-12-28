---

### **项目部署文档：个人贵金属持仓追踪器 (Selenium版)**

#### 1. 项目概述

本项目是一个基于Flask和Selenium的个人贵金属投资追踪应用。它由两个核心部分组成：
1.  **Web应用 (`app.py`)**: 由Gunicorn运行，负责处理用户请求、展示行情数据和持仓信息。
2.  **后台抓取服务 (`scheduler.py`)**: 一个独立的Python进程，使用APScheduler定时调用Selenium，模拟浏览器抓取最新的金银价格并存入数据库。

这种架构实现了Web服务和后台任务的完全分离，确保了生产环境的稳定性和可扩展性。

#### 2. 环境要求 (Prerequisites)

-   **操作系统**: CentOS 7/8 或兼容的Linux发行版 (如AlmaLinux, Rocky Linux)。
-   **Python**: 3.10 或更高版本。
-   **工具**: `git`, `wget`, `unzip`。

#### 3. `requirements.txt` 文件

在您的项目根目录下，确保 `requirements.txt` 文件内容如下：

```text
# Flask and related
Flask==3.0.0
Flask-SQLAlchemy==3.1.1
SQLAlchemy==2.0.22
Jinja2==3.1.2

# Web Scraping & Automation (Switched to Selenium)
selenium==4.15.0

# Background Tasks
APScheduler==3.10.4

# HTTP Requests
requests==2.31.0
```

---

### **部署步骤 (Step-by-Step Guide)**

#### **第 1 步：获取代码并创建虚拟环境**

```bash
# 克隆您的项目 (如果需要)
# git clone [your-repo-url]
# cd [your-project-folder]

# 创建并激活Python虚拟环境
python3 -m venv .venv
source .venv/bin/activate
```

#### **第 2 步：安装Python依赖包**

```bash
pip install -r requirements.txt
```

#### **第 3 步：安装Selenium环境依赖 (核心步骤)**

这一步将在服务器上安装Selenium运行所需的浏览器和驱动程序。

1.  **安装 Google Chrome 浏览器**:
    ```bash
    # 下载官方的 .rpm 安装包
    wget https://dl.google.com/linux/direct/google-chrome-stable_current_x86_64.rpm
    
    # 使用 yum localinstall 来安装，它会自动处理所有系统依赖
    yum localinstall -y google-chrome-stable_current_x86_64.rpm
    
    # 清理下载的安装包
    rm google-chrome-stable_current_x86_64.rpm
    ```

2.  **验证 Chrome 安装**:
    ```bash
    which google-chrome
    # 预期输出: /usr/bin/google-chrome
    
    google-chrome --version
    # 记下版本号，例如: Google Chrome 143.0.7499.169
    ```

3.  **安装匹配的 ChromeDriver**:
    ChromeDriver的版本**必须**与Chrome浏览器的版本**主版本号一致**。

    a. **访问官方镜像站**: [Chrome for Testing availability](https://googlechromelabs.github.io/chrome-for-testing/)
    b. **找到匹配版本**: 根据上一步记下的版本号，找到对应的ChromeDriver下载链接。
    c. **下载、解压并安装**: (**请将下面的版本号替换为您自己的版本号**)
    ```bash
    # 示例：为 Chrome 143.0.7499.169 下载驱动
    wget https://storage.googleapis.com/chrome-for-testing-public/143.0.7499.169/linux64/chromedriver-linux64.zip
    
    # 解压
    unzip chromedriver-linux64.zip
    
    # 移动到系统的可执行路径中
    mv chromedriver-linux64/chromedriver /usr/local/bin/
    
    # 赋予执行权限
    chmod +x /usr/local/bin/chromedriver
    
    # 清理下载文件
    rm chromedriver-linux64.zip
    rm -rf chromedriver-linux64
    ```

4.  **验证 ChromeDriver 安装**:
    ```bash
    chromedriver --version
    # 预期输出的版本号应与您的Chrome版本匹配
    ```

#### **第 4 步：初始化数据库**

```bash
# 确保 instance 目录存在，并创建数据库表
flask init-db
```

#### **第 5 步：启动应用 (双进程)**

您需要启动两个独立的、长期运行的进程。

1.  **启动 Gunicorn Web 服务器 (处理用户访问)**:
    ```bash
    # 激活虚拟环境 (如果终端是新的)
    # source .venv/bin/activate
    
    nohup gunicorn --workers 3 --bind 0.0.0.0:5000 app:app &
    ```
    -   `--workers 3`: 启动3个工作进程处理请求，可根据服务器CPU核心数调整。
    -   `--bind 0.0.0.0:5000`: 监听服务器所有IP的5000端口。
    -   `nohup ... &`: 让服务在后台持续运行。

2.  **启动后台调度器服务 (执行定时抓取)**:
    ```bash
    nohup python -u scheduler.py >> scheduler.log 2>&1 &
    ```
    -   `python -u`: `-u`参数确保Python的`print`输出**不被缓冲**，日志会立即写入文件。
    -   `>> scheduler.log`: 将所有**正常输出**追加到 `scheduler.log` 文件。
    -   `2>&1`: 将所有**错误输出**也重定向到与正常输出相同的地方（即 `scheduler.log`）。

---

### **日常管理与维护**

#### **查看后台任务日志**

要实时监控Selenium抓取任务的运行情况，使用`tail`命令：
```bash
tail -f scheduler.log
```
按 `Ctrl+C` 退出监控，不会影响后台进程。

#### **查看Gunicorn日志**

Gunicorn的输出默认可能也在 `nohup.out` 文件中，或者您可以配置其日志路径。

#### **停止服务**

如果需要更新或停止服务，您需要分别停止两个进程。

1.  **找到进程ID (PID)**:
    ```bash
    # 查找 Gunicorn 进程
    ps aux | grep gunicorn
    
    # 查找调度器进程
    ps aux | grep scheduler.py
    ```

2.  **停止进程**:
    使用 `kill` 命令，并带上您找到的PID。
    ```bash
    # 示例:
    kill [gunicorn_master_process_pid]
    kill [scheduler_pid]
    ```
    
3. **新增字段**:
在 app.py 里修改模型类。
运行 flask db migrate -m "一句话说明你做了什么改动"。
运行 flask db upgrade。