# ragflow 集成指南

本教程主要是是两部分

- 一、如何部署ragflow
- 二、如何在智控台配置ragflow接口

如果您对ragflow很熟悉，且已经部署了ragflow，可直接跳过第一部分，直接进入第二部分。但是如果你希望有人指导你部署ragflow，让它能够和`xiaozhi-esp32-server`共同使用`mysql`、`redis`基础服务，以减少资源成本，你需要从第一部分开始。

# 第一部分 如何部署ragflow
## 第一步， 确认mysql、redis是否可用

ragflow需要依赖`mysql`数据库。如果你之前已经部署`智控台`，说明你已经安装了`mysql`。你可以共用它。

你可以你试一下在宿主机使用`telnet`命令，看看能不能正常访问`mysql`的`3306`端口。
``` shell
telnet 127.0.0.1 3306

telnet 127.0.0.1 6379
```
如果能访问到`3306`端口和`6379`端口，请忽略以下的内容，直接进入第二步。

如果不能访问，你需要回忆一下，你的`mysql`是怎么安装的。

如果你的mysql是通过自己使用安装包安装的，说明你的`mysql`做了网络隔离。你可能先解决访问`mysql`的`3306`端口这个问题。

如果你`mysql`是通过本项目的`docker-compose_all.yml`安装的。你需要找一下你当时创建数据库的`docker-compose_all.yml`文件，修改以下的内容

修改前
``` yaml
  xiaozhi-esp32-server-db:
    ...
    networks:
      - default
    expose:
      - "3306:3306"
  xiaozhi-esp32-server-redis:
    ...
    expose:
      - 6379
```

修改后
``` yaml
  xiaozhi-esp32-server-db:
    ...
    networks:
      - default
    ports:
      - "3306:3306"
  xiaozhi-esp32-server-redis:
    ...
    ports:
      - "6379:6379"
```

注意是将`xiaozhi-esp32-server-db`和`xiaozhi-esp32-server-redis`下面的`expose`改成`ports`。改完后，需要重新启动。以下是重启mysql的命令：

``` shell
# 进入你docker-compose_all.yml所在的文件夹，例如我的是xiaozhi-server
cd xiaozhi-server
docker compose -f docker-compose_all.yml down
docker compose -f docker-compose.yml up -d
```

启动完后，在宿主机再使用`telnet`命令，看看能不能正常访问`mysql`的`3306`端口。
``` shell
telnet 127.0.0.1 3306

telnet 127.0.0.1 6379
```
正常来说这样就可以访问的了。

## 第二步， 创建数据库和表
如果你的宿主机，能正常访问mysql数据库，那就在mysql上创建一个名字为`rag_flow`的数据库和`rag_flow`用户，密码为`infini_rag_flow`。

``` sql
-- 创建数据库
CREATE DATABASE IF NOT EXISTS rag_flow CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

-- 创建用户并授权
CREATE USER IF NOT EXISTS 'rag_flow'@'%' IDENTIFIED BY 'infini_rag_flow';
GRANT ALL PRIVILEGES ON rag_flow.* TO 'rag_flow'@'%';

-- 刷新权限
FLUSH PRIVILEGES;
```

## 第三步， 下载ragflow项目

你需要在你电脑找一个文件夹，用来存放ragflow项目。例如我在`/home/system/xiaozhi`文件夹。

你可以使用`git`命令，将ragflow项目下载到这个文件夹，本教程使用的是`v0.25.6（最新版）`版本进行安装部署。
```
git clone https://ghfast.top/https://github.com/infiniflow/ragflow.git
cd ragflow
git checkout v0.25.6
```
下载完后，进入`docker`文件夹。
``` shell
cd docker
```
修改`ragflow/docker`文件夹下的`docker-compose.yml`文件，将`ragflow-cpu`和`ragflow-gpu`服务的`depends_on`配置去掉，用于解除`ragflow-cpu`服务对`mysql`的依赖。

这是修改前：
``` yaml
  ragflow-cpu:
    depends_on:
      mysql:
        condition: service_healthy
    profiles:
      - cpu
  ...
  ragflow-gpu:
    depends_on:
      mysql:
        condition: service_healthy
    profiles:
      - gpu
```
这是修改后：
``` yaml
  ragflow-cpu:
    profiles:
      - cpu
  ...
  ragflow-gpu:
    profiles:
      - gpu
```

接着，修改`ragflow/docker`文件夹下的`docker-compose-base.yml`文件，去掉`mysql`和`redis`的配置。

例如，删除前：
``` yaml
services:
  minio:
    image: quay.io/minio/minio:RELEASE.2025-06-13T11-33-47Z
    ...
  mysql:
    image: mysql:8.0
    ...
  redis:
    image: redis:6.2-alpine
    ...
```

删除后
``` yaml
services:
  minio:
    image: quay.io/minio/minio:RELEASE.2025-06-13T11-33-47Z
    ...
```
## 第四步，修改环境变量配置

编辑`ragflow/docker`文件夹下的`.env`文件,找到以下配置，逐个搜索，逐个修改！逐个搜索，逐个修改！

下面对于`.env`文件的修改，60%的人会忽略`MYSQL_USER`配置导致ragflow启动不成功，因此，需要强调三次：

强调第一次：如果你的`.env`文件如果没有`MYSQL_USER`配置，请在配置文件增加这项！

强调第二次：如果你的`.env`文件如果没有`MYSQL_USER`配置，请在配置文件增加这项！

强调第三次：如果你的`.env`文件如果没有`MYSQL_USER`配置，请在配置文件增加这项！

``` env
# 端口设置
SVR_WEB_HTTP_PORT=8008           # HTTP端口
SVR_WEB_HTTPS_PORT=8009          # HTTPS端口
# MySQL配置 - 修改为您本地MySQL的信息
MYSQL_HOST=host.docker.internal  # 使用host.docker.internal让容器访问主机服务
MYSQL_PORT=3306                  # 本地MySQL端口
MYSQL_USER=rag_flow              # 上面创建的用户名，如果没有这项就增加这一项
MYSQL_PASSWORD=infini_rag_flow   # 上面设置的密码
MYSQL_DBNAME=rag_flow            # 数据库名称

# Redis配置 - 修改为您本地Redis的信息
REDIS_HOST=host.docker.internal  # 使用host.docker.internal让容器访问主机服务
REDIS_PORT=6379                  # 本地Redis端口
REDIS_PASSWORD=123456                  # 如果你的Redis没有设置密码，就按这样子填写，否则填写密码
```

注意：

（1）windows环境下：redis的版本不能太低，建议使用最新版，最好设置密码。否则ragflow连接redis会报错，在搭建环境时使用的redis版本是Redis-x64-5.0.14.1。

（2）如果你的Redis没有设置密码，还要修改`ragflow/docker`文件夹下`service_conf.yaml.template`，将`infini_rag_flow`替换成空字符串。

修改前
``` shell
redis:
  db: 1
  password: '${REDIS_PASSWORD:-infini_rag_flow}'
  host: '${REDIS_HOST:-redis}:6379'
```
修改后
``` shell
redis:
  db: 1
  password: '${REDIS_PASSWORD:-}'
  host: '${REDIS_HOST:-redis}:6379'
```

## 第五步，启动ragflow服务
执行【启动】命令：
``` shell
docker-compose -f docker-compose.yml up -d
```
执行成功后，你可以使用`docker logs -n 20 -f docker-ragflow-cpu-1`命令，查看`docker-ragflow-cpu-1`服务的日志。
如果日志中没有报错，说明ragflow服务启动成功。


执行【停止】命令：
``` shell
docker-compose -f docker-compose.yml down
```


# Docker Windows 端口绑定报错解决方案（端口被系统禁止/占用）
## 报错信息
```
Error response from daemon: ports are not available: exposing port TCP 0.0.0.0:1200 -> 127.0.0.1:0: listen tcp 0.0.0.0:1200: bind: An attempt was made to access a socket in a way forbidden by its access permissions.
```

## 报错说明
该错误为 **Windows 环境下 Docker 端口异常**，并非单纯端口被进程占用，大概率是**端口被系统保留、权限不足、Hyper-V/WSL 端口限制**，系统禁止 Docker 绑定当前端口。

## 解决方案（按优先级执行）
### 一、方案一：直接更换端口（推荐，最简方案）
无需排查占用，直接修改宿主机映射端口，避开受限端口段。
可选空闲端口：`1201`、`1300`、`8080`、`8090`、`29000+` 高位端口。

