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

你可以使用`git`命令，将ragflow项目下载到这个文件夹，本教程使用的是`v0.22.0`版本进行安装部署。
```
git clone https://ghfast.top/https://github.com/infiniflow/ragflow.git
cd ragflow
git checkout v0.22.0
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
REDIS_PASSWORD=                  # 如果你的Redis没有设置密码，就按这样子填写，否则填写密码
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



如果启动报错：1200端口被占用
```angular2html
Error response from daemon: ports are not available: exposing port TCP 0.0.0.0:1200 -> 127.0.0.1:0: listen tcp 0.0.0.0:1200: bind: An attempt was made to access a socket in a way forbidden by its access permissions.
这个错误是Windows 下 Docker 端口被占用 / 被系统保留 / 权限不足导致的，核心原因：1200 端口无法绑定，系统禁止使用。
我给你最直接、一步到位的解决方法（按顺序试，99% 能解决）：
一、最快解决：直接换个端口（推荐）
不用查占用，直接把 1200 改成别的端口，比如：
1201
1300
8080
8090
例如你原来的命令是：
bash
运行
-p 1200:1200
改成：
bash
运行
-p 1300:1200
立刻就能跑起来。

二、如果你必须用 1200 端口（完整修复）
1. 先看谁占用了 1200
以管理员身份打开 CMD / PowerShell，运行：
netstat -ano | findstr ":1200"
如果有输出，说明被其他程序占用。记下最后那串数字（PID），打开任务管理器 → 详细信息 → 结束对应 PID 进程。

2. 最常见原因：Windows 保留了这段端口（Hyper-V 导致）
很多人安装了 WSL / Hyper-V，系统会自动保留一段端口，刚好把 1200 包含进去，所以 Docker 无权使用。

管理员权限执行下面 3 条命令：
查看被保留端口范围
netsh int ipv4 show excludedportrange protocol=tcp
你会看到 1200 落在一段禁止端口里。

释放保留端口
net stop winnat

重启端口服务
net start winnat

然后重启 Docker Desktop，再跑容器就正常了。

3. 终极解决：永久排除 1200 端口不被系统占用
将.env文件中中的1200端口和1201端口改为排序序列之外的端口，即可解决此端口占用的问题

修改完成之后，再重启镜像服务可正常使用
```



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


#### 给ragflow配置本地模型的相关过程记录如下：

1.[ragflow服务模型 可配置的免费的大语言模型LLM有哪些?](https://www.doubao.com/thread/w72d11630085b668a)

2.[LLM 通俗大白话介绍](https://www.doubao.com/thread/w3dcce8018d3da946)

3.[Windows安装Ollama](https://www.doubao.com/thread/w086ab2ca30d5dd09)

4.[ollama官网](https://ollama.com/download)

5.[128G内存的电脑 适合部署哪个qwen模型？](https://www.doubao.com/thread/w95419e07403508d2)


OllamaSetup的默认安装路径是C盘
6.[OllamaSetup安装路径如何自定义？](https://www.doubao.com/thread/w5b372f794ee2cc48)
"D:\软件\开发软件\OllamaSetup.exe" /DIR="D:\AI\Ollama"


7.[Windows Ollama常用命令](https://www.doubao.com/thread/w46fd03368a86b04c)


8.[RAGFlow web界面如何配置ollama](https://www.doubao.com/thread/wbaf17693f60b1551)



9.[ragflow文档解析报错 Task has been received. Page(1~9): [ERROR]Fail to bind embedding model: Model(@None) not authorized [ERROR][Exception]: Model(@None) not authorized](https://www.doubao.com/thread/we3cd77f6f1aeb162)
下载并安装Embedding向量模型
ollama pull nomic-embed-text



10.[RAGFlow Ollama Qwen 最大Token 标准答案](https://www.doubao.com/thread/wbcec37870dee8cbe)



# 第二部分 配置ragflow服务

# 第一步 登录ragflow服务
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
