



# 1. 下载镜像

## 方式1：docker pull 逐个下载
```

docker pull elasticsearch:8.11.3

docker pull infiniflow/ragflow:v0.25.6

docker pull pgsty/minio:RELEASE.2026-03-25T00-00-00Z

```

> 下面的ollama按需下载：
>
```

docker pull ollama/ollama:latest

docker pull ghcr.io/huggingface/text-embeddings-inference:latest

```


## 方式2：执行 docker compose -f docker-compose.yml up -d 进行下载

```
docker compose -f docker-compose.yml up -d
```


# 2. 运行镜像，启动容器

## 2.1 进入docker-compose.yml所在的目录：
```
cd /usr/local/myproject/ragflow/docker
```


## 2.2 在首次执行docker compose -f docker-compose.yml up -d的时候，需要给 entrypoint.sh 授权，否则会报错：

```
Container docker-ragflow-cpu-1 Starting                                                                                                                                                                                   0.1s
Error response from daemon: failed to create task for container: failed to create shim task: OCI runtime create failed: runc create failed: 
unable to start container process: error during container init: exec: "./entrypoint.sh": permission denied
```

## 给entrypoint.sh增加 执行权限：
```
chmod +x entrypoint.sh
```


## 2.2 进入docker-compose.yml所在的目录，执行 docker compose -f docker-compose.yml up -d
### 方式1：docker compose -f docker-compose.yml up -d
```
进入docker-compose.yml所在的目录

docker compose -f docker-compose.yml up -d
```

### 方式2：使用集成化的启动脚本: sh start_stop_ragFlow.sh start
```
进入docker-compose.yml所在的目录

(base) [root@iZ2vcftc4aunr4n9ucf937Z docker]# sh start_stop_ragFlow.sh start
================== Docker Compose 管理工具 ==================
1. 后台启动容器
2. 停止容器
3. 重启容器
4. 实时查看【仅ragflow容器】日志（推荐）
5. 删除容器(保留数据卷)
6. 退出
===========================================================
请输入操作序号：1

正在启动 ollama 容器...
ollama
ollama 启动完成，开始启动 compose 服务...
[+] up 3/3
 ✔ Container docker-minio-1       Running                                                                                                                                                                                    0.0s
 ✔ Container docker-es01-1        Running                                                                                                                                                                                    0.0s
 ✔ Container docker-ragflow-cpu-1 Started                                                                                                                                                                                    0.2s
全部服务启动完毕
按回车返回菜单...

```



## 运维相关命令


### 查看容器日志

docker compose -f docker-compose.yml logs -f ragflow-cpu

