示例修改：
原端口配置
```bash
-p 1200:1200
```
修改后配置
```bash
-p 1300:1200
```
修改完成后重新启动容器即可正常运行。

---

### 二、方案二：必须使用 1200 端口（完整修复流程）
#### 1. 排查端口占用进程
**以管理员身份**打开 CMD / PowerShell，执行端口查询命令：
```cmd
netstat -ano | findstr ":1200"
```
- 有输出：代表端口被其他进程占用，记录末尾的 `PID`；
  打开「任务管理器 → 详细信息」，找到对应 PID 并结束进程。
- 无输出：代表端口**未被进程占用**，属于系统保留端口，继续下一步。

#### 2. 释放 Windows 系统保留端口（Hyper-V/WSL 导致）
安装 WSL、Hyper-V 后，Windows 会自动保留部分端口段，Docker 无权限绑定，执行以下命令修复：

1. 查看系统已保留的 TCP 端口范围
```cmd
netsh int ipv4 show excludedportrange protocol=tcp
```
查看结果，确认 `1200` 在系统保留端口段内。

2. 停止 NAT 端口服务（管理员权限执行）

```angular2html
关键问题：**必须用「管理员身份」打开 PowerShell/CMD 才行**，普通身份就是报「系统错误5 拒绝访问」。

### 一、正确操作（管理员权限）
1. 左下角开始菜单 → 搜索 **PowerShell**
2. 右键 **Windows PowerShell** → **以管理员身份运行**（必须这步）
3. 在弹出的管理员窗口里执行：

```powershell
# 1. 停止WinNAT
net stop winnat

# 2. 手动把1200加入【管理员预留白名单】（带*，系统不会抢占）
netsh interface ipv4 add excludedportrange protocol=tcp startport=1200 numberofports=1 store=persistent

# 3. 重启WinNAT
net start winnat
```
提示「服务已成功停止」就对了。

之后启动你的 docker 容器（比如 ragflow、es 等），跑完再恢复：


### 二、为什么你会报错
- `net stop winnat` 是**系统级服务操作**，普通用户权限被 UAC 拦截。
- 即使你账号是管理员，**不右键“以管理员身份运行”= 还是普通权限**。

### 三、顺便查一下被占用端口（可选）
管理员 PowerShell 里跑：
```powershell
netsh interface ipv4 show excludedportrange protocol=tcp
```
能看到系统（Hyper-V/WSL/Docker）**偷偷保留的端口段**，你的 1208 很可能就在里面。

### 四、如果还是不让停（少见）
管理员 PowerShell 用 sc 命令：
```powershell
sc stop winnat
```
如果提示「依赖服务正在运行」，先把 Docker Desktop、WSL 全部关掉再试。

```

```cmd
net stop winnat
```

3. 重启 NAT 端口服务
```cmd
net start winnat
```

4. 重启 `Docker Desktop`，重新启动容器测试。

#### 3. 永久规避端口占用（长效方案）
修改项目内 `.env` 环境配置文件，将文件中的 `1200`、`1201` 等受限端口，修改为**高位空闲端口**（如 29000 以上）。

修改完成后，重启 Docker 镜像服务，即可永久解决该端口限制问题。










# 第五步，注册账号
你可以在浏览器中访问`http://127.0.0.1:8008`，点击`Sign Up`，注册一个账号【renalysis/renalysis】。

注册成功后，你可以点击`Sign In`，登录到ragflow服务。如果你想关闭ragflow服务的注册服务，不想让其他人注册账号，你可以在`ragflow/docker`文件夹下的`.env`文件中，将`REGISTER_ENABLED`配置项设置为`0`。

``` dotenv
REGISTER_ENABLED=0
```
修改后，重启启动ragflow服务。
``` shell
docker-compose -f docker-compose.yml down
docker-compose -f docker-compose.yml up -d
```

# 第六步，配置ragflow服务的模型
你可以在浏览器中访问`http://127.0.0.1:8008`，点击`Sign In`，登录到ragflow服务。点击页面右上角的`头像`，进入设置页面。

(1)首先，在左侧导航栏中，点击`模型供应商`，进入到模型配置页面。在右侧的`可选模型`搜索框下，选择`LLM`，在列表选择你使用的模型供应商，点击`添加`，输入你的密钥；

(2)然后，选择`TEXT EMBEDDING`，在列表选择你使用的模型供应商，点击`添加`，输入你的密钥。

(3)最后，刷新一下页面，分别点击`设置默认模型`列表的LLM和Embedding，选择你使用的模型即可。请确认你的密钥开通了相应的服务，比如我是用的Embedding模型是xxx供应商的，需要去这个供应商官网查看这个模型是否需要购买资源包才能使用。



# 第二部分 配置ragflow服务

# 第一步 登录ragflow服务 8008 是在.env文件中配置的访问端口
你可以在浏览器中访问`http://127.0.0.1:8008`，点击`Sign In`，登录到ragflow服务。

然后点击右上角的`头像`，进入设置页面。在左侧导航栏中，点击`API`功能，然后点击"API Key"按钮。出现一个弹框，

在弹框中，点击"Create new Key"按钮，生成一个API Key。复制这个`API Key`，你稍后会用到。

# 第二步 配置到智控台
确保你的智控台版本是`0.8.7`或以上。使用超级管理员账号登录到智控台。

首先，你要先开启知识库功能。在顶部导航栏中，点击`参数字典`，在下拉菜单中，点击`系统功能配置`页面。在页面上勾选`知识库`，点击`保存配置`。即可在导航栏看到`知识库`功能。

在顶部导航栏中，点击`模型配置`，在左侧导航栏中，点击`知识库`。在列表中找到`RAG_RAGFlow`，点击`编辑`按钮。

在`服务地址`中，填写`http://你的ragflow服务的局域网IP:8008`，例如我的ragflow服务的局域网IP是`192.168.1.100`，那么我就填写`http://192.168.1.100:8008`。

在`API密钥`中，填写之前复制的`API Key`。

最后点击保存按钮。

# 第二步 创建一个知识库
使用超级管理员账号登录到智控台。在顶部导航栏中，点击`知识库`，在列表左下脚，点击`新增`按钮。填写一个知识库的名字和描述。点击保存。

为了提高大模型对知识库的理解和召回能力，建议在创建知识库时，填写一个有意义的名字和描述。例如，如果你要创建一个关于`公司介绍`的知识库，那么知识库的名字可以是`公司介绍`，描述可以是`关于公司的相关信息例如公司基本信息、服务项目、联系电话、地址等。`。

保存后，你可以在知识库列表中看到这个知识库。点击刚才创建的知识库的`查看`按钮，进入知识库详情页面。

在知识库详情页面中，左下角点击`新增`按钮，可以上传文档到知识库。

上传后，你可以在知识库详情页面中，看到上传的文档。此时可以点击文档的`解析`按钮，解析文档。

解析完成后，你可以查看解析后的切片信息。你可以在知识库详情页面中，点击`召回测试`按钮，可以测试知识库的召回/检索功能。

# 第三步 让小智使用ragflow知识库
登录到智控台。在顶部导航栏中，点击`智能体`，找到你要配置的智能体，点击`配置角色`按钮。

在意图识别左侧，点击`编辑功能`按钮，弹出一个弹框。在弹框中选择你要添加的知识库。保存即可。




====================================================================================================


# 知识库启动过程中的问题
# docker  compose 启动时，报端口被占用，修改端口之后，还是被占用
```angular2html
PS D:\pythonWorkSpace\ragflow\docker> docker-compose -f docker-compose.yml up -d
[+] up 2/3
 ✔ Container docker-minio-1       Started                                                                                                                                                                                                                                 0.4s
 ✔ Container docker-ragflow-cpu-1 Started                                                                                                                                                                                                                                 0.5s
 - Container docker-es01-1        Starting                                                                                                                                                                                                                                0.5s
Error response from daemon: ports are not available: exposing port TCP 0.0.0.0:1208 -> 127.0.0.1:0: listen tcp 0.0.0.0:1208: bind: An attempt was made to access a socket in a way forbidden by its access permissions.

1208是更换之后的端口，还是被占用
```

先把结论说清楚：  
**1208 不一定有进程在“占用”，但它落在 Windows 的系统保留端口段里，所以 Docker 无权 bind，直接报权限错误。**

