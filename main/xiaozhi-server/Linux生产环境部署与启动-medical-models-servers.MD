
# 1.搭建项目虚拟环境
## 1.1 用 conda 创建虚拟环境（推荐）
```
conda create -n medical-models-servers python=3.10 -y
```

---

## 1.2 激活虚拟环境
```
conda activate medical-models-servers
```
---


## 1.3 安装项目依赖
```
pip install -r requirements.txt
```
---


## 1.4 退出虚拟环境
```
conda deactivate
```
---


## 1.5 删除虚拟环境（若需重建）
```
conda remove -n medical-models-servers --all
```
---




# 2. 生产环境启动、停止服务
## 2.1 必须 先 激活虚拟环境
```
conda activate medical-models-servers
```


## 2.2 在虚拟环境中 执行项目的启动脚本

```
sh deploy_api_server_1.sh start

或 

sh deploy_api_server_2.sh start
```

## 2.3 验证启动是否成功
### 启动 deploy_api_server_1.sh 时

> 浏览器访问：http://8.137.151.255:8106/health
> 
> 正常返回：{"status":"healthy","status_code":200,"backend":"llama-server","model":"Qwen3.5-Medical-GSPO.Q4_K_M.gguf","parallel_slots":4,"uptime_seconds":1792721845,"slots":{"status":"ok"}}



### 启动 deploy_api_server_2.sh 时

> 浏览器访问：http://8.137.151.255:8104/health
> 
> 正常返回：{"status":"healthy","status_code":200,"backend":"llama-server","model":"Qwen3.5-Medical-GSPO.Q4_K_M.gguf","parallel_slots":4,"uptime_seconds":1792721845,"slots":{"status":"ok"}}







