你现在这个错误：
```
listen tcp 0.0.0.0:1208: bind: An attempt was made to access a socket in a way forbidden by its access permissions.
```
就是典型的 **WinError 10013 / WSAEACCES**：  
**不是端口被占用，是系统不让你用这个端口。**

---

## 一、先确认：1208 是不是被系统保留
用管理员身份打开 PowerShell / CMD：
```cmd
netsh int ipv4 show excludedportrange protocol=tcp
```
你会看到一堆：
```
Start Port    End Port
1200          1299
...
```
只要 **1208 在任何一个 Start–End 区间内**，就是系统保留端口，**Docker 再怎么换都绑不上**。

---

## 二、为什么 1208 也不行？
Windows（尤其装了 Hyper-V / WSL2 / Docker Desktop）会自动保留一段端口，通常包含：
- 1024–1500 某段
- 或更大的动态端口区

这些端口：
- `netstat -ano` **查不到占用**
- 但任何普通程序（包括 Docker）都 **无权 bind**

---

## 三、立刻能用的解决办法（最简单有效）
### 方案 A：直接换一个“高位、安全”端口（推荐）
不要在 1024–2000 里反复试了，很容易撞保留段。

改 `docker-compose.yml` 里 es01 的端口：
```yaml
ports:
  - "29200:9200"
  - "29300:9300"
```
用 **29200、39200、49200** 这种高位，基本不会被保留。

然后：
```cmd
docker-compose down
docker-compose up -d
```

### 方案 B：查保留范围，避开它
```cmd
netsh int ipv4 show excludedportrange protocol=tcp
```
找到类似：
```
1200    1299
```
那你就 **不要用 1200–1299**，直接跳到 1300 以上或 2000 以上。

### 方案 C：管理员身份运行 Docker Desktop（可选）
- 完全关闭 Docker Desktop
- 右键 → **以管理员身份运行**
- 再 up 一次

有时能绕过部分权限限制，但不如换端口稳。

---

## 四、要不要查 1208 到底被谁用？
可以查，但大概率查不到：
```powershell
Get-NetTCPConnection -LocalPort 1208
netstat -ano | findstr :1208
```
**返回空 = 没有进程占用 = 就是系统保留**。

---

## 五、给你一套“避坑端口建议”
以后在 Windows 上给 Docker 映射，尽量选：
- **20000–29999**
- **30000–39999**
- **40000–49999**

避开：
- <1024（特权端口）
- 1024–2000（很容易被系统保留）

---
============================================================================

# 特别注意：
1. 修改配置文件的时候，原始的配置一定要被修改掉，不要漏修改，否则启动或使用会异常。
2. 修改了.env中的端口之后，记得在 /ragflow/conf/service_conf.yaml文件中同步修改


=============================================================================




# docker 运维命令
## 后端日志
docker-compose logs -f ragflow-cpu

## Nginx 日志
docker-compose logs -f ragflow-cpu | grep nginx

## ES 日志
docker-compose logs -f es01


======================================================================







# ragflow配置参考资料

---

1.[ragflow服务模型 可配置的免费的大语言模型LLM有哪些?](https://www.doubao.com/thread/w72d11630085b668a)

2.[LLM 通俗大白话介绍](https://www.doubao.com/thread/w3dcce8018d3da946)

3.[Windows安装Ollama](https://www.doubao.com/thread/w086ab2ca30d5dd09)

4.[ollama官网](https://ollama.com/download)

5.[128G内存的电脑 适合部署哪个qwen模型？](https://www.doubao.com/thread/w95419e07403508d2)


OllamaSetup的默认安装路径是C盘
6.[OllamaSetup安装路径如何自定义？](https://www.doubao.com/thread/w5b372f794ee2cc48)
"D:\软件\开发软件\OllamaSetup.exe" /DIR="D:\AI\Ollama"


7.[Windows Ollama常用命令](https://www.doubao.com/thread/w46fd03368a86b04c)
```
一句话总结
下载 = pull
运行 = run
看安装 = list
看运行 = ps
停止 = stop
删除 = rm
```


8.[RAGFlow web界面如何配置ollama](https://www.doubao.com/thread/wbaf17693f60b1551)



9.[ragflow文档解析报错 Task has been received. Page(1~9): [ERROR]Fail to bind embedding model: Model(@None) not authorized [ERROR][Exception]: Model(@None) not authorized](https://www.doubao.com/thread/we3cd77f6f1aeb162)
下载并安装Embedding向量模型
ollama pull nomic-embed-text



10.[RAGFlow Ollama Qwen 最大Token 标准答案](https://www.doubao.com/thread/wbcec37870dee8cbe)


11. [Qwen2.5:32b 与 Qwen2.5:14b 性能全面对比](https://www.doubao.com/thread/wa1144451403a2655)
12. https://feishu.doubao.com/docx/RH44dLktJocEqpxePkHcLZXnnMb?enter_from=public_link#
    【豆包 AI 文档】Qwen2.5:32b 与 Qwen2.5:14b 性能全面对比

13. [三款模型对比：Qwen3-8B、Qwen2.5-14B、Qwen2.5-32B](https://www.doubao.com/thread/w47113795db06b522)

14. [为什么qwen2.5:32b的延迟低于其他两个](https://www.doubao.com/thread/w641ec9bbdbb298ae)


15. [向量模型 Qwen3-Embedding + 重排模型 BGE-Large Reranker](https://www.doubao.com/thread/wee482c692bdb4a3e)

16.[重排模型qwen3-reranker-0.6b:q8_0](https://www.doubao.com/thread/w6a9050e065ad713e)


---





# ragflow web界面配置记录

# ragflow如何集成 Ollama


## 方式1：使用docker部署ollama

[【将ollama部署到docker，然后安装进入ollama安装大模型】](https://github.com/infiniflow/ragflow/blob/main/docs/guides/models/deploy_local_llm.mdx)

# Deploy Ollama using Docker

## docker中部署ollama
```angular2html


Ollama can be installed from binaries or deployed with Docker. Here are the instructions to deploy with Docker:

docker run --name ollama -p 11434:11434 ollama/ollama

docker run --name ollama -p 11435:11434 ollama/ollama

---------------------------------------------------------------------------------下面是启动日志-----------------------------------------------------------------------------------------
PS C:\Users\renalysis> docker run --name ollama -p 11435:11434 ollama/ollama
Couldn't find '/root/.ollama/id_ed25519'. Generating new private key.
Your new public key is:

ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAICL9oDWTEoH5urlhFXBrh5ESUSIaAMSjwfXNuEEzFXpM

time=2026-06-12T04:23:28.050Z level=INFO source=routes.go:1919 msg="server config" env="map[CUDA_VISIBLE_DEVICES: GGML_VK_VISIBLE_DEVICES: GPU_DEVICE_ORDINAL: HIP_VISIBLE_DEVICES: HSA_OVERRIDE_GFX_VERSION: HTTPS_PROXY: HTTP_PROXY: LLAMA_ARG_FIT: LLAMA_ARG_FIT_TARGET: NO_PROXY: OLLAMA_CONTEXT_LENGTH:0 OLLAMA_DEBUG:INFO OLLAMA_DEBUG_LOG_REQUESTS:false OLLAMA_EDITOR: OLLAMA_FLASH_ATTENTION:false OLLAMA_GO_TEMPLATE:true OLLAMA_GPU_OVERHEAD:0 OLLAMA_HOST:http://0.0.0.0:11434 OLLAMA_IGPU_ENABLE: OLLAMA_KEEP_ALIVE:5m0s OLLAMA_KV_CACHE_TYPE: OLLAMA_LLM_LIBRARY: OLLAMA_LOAD_TIMEOUT:5m0s OLLAMA_MAX_LOADED_MODELS:0 OLLAMA_MAX_QUEUE:512 OLLAMA_MAX_TRANSFER_STREAMS:4 OLLAMA_MODELS:/root/.ollama/models OLLAMA_NOHISTORY:false OLLAMA_NOPRUNE:false OLLAMA_NO_CLOUD:false OLLAMA_NUM_PARALLEL:1 OLLAMA_ORIGINS:[http://localhost https://localhost http://localhost:* https://localhost:* http://127.0.0.1 https://127.0.0.1 http://127.0.0.1:* https://127.0.0.1:* http://0.0.0.0 https://0.0.0.0 http://0.0.0.0:* https://0.0.0.0:* app://* file://* tauri://* vscode-webview://* vscode-file://*] OLLAMA_REMOTES:[ollama.com] OLLAMA_SCHED_SPREAD:false OLLAMA_VULKAN:true ROCR_VISIBLE_DEVICES: http_proxy: https_proxy: no_proxy:]"
time=2026-06-12T04:23:28.051Z level=INFO source=routes.go:1921 msg="Ollama cloud disabled: false"
time=2026-06-12T04:23:28.052Z level=INFO source=images.go:864 msg="total blobs: 0"
time=2026-06-12T04:23:28.052Z level=INFO source=images.go:871 msg="total unused blobs removed: 0"
time=2026-06-12T04:23:28.052Z level=INFO source=routes.go:1981 msg="Listening on [::]:11434 (version 0.30.7)"
time=2026-06-12T04:23:28.054Z level=INFO source=model_list_cache.go:111 msg="model list cache hydration complete" models=0 failures=0 elapsed=1.553127ms
time=2026-06-12T04:23:28.056Z level=INFO source=runner.go:60 msg="discovering available GPUs..."
time=2026-06-12T04:23:28.543Z level=INFO source=types.go:50 msg="inference compute" id=cpu library=cpu compute="" name=cpu description=cpu libdirs=ollama driver="" pci_id="" type="" total="15.4 GiB" available="15.3 GiB"
time=2026-06-12T04:23:28.543Z level=INFO source=routes.go:2031 msg="vram-based default context" total_vram="0 B" default_num_ctx=4096
time=2026-06-12T04:23:29.584Z level=INFO source=model_recommendations.go:177 msg="model recommendations cache sleep scheduled" wait=3h16m34.694058044s consecutive_failures=0
[GIN] 2026/06/12 - 04:27:03 | 200 |    1.759479ms |       127.0.0.1 | HEAD     "/"
time=2026-06-12T04:27:08.236Z level=INFO source=download.go:179 msg="downloading dde5aa3fc5ff in 16 126 MB part(s)"
[GIN] 2026/06/12 - 04:27:36 | 200 |       35.14µs |       127.0.0.1 | HEAD     "/"
time=2026-06-12T04:27:39.536Z level=INFO source=download.go:179 msg="downloading daec91ffb5dd in 12 100 MB part(s)"
--------------------------------------------------------------------------------------------------------------------------------------------------------------------------


netstat -ano | findstr 11434

netstat -ano | findstr 11435

ps aux | grep ollama

```

## 下载chat model 和 文本嵌入（Embedding）模型
> llama3.2 (a 3B chat model) and bge-m3 (a 567M embedding model)
> Pull models as you need. We recommend that you start with llama3.2 (a 3B chat model) and bge-m3 (a 567M embedding model):


````angular2html

docker exec ollama ollama pull llama3.2

docker exec ollama ollama pull bge-m3


````

### 状态总结
容器 **ollama** 启动成功，端口映射 `11435(宿主机) → 11434(容器内)` 生效，服务正常监听，当前仅使用CPU运行。

---
### 关键日志解读
1. **密钥生成**
   `Couldn't find '/root/.ollama/id_ed25519'`：容器首次启动自动生成SSH密钥，属于正常现象，无需处理。

2. **监听地址**
   `Listening on [::]:11434`：容器内Ollama 默认监听 `0.0.0.0:11434`，已放行外部访问。
   宿主机访问地址：
- 本机：`http://127.0.0.1:11435`
- 同局域网其他设备：`http://你的本机IP:11435`

3. **运行硬件**
   `inference compute id=cpu`：当前纯CPU推理，可用内存约15.3GiB，默认上下文窗口 `4096`。

---
### 常用操作（PowerShell）
#### 1. 验证端口监听
```powershell
netstat -ano | findstr 11435
```
能查到记录说明端口正常占用。

#### 2. 进入容器内部操作（拉取/管理模型）
```powershell
docker exec -it ollama /bin/sh

# 容器内执行 ollama 命令
ollama list
ollama pull bge-m3
ollama pull llama3.2:3b-instruct

```

#### 3. 后台运行容器（当前是前台，关窗口就停止）
先停止当前容器：
```powershell

docker stop ollama

```
重新后台启动（加 `-d`）：
```powershell

docker run -d --name ollama -p 11435:11434 ollama/ollama

```

#### 4. 测试接口连通性
```powershell
curl http://127.0.0.1:11435/api/tags
```
返回JSON列表即代表服务可用。

---
### 对接 RAGFlow 注意点
之前配置里的 `Base URL` 对应改为：
- 容器内RAGFlow访问Ollama：`http://host.docker.internal:11435`
- 宿主机本地访问：`http://127.0.0.1:11435`

-----------------------------------------------------------------------------------------------


## 方式2：只额吉使用本地安装的ollama

# RAGFlow web界面如何配置ollama
> 发布时间：2026-04-21
> 说明：内容由 AI 生成，不能完全保障真实，可直接按照步骤填写配置

## 一、前置必做（不做 100% 连不上）
### 1. 配置 Ollama 环境变量，放行 Docker 访问
1. 打开 **此电脑→属性→高级系统设置→环境变量**
2. 在**用户变量**中新建变量：
    - 变量名：`OLLAMA_HOST`
    - 变量值：`0.0.0.0`
3. 重启 Ollama 托盘服务。

### 2. 提前拉取所需模型
打开终端执行以下命令拉取模型：
```bash
ollama pull qwen2.5:32b
ollama pull nomic-embed-text
```

## 二、Web 界面一步步配置
1. 打开浏览器访问地址 `http://localhost:8080`，登录 RAGFlow。
2. 点击页面右上角头像，选择 **模型供应商 Model Providers**，找到 Ollama 并点击 **添加模型**。

### 1. 配置对话大模型 LLM（Qwen2.5:32b）
| 配置项 | 填写内容 |
| ---- | ---- |
| 模型类型 | `Chat` |
| 模型名称 | `qwen2.5:32b`（需和 `ollama list` 查询结果完全一致） |
| Base URL | `http://host.docker.internal:11434` |
| API Key | 自定义填写，示例：`ollama123` |
| 温度 | `0.15`（RAG 场景低幻觉最优值） |
| 最大 Token | `131072` |

配置完成后点击**测试连接**，连接成功后保存配置。

### 2. 配置向量嵌入 Embedding（必须配置）
| 配置项 | 填写内容 |
| ---- | ---- |
| 模型类型 | `Embedding` |
| 模型名称 | `nomic-embed-text` |
| Base URL | `http://host.docker.internal:11434` |
| API Key | `ollama123`（与上文保持一致） |

点击**测试连接**，连接成功后保存配置。

### 3. 设置全局默认模型（必设）
1. 回到页面右上角，设置默认模型。
2. 默认 LLM：`qwen2.5:32b`
3. 默认 Embedding：`nomic-embed-text`
4. 保存设置使其生效。

## 三、Docker Windows 关键地址口诀
- 宿主机本地访问 Ollama：`http://localhost:11434`
- Docker 容器访问宿主机 Ollama：`http://host.docker.internal:11434`

> 重要提醒：容器内 `localhost` 指向容器自身，**绝对不能填写 localhost**。

## 四、连接失败 90% 原因排查
1. 未配置环境变量 `OLLAMA_HOST=0.0.0.0`：会导致 Ollama 仅允许本机访问，容器无法连接。
2. URL 填写错误：误用 `localhost` 而非 `host.docker.internal`。
3. Ollama 服务未运行：执行 `ollama ps` 检查服务状态。
4. 防火墙拦截：放行 `11434` 端口即可。
5. 模型未下载：执行 `ollama list` 核对目标模型是否存在。

## 五、128G 内存最优全套参数
- LLM 模型：`qwen2.5:32b`（适配稳定 RAG 场景）
- Embedding 模型：`nomic-embed-text`
- 温度参数：`0.1~0.2`
- 上下文长度：128K


===================================================================================




# RAGFlow 内置分块类型 + 适配 BGE-M3 模型的分块方法

结合 **RAGFlow 内置分块类型** + 适配 **BGE-M3 模型（最大8192 tokens）**，针对你列出的 6 类文档（Q&A、简历、手册、表格、论文、书籍），给出**分块规则、参数、配置、适配方案**，直接在 RAGFlow 界面套用即可。

> 通用前置约束（统一适配 BGE-M3）
> - 单块上限：**最大 7680 tokens**（预留余量，避免截断）
> - 重叠值统一参考：**128 ~ 256 tokens**
> - 优先语义切分，不破坏原有结构；超长片段再用滑动窗口补切

---

# 一、RAGFlow 分块通用配置说明
RAGFlow 上传知识库时，**文本分段**可选模式：
1. 通用分段（字符/Token）
2. 语义分段（推荐，中文友好）
3. 自定义分隔符
4. 模型智能分段（消耗资源，复杂文档用）

下文统一给出：**推荐模式 + 块大小 + 重叠 + 分隔符 + 适配理由**

---



# 二、分场景详细方案

## 1. General 通用综合文档
### 文档特征
混合内容（段落、短句、少量标题/列表）、无固定格式、结构杂乱，是最常见的普通文本文档，语义衔接自由，边界不明确。

### 分块策略
**语义分段为主 + 滑动窗口兜底**，兼顾语义完整与长度限制，不刻意寻找特殊分隔符。
### 推荐配置
- 分段模式：**语义分段**（RAGFlow 首选）
- 块大小：`4096 ~ 6144 tokens`
- 重叠：`160 ~ 200 tokens`
### 核心规则
1. 优先按自然段落、空行、长句边界切割，避免割裂单段语义
2. 连续大段纯文本，自动启用滑动重叠分块
3. 零散短句、列表内容就近合并，不单独拆成过小碎片
4. 全文整体长度不足阈值则**完整保留**

### 适配 BGE-M3
通用文本语义多样，结合稠密向量理解整体语义、稀疏向量匹配关键词，综合检索效果均衡。

### 避坑
不要使用纯固定字符硬切割，极易打断语句逻辑。

---

## 2. Q&A 问答文档
### 文档特征
一问一答、结构固定、每条独立语义，关联性弱。
### 分块策略
**按问答组为最小单元，禁止拆分单条 Q&A**
### 推荐配置
- 分段模式：**语义分段 / 自定义分隔符**
- 主分隔符：`Q:`、`A:`、`问题：`、`答案：`
- 块大小：**2000 ~ 3000 tokens**
- 重叠：**64 ~ 128 tokens**
- 单块规则：
    1. 单条 Q&A 整体保留，不切割
    2. 多条连续问答合并至接近上限再分块
### 适配 BGE-M3
块偏小，检索精准，稠密+稀疏向量匹配关键词效果极佳。
### 避坑
不要按固定字符硬切，极易把「问题」和「答案」拆分开。

---

## 3. Resume 简历
### 文档特征
结构化强：个人信息、工作经历、项目、技能、教育经历，**板块边界清晰**。
### 分块策略
**按大板块切分**（工作经历/项目经历各自成块）
### 推荐配置
- 分段模式：**语义分段**
- 块大小：**2500 ~ 4096 tokens**
- 重叠：**128 tokens**
- 天然分隔点：标题、空行、章节换行
### 适配 BGE-M3
简历关键词密集，BGE-M3 稀疏向量可精准匹配岗位/技能关键词。
### 建议
项目经历多的长简历，在板块内启用**滑动重叠分块**。

---

## 5. Manual 操作手册 / 使用说明书
### 文档特征
层级标题（章节→小节→步骤）、流程化内容、指令类文本，长段落多。
### 分块策略
**按标题层级切分**，同章节内容合并，不跨大章节。
### 推荐配置
- 分段模式：**语义分段 + 层级标题优先**
- 块大小：**4096 ~ 6144 tokens**
- 重叠：**200 ~ 256 tokens**
- 分隔符：一级标题、二级标题、空行
### 适配 BGE-M3
手册常含长流程，7680 以内大块可完整保留操作逻辑，检索上下文完整。
### 避坑
禁止把「前置条件 + 操作步骤 + 注意事项」拆成多块。

---

## 5. Table 纯表格文档
### 文档特征
行列结构化数据、条目化、关联性强，**行/列不能拆分**。
### 分块策略
**按行组/逻辑表格单元切分**，整张小表作为一个块；大表按连续行分组。
### 推荐配置
- 分段模式：**自定义分隔符 / 固定行分组**
- 块大小：**3000 ~ 4096 tokens**
- 重叠：**128 tokens**
- 规则：
    1. 单张小表格 → 整块入库
    2. 超长表格 → 按「连续N行」分组，组间少量重叠
### 适配 BGE-M3
表格文本短、关键词集中，BGE-M3 稀疏检索命中率极高。
### 重要提醒
RAGFlow 识别表格建议先开启 **OCR 解析表格**，再分块。

---

## 6. Paper 学术论文
### 文档特征
摘要、引言、实验、结论、参考文献，长段落、专业术语、逻辑连贯。
### 分块策略
**按章节强边界切分**，同一章节内部长文本启用滑动窗口。
### 推荐配置
- 分段模式：**语义分段（首选）**
- 块大小：**6144 ~ 7680 tokens（拉满 BGE-M3 上限）**
- 重叠：**256 tokens（最大重叠）**
- 分隔点：章节标题、摘要、结论、参考文献分隔线
### 适配 BGE-M3
论文逻辑长依赖，用接近上限块大小保证论证完整；多向量模式提升长文本语义匹配。
### 规则
参考文献统一单独分块，不和正文混合。

---

## 7. Book 完整书籍 / 长篇著作
### 文档特征
超大篇幅、多级目录、章节连贯、上下文强依赖，属于超长文本。
### 分块策略
**三级分层切分：书籍 → 篇章 → 章节 + 滑动重叠**
### 推荐配置
- 分段模式：**语义分段 + 滑动窗口混合**
- 块大小：**6144 ~ 7680 tokens**
- 重叠：**256 tokens**
- 分层规则：
    1. 以「章节」为第一分割单元
    2. 单章节超长 → 内部滑动切分（保留重叠）
    3. 序言、目录、后记单独分块
### 适配 BGE-M3
充分利用 8192 长上下文能力，大块保留剧情/论述连贯性，检索体验最好。
### 优化
书籍优先开启 BGE-M3 **MCLS 多池化**，长块检索效果大幅提升。

---


## 8. Laws 法律法规/规章条文
### 文档特征
层级严谨（编/章/节/条/款/项）、句式固定、条文具备强独立性，条款编号是天然分割符，严禁拆分单条法规。

### 分块策略
以**法条编号**为核心分割单元，同章节条文合并，单条超长条文内部做滑动切分。
### 推荐配置
- 分段模式：**自定义分隔符 + 语义分段**
- 块大小：`3000 ~ 4096 tokens`
- 重叠：`128 tokens`
- 自定义分隔符：`第X条、第X款、第X项、§` 等编号标识
### 核心规则
1. 单条法条**完整保留**，不割裂条款内容
2. 多条连续同主题法条合并为一个块
3. 超长释义/附则，在条款边界内做滑动重叠分块
### 适配 BGE-M3
法规关键词、专有名词密集，BGE-M3 稀疏向量可精准匹配法条、关键字，检索准确率高。
### 避坑
不要按纯字符切割，防止一条法规被拆分为多个碎片。

---

## 9. Presentation 演示文稿（PPT/演讲稿）
### 文档特征
每页独立主题、图文结合、要点化表达、层级标题多，单页内容语义完整，页与页之间相对独立。

### 分块策略
**单页为基础单元**，内容少的相邻页面合并，内容极多的单页内部二次切分。
### 推荐配置
- 分段模式：**语义分段**
- 块大小：`2500 ~ 4096 tokens`
- 重叠：`64 ~ 128 tokens`
- 天然分隔点：分页标记、幻灯片标题、大标题、空行
### 核心规则
1. 单页内容优先整体作为一个块
2. 连续多页同主题内容，合并至块大小上限
3. 大篇幅演讲稿/逐字稿，启用滑动窗口切分
### 适配 BGE-M3
要点短句居多，稠密向量匹配语义、稀疏向量匹配关键词，兼顾整体意图与重点词汇检索。

---

## 10. One 零散短文/单篇文本（随笔、公告、短通知、单篇正文）
### 文档特征
无复杂层级、篇幅不长、语义完整独立，无明显分割边界，全文逻辑连贯。

### 分块策略
完整优先，超长文本使用**标准滑动窗口重叠分块**。
### 推荐配置
- 分段模式：**通用 Token 分段 / 滑动分段**
- 块大小：`4096 ~ 6144 tokens`
- 重叠：`128 ~ 200 tokens`
### 核心规则
1. 全文长度＜块上限：**整块入库，不拆分**
2. 超长单文本，仅使用滑动窗口切分，不强行按标点割裂
### 适配 BGE-M3
充分利用模型长上下文能力，完整文本向量表征更精准。

---

## 11. Tag 标签类文本（标签集合、分类词条、关键词库、标签说明）
### 文档特征
条目化、短文本居多，标签+简短释义组合，条目独立，关键词高度集中。

### 分块策略
按**标签组**聚合分块，单个标签/释义不拆分。
### 推荐配置
- 分段模式：**自定义分隔符**
- 块大小：`2000 ~ 3000 tokens`
- 重叠：`64 tokens`
- 自定义分隔符：换行、逗号、顿号、标签前缀
### 核心规则
1. 单个标签+配套释义作为最小单元
2. 批量标签按数量聚合，凑至块大小上限再分割
3. 分类目录与对应标签绑定在同一块内
### 适配 BGE-M3
极度适配稀疏检索能力，标签关键词可以被快速命中，检索响应快、精度高。

---


## 完整汇总表（全11类）
| 文档类型 | 推荐块大小(tokens) | 重叠(tokens) | 首选分段模式 | 核心切分规则 |
|--------|--------------------|--------------|-------------|------------|
| Q&A 问答 | 2000~3000 | 64~128 | 自定义分隔符 | 不拆分单条问答 |
| Resume 简历 | 2500~4096 | 128 | 语义分段 | 按经历/技能板块切分 |
| Manual 手册 | 4096~6144 | 200~256 | 语义分段 | 按标题层级切分 |
| Table 表格 | 3000~4096 | 128 | 自定义/行分组 | 表格单元、行组不拆分 |
| Paper 论文 | 6144~7680 | 256 | 语义分段 | 按章节拆分 |
| Book 书籍 | 6144~7680 | 256 | 语义+滑动窗口 | 以章节为单元 |
| Laws 法规 | 3000~4096 | 128 | 自定义+语义分段 | 法条编号为分割依据，单条完整保留 |
| Presentation 演示文稿 | 2500~4096 | 64~128 | 语义分段 | 以单页幻灯片为基础单元 |
| One 零散单文本 | 4096~6144 | 128~200 | Token/滑动分段 | 短文整块保留，长文本滑动切分 |
| Tag 标签库 | 2000~3000 | 64 | 自定义分隔符 | 标签+释义为最小单元，分组聚合 |
| General 通用文档 | 4096~6144 | 160~200 | 语义分段 | 按自然段落切割，长文本滑动兜底 |

---

# 三、汇总速查表（RAGFlow 直接照填）
| 文档类型 | 推荐块大小(tokens) | 重叠(tokens) | 首选分段模式 | 核心切分规则 |
|--------|--------------------|--------------|-------------|------------|
| Q&A 问答 | 2000~3000 | 64~128 | 自定义分隔符 | 不拆分单条问答 |
| Resume 简历 | 2500~4096 | 128 | 语义分段 | 按板块（经历/技能）切 |
| Manual 手册 | 4096~6144 | 200~256 | 语义分段 | 按标题层级切 |
| Table 表格 | 3000~4096 | 128 | 自定义/行分组 | 表格整体/行组不拆分 |
| Paper 论文 | 6144~7680 | 256 | 语义分段 | 按章节拆分 |
| Book 书籍 | 6144~7680 | 256 | 语义+滑动窗口 | 章节为单元，超长内部滑动 |

---

# 四、RAGFlow + BGE-M3 配套全局最优设置
1. 嵌入模型：`bge-m3`
2. 分块最大 Token：**7680**（全局上限，不碰 8192）
3. 全局默认重叠：**200 tokens**
4. 检索策略：开启 **稠密+稀疏混合检索**（BGE-M3 核心能力）
5. 长文档一律开启：**多向量检索 / MCLS**

---

# 五、补充小技巧
1. 全类型文档**优先语义分段**，比纯字符切割效果高 30%+
2. 中文场景不要用英文分词规则
3. 上传前：PDF/图片类文档先做 **OCR 解析** 再分块
4. 若出现召回残缺：**加大重叠值** 是最有效的解决方案


## 配套全局优化（延续之前方案）
1. 嵌入模型固定：`bge-m3`，全局单块上限 **7680 tokens**
2. 检索配置：开启**稠密+稀疏混合检索**，长文档开启多向量/MCLS
3. 统一原则：结构化文档优先语义/自定义分隔，纯长文本优先滑动窗口


============================================================================

# RAGFlow + Ollama(Docker) + BGE-M3 + Llama3.2 知识库专属智能体模板
结合你当前 **RAGFlow + Ollama(Docker) + BGE-M3 + Llama3.2** 技术栈，整理**知识库专属智能体模板**，区分**基础问答、多轮对话、文档解析、专业场景（法规/论文/手册）、混合检索增强**五类，可直接在 RAGFlow 「智能体/提示词模板」中复制使用，同时附带配置说明、参数搭配和使用技巧。

> 前置说明
> 1. RAGFlow 模板支持变量：`{question}` 用户问题、`{context}` 知识库召回内容、`{history}` 对话历史
> 2. 适配模型：Llama3.2-1B/3B-Instruct、通用对话LLM
> 3. 配套分块：沿用之前各类文档分块规则，BGE-M3 混合检索

---

# 一、通用基础问答模板（默认首选，全文档通用）
适用：General通用文档、通知、短文、普通知识库
## 模板内容
```
你是专业知识库问答助手，请严格基于下方【参考资料】回答用户问题。
### 参考资料
{context}

### 对话历史
{history}

### 用户问题
{question}

要求：
1. 仅使用参考资料内信息作答，资料无相关内容直接回复：“当前知识库中未查询到相关信息”，禁止编造内容。
2. 回答简洁通顺，逻辑清晰，优先提炼核心要点。
3. 不要额外拓展无关内容，不猜测、不联想。
```

## 配套参数
- 温度 `temperature`：0.1~0.2
- 最大生成长度：2048
- 适用文档：General、One、Tag

---

# 二、多轮对话增强模板（支持上下文记忆）
适用：持续问答、连续追问、Q&A 问答库、客服类知识库
## 模板内容
```
你是智能问答助手，结合历史对话与知识库内容，连贯回答用户问题。
### 知识库参考内容
{context}

### 历史对话记录
{history}

### 当前问题
{question}

作答规则：
1. 结合上文对话+参考资料综合回答，保持回答前后一致。
2. 参考资料无对应信息，如实告知，严禁杜撰。
3. 回答口语化、易懂，分点展示长答案，提升可读性。
4. 不重复历史对话中已回答过的冗余内容。
```

## 配套参数
- 温度：0.2~0.3
- 最大生成长度：3072
- 适用文档：Q&A、Manual手册、Presentation

---

# 三、结构化文档专用模板（表格/简历/标签）
适用：Table表格、Resume简历、Tag标签库，侧重**精准提取、结构化输出**
## 模板内容
```
你是信息提取助手，请从参考资料中精准提取结构化信息，回答用户问题。
### 参考资料
{context}

### 用户问题
{question}

要求：
1. 针对表格、条目、标签、简历类内容，优先整理成列表/表格形式展示。
2. 只提取原文存在的信息，不补充、不美化。
3. 关键词、数据、编号、名称必须与原文完全一致。
4. 无匹配信息直接说明，不要模糊回答。
```

## 配套参数
- 温度：0.1（极低，保证信息准确）
- 最大生成长度：2048
- 适用文档：Table、Resume、Tag

---

# 四、专业正式文档模板（法规/论文/书籍）
## 4.1 Laws 法律法规/规章
适用：法条、制度、规范、红头文件，要求严谨、原文引用
```
你是法规解读助手，严格依据提供的法条内容作答，表述严谨规范。
### 法规原文
{context}

### 用户问题
{question}

规则：
1. 引用条款时标注对应条目/编号，内容与原文保持一致。
2. 解读客观中立，不主观解读、不引申释义。
3. 多条内容分条罗列，条理清晰。
4. 知识库无相关法条，明确告知无法查询。
```

## 4.2 Paper 学术论文 / Book 书籍
适用：论文、专著、技术书籍，支持摘要、观点、论据梳理
```
你是文献分析助手，请基于下方文献内容解答问题、梳理观点。
### 文献内容
{context}

### 对话历史
{history}

### 用户问题
{question}

要求：
1. 提炼核心观点、研究结论、关键论据，忠于原文。
2. 长内容可分段总结，复杂逻辑分层说明。
3. 专业术语保留原文写法，不随意改写。
4. 超出文献范围的内容，明确说明。
```

## 配套参数（法规/论文/书籍）
- 温度：0.1~0.15
- 最大生成长度：4096
- 开启：长文本兼容模式

---

# 五、操作手册/PPT 演示文稿模板（步骤/流程类）
适用：Manual操作手册、Presentation演讲稿、教程类文档，侧重**步骤、流程、操作指引**
```
你是操作指引助手，根据参考资料为用户解答操作、流程、使用相关问题。
### 参考资料
{context}

### 用户问题
{question}

作答要求：
1. 涉及操作步骤、流程、配置，请按顺序分点列出，步骤清晰。
2. 重点操作、注意事项单独标注提醒。
3. 语言通俗，适合实操参考，简化专业术语。
4. 资料中无对应流程/操作，直接说明。
```

## 配套参数
- 温度：0.2
- 最大生成长度：3072

---

# 六、高阶：BGE-M3混合检索专属增强模板（推荐生产使用）
结合稠密+稀疏检索结果，**融合多片段内容、解决长文档碎片化问题**，全类型通用，最优搭配你的 BGE-M3 模型。
```
你是基于本地知识库的全能问答助手，本次检索融合了语义匹配与关键词匹配结果，请整合多段参考内容统一作答。
### 知识库检索内容（多片段）
{context}

### 历史对话
{history}

### 用户提问
{question}

统一规范：
1. 整合所有参考片段，去重、合并重复内容，形成完整答案。
2. 严格限定范围，只使用检索到的内容，绝不编造外部信息。
3. 根据文档类型适配风格：法规严谨、手册分步、论文总结、表格结构化。
4. 若多个片段信息冲突，以完整原文片段为准，并如实说明。
5. 无有效信息时，固定回复：暂未在知识库中找到相关内容。
```

---

# 七、RAGFlow 模板使用全流程
## 1. 入口位置
知识库 → 对应数据集 → **设置** → **提示词模板** / 智能体配置 → 粘贴对应模板

## 2. 全局通用配置（搭配 Llama3.2）
| 模型参数 | 推荐值 | 说明 |
| ---- | ---- | ---- |
| temperature | 0.1~0.3 | 专业文档取0.1，闲聊/多轮取0.3 |
| top_p | 0.7 | 通用默认值 |
| repetition_penalty | 1.05 | 减少重复话术 |
| 召回条数(top-k) | 4~8 | BGE-M3混合检索建议6条 |

## 3. 模板选用速查表（对应你所有文档类型）
| 文档类型 | 优先使用模板 |
| ---- | ---- |
| Q&A | 多轮对话模板 |
| Resume 简历 | 结构化文档模板 |
| Manual 手册 | 操作指引模板 |
| Table 表格 | 结构化文档模板 |
| Paper 论文 | 学术文献模板 |
| Book 书籍 | 学术文献模板 |
| Laws 法规 | 法规专用模板 |
| Presentation PPT | 操作指引模板 |
| One 单篇短文 | 基础问答模板 |
| Tag 标签库 | 结构化文档模板 |
| General 通用文档 | 基础问答 / 高阶混合检索模板 |

---

# 八、常见问题优化技巧
1. **回答内容不全**
    - 提高召回条数(top-k)，使用「高阶混合检索模板」整合多片段
2. **模型乱编内容**
    - 温度调低至 `0.1`，模板强化“禁止编造”约束
3. **步骤/法条顺序混乱**
    - 切换对应专项模板（手册/法规），关闭自由发挥
4. **多轮追问上下文丢失**
    - 启用「多轮对话模板」，保证 `{history}` 变量正常开启
---

==============================================================


# RAGFlow 智能体模板 JSON 标准结构（适配 Llama3.2 + BGE-M3）

结合 RAGFlow 智能体模板 **JSON 标准结构**、前文分类与 Prompt 内容，为每类文档输出可直接导入/粘贴使用的完整 JSON 模板，同时标注字段含义、配套推理参数，适配 `Llama3.2 + BGE-M3` 整套栈。

> 前置说明
> 1. RAGFlow 智能体模板 JSON 核心字段：`name`(模板名)、`prompt`(提示词主体)、`variables`(内置变量)、`llm_config`(模型推理参数)
> 2. 内置变量固定：`{question}` 用户问题、`{context}` 知识库上下文、`{history}` 对话历史
> 3. 所有模板已按文档场景优化 `temperature`/`max_tokens` 等参数，开箱即用

---

## 通用字段说明
```json
{
  "name": "模板名称",
  "desc": "模板用途描述",
  "prompt": "完整提示词文本",
  "variables": ["question", "context", "history"],
  "llm_config": {
    "temperature": 0.1,
    "top_p": 0.7,
    "max_tokens": 2048,
    "repetition_penalty": 1.05,
    "stream": true
  }
}
```
- `variables`：RAGFlow 固定变量，全部保留 `question/context/history`
- `stream`：默认开启流式输出，适配前端交互

---

# 1. Q&A 问答文档 模板
适用：问答库、客服问答、一问一答类资料
```json
{
  "name": "Q&A问答专用模板",
  "desc": "适配问答型知识库，支持多轮对话，不拆分问答单元",
  "prompt": "你是专业问答助手，请结合历史对话与知识库参考内容回答用户问题。\n### 知识库参考内容\n{context}\n\n### 历史对话记录\n{history}\n\n### 当前用户问题\n{question}\n\n作答规则：\n1. 严格依据参考资料作答，禁止编造、联想、拓展外部内容。\n2. 保持问答语义完整，不割裂原有问答结构。\n3. 回答通俗易懂，长内容分点展示，精简冗余信息。\n4. 知识库无相关内容，统一回复：当前知识库中未查询到相关信息。",
  "variables": ["question", "context", "history"],
  "llm_config": {
    "temperature": 0.25,
    "top_p": 0.7,
    "max_tokens": 3072,
    "repetition_penalty": 1.05,
    "stream": true
  }
}
```

---

# 2. Resume 简历模板
适用：简历、人员档案、履历信息提取
```json
{
  "name": "简历信息提取模板",
  "desc": "结构化提取简历、履历信息，保证关键词与原文一致",
  "prompt": "你是简历信息提取助手，仅从参考资料中精准提取信息并回答问题。\n### 参考资料\n{context}\n\n### 用户问题\n{question}\n\n要求：\n1. 优先使用列表、条目形式整理信息，结构清晰。\n2. 姓名、岗位、技能、工作经历、时间等内容严格与原文保持一致。\n3. 不主观美化、不补充额外内容，只做信息提取。\n4. 无匹配信息直接告知：未查询到对应简历信息。",
  "variables": ["question", "context", "history"],
  "llm_config": {
    "temperature": 0.1,
    "top_p": 0.7,
    "max_tokens": 2048,
    "repetition_penalty": 1.05,
    "stream": true
  }
}
```

---

# 3. Manual 操作手册模板
适用：使用手册、运维文档、教程、操作流程
```json
{
  "name": "操作手册指引模板",
  "desc": "适配操作手册、教程类文档，按步骤输出操作流程",
  "prompt": "你是操作指引助手，根据知识库内容解答使用、配置、操作相关问题。\n### 参考资料\n{context}\n\n### 用户问题\n{question}\n\n作答要求：\n1. 涉及操作步骤、流程、配置，请按先后顺序分点列出。\n2. 关键步骤、注意事项重点说明，逻辑连贯。\n3. 语言通俗，贴合实操场景，简化复杂专业术语。\n4. 资料无对应内容，直接说明：暂无相关操作指引。",
  "variables": ["question", "context", "history"],
  "llm_config": {
    "temperature": 0.2,
    "top_p": 0.7,
    "max_tokens": 3072,
    "repetition_penalty": 1.05,
    "stream": true
  }
}
```

---

# 4. Table 表格文档模板
适用：数据表、清单、统计表格、结构化表单
```json
{
  "name": "表格数据解析模板",
  "desc": "解析表格类文档，结构化提取行列数据",
  "prompt": "你是表格数据解析助手，基于表格内容提取数据并回答问题。\n### 参考资料\n{context}\n\n### 用户问题\n{question}\n\n规则：\n1. 优先以列表/简易表格形式展示数据，行列信息不篡改。\n2. 数字、编号、名称、状态等内容完全沿用原文。\n3. 不合并、不脑补表格以外的信息。\n4. 未查询到对应数据，请如实告知。",
  "variables": ["question", "context", "history"],
  "llm_config": {
    "temperature": 0.1,
    "top_p": 0.7,
    "max_tokens": 2048,
    "repetition_penalty": 1.05,
    "stream": true
  }
}
```

---

# 5. Paper 学术论文模板
适用：期刊论文、研究报告、学术文献
```json
{
  "name": "学术论文解读模板",
  "desc": "梳理论文观点、结论、论据，忠于原文学术内容",
  "prompt": "你是文献分析助手，基于论文内容解答问题、梳理核心观点。\n### 文献内容\n{context}\n\n### 历史对话\n{history}\n\n### 用户问题\n{question}\n\n要求：\n1. 提炼研究目的、实验过程、核心结论、关键论据。\n2. 专业术语、公式、数据保留原文写法，不随意修改。\n3. 长内容分段分层说明，逻辑严谨。\n4. 超出文献范围的内容，明确说明无法解答。",
  "variables": ["question", "context", "history"],
  "llm_config": {
    "temperature": 0.15,
    "top_p": 0.7,
    "max_tokens": 4096,
    "repetition_penalty": 1.05,
    "stream": true
  }
}
```

---

# 6. Book 书籍模板
适用：完整书籍、长篇专著、系列读物
```json
{
  "name": "书籍内容问答模板",
  "desc": "适配长篇书籍、专著，整合多章节内容作答",
  "prompt": "你是书籍解读助手，结合知识库中的书籍内容回答用户问题。\n### 书籍内容\n{context}\n\n### 历史对话\n{history}\n\n### 用户问题\n{question}\n\n作答规范：\n1. 整合多章节片段内容，去重合并，保证上下文连贯。\n2. 忠于原著内容，不改编剧情、观点与描述。\n3. 内容较多时分段阐述，条理清晰。\n4. 书中无相关内容，统一回复：当前书籍资料中未找到对应内容。",
  "variables": ["question", "context", "history"],
  "llm_config": {
    "temperature": 0.15,
    "top_p": 0.7,
    "max_tokens": 4096,
    "repetition_penalty": 1.05,
    "stream": true
  }
}
```

---

# 7. Laws 法律法规模板
适用：法条、规章制度、行政规范、红头文件
```json
{
  "name": "法律法规专用模板",
  "desc": "法规条文解读，严谨引用条款编号与原文",
  "prompt": "你是法规解读助手，严格依据法条原文作答，表述正式严谨。\n### 法规原文\n{context}\n\n### 用户问题\n{question}\n\n规则：\n1. 引用内容必须标注条款、条目编号，原文内容一字不改。\n2. 客观解读，不做主观引申、扩大解释。\n3. 多条法规分条罗列，格式规范。\n4. 未检索到相关法条，直接告知暂无对应法规内容。",
  "variables": ["question", "context", "history"],
  "llm_config": {
    "temperature": 0.1,
    "top_p": 0.7,
    "max_tokens": 3072,
    "repetition_penalty": 1.05,
    "stream": true
  }
}
```

---

# 8. Presentation 演示文稿(PPT)模板
适用：PPT、演讲稿、会议课件、宣讲材料
```json
{
  "name": "PPT演示文稿模板",
  "desc": "适配幻灯片、演讲稿，提炼要点与核心内容",
  "prompt": "你是课件解读助手，根据PPT/演讲稿内容回答用户问题。\n### 参考内容\n{context}\n\n### 用户问题\n{question}\n\n要求：\n1. 优先提炼页面核心要点、关键信息，精简冗余话术。\n2. 涉及流程、观点按逻辑顺序梳理。\n3. 语言简洁干练，贴合宣讲场景。\n4. 无相关内容请明确说明。",
  "variables": ["question", "context", "history"],
  "llm_config": {
    "temperature": 0.2,
    "top_p": 0.7,
    "max_tokens": 2560,
    "repetition_penalty": 1.05,
    "stream": true
  }
}
```

---

# 9. One 单篇短文模板
适用：通知、公告、随笔、独立短文本
```json
{
  "name": "单篇短文通用模板",
  "desc": "适配独立短文、公告、通知等单篇完整文本",
  "prompt": "你是文本问答助手，基于下方参考内容回答用户问题。\n### 参考内容\n{context}\n\n### 历史对话\n{history}\n\n### 用户问题\n{question}\n\n1. 完整理解文本语义，提炼核心内容作答。\n2. 不编造信息，内容以原文为准。\n3. 回答简洁自然，无需过度拓展。\n4. 无相关内容回复：未查询到相关信息。",
  "variables": ["question", "context", "history"],
  "llm_config": {
    "temperature": 0.2,
    "top_p": 0.7,
    "max_tokens": 2560,
    "repetition_penalty": 1.05,
    "stream": true
  }
}
```

---

# 10. Tag 标签库模板
适用：关键词库、标签分类、词条注释、标签说明
```json
{
  "name": "标签词条解析模板",
  "desc": "标签、关键词、分类词条专用，精准匹配关键词释义",
  "prompt": "你是标签词条助手，根据标签及释义内容回答问题。\n### 标签参考内容\n{context}\n\n### 用户问题\n{question}\n\n要求：\n1. 精准匹配关键词、标签名称与对应解释。\n2. 多条标签分条展示，结构清晰。\n3. 释义内容完全沿用原文，不修改。\n4. 未匹配到相关标签，直接告知。",
  "variables": ["question", "context", "history"],
  "llm_config": {
    "temperature": 0.1,
    "top_p": 0.7,
    "max_tokens": 2048,
    "repetition_penalty": 1.05,
    "stream": true
  }
}
```

---

# 11. General 通用综合文档模板
适用：混合格式普通文档、无固定结构综合文本
```json
{
  "name": "通用综合文档模板",
  "desc": "全场景通用模板，适配混合结构普通文档",
  "prompt": "你是通用知识库问答助手，请基于参考内容回答用户问题。\n### 参考资料\n{context}\n\n### 历史对话\n{history}\n\n### 用户问题\n{question}\n\n作答要求：\n1. 严格依托参考资料，禁止虚构内容。\n2. 根据文本结构灵活组织答案，逻辑通顺、表达自然。\n3. 长内容合理分段，重点内容突出。\n4. 无相关信息统一回复：当前知识库中未查询到相关信息。",
  "variables": ["question", "context", "history"],
  "llm_config": {
    "temperature": 0.2,
    "top_p": 0.7,
    "max_tokens": 3072,
    "repetition_penalty": 1.05,
    "stream": true
  }
}
```

---

# 12. 高阶：BGE-M3混合检索通用增强模板（全文档通用）
适配 BGE-M3 稠密+稀疏+多向量混合检索，生产环境首选
```json
{
  "name": "BGE-M3混合检索增强模板",
  "desc": "适配BGE-M3三合一检索，整合多片段内容，全文档通用",
  "prompt": "你是基于本地知识库的全能问答助手，本次检索融合语义与关键词匹配结果，请整合多段参考内容统一作答。\n### 知识库检索内容（多片段）\n{context}\n\n### 历史对话\n{history}\n\n### 用户提问\n{question}\n\n统一规范：\n1. 合并、去重多个检索片段，形成完整连贯答案。\n2. 严格仅使用检索内容，绝不编造外部信息。\n3. 根据文档类型调整风格：法规严谨、手册分步、文献总结、表格结构化。\n4. 片段信息冲突时以完整原文为准。\n5. 无有效信息固定回复：暂未在知识库中找到相关内容。",
  "variables": ["question", "context", "history"],
  "llm_config": {
    "temperature": 0.15,
    "top_p": 0.7,
    "max_tokens": 4096,
    "repetition_penalty": 1.05,
    "stream": true
  }
}
```

---

## 导入使用说明
1. 进入 RAGFlow → 知识库数据集 → **设置** → **提示词/智能体模板**
2. 选择「新建模板」，粘贴对应完整 JSON
3. 或直接在现有模板中替换 `prompt` 和 `llm_config` 内容
4. 结合前文分块规则 + BGE-M3 混合检索，整套方案即可落地使用
