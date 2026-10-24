本文档是开发类文档，如需部署小智服务端，[点击这里查看部署教程](../../README.md#%E9%83%A8%E7%BD%B2%E6%96%87%E6%A1%A3)

# xiaozhi

## Project setup


开发使用代码编辑器，导入项目时，选择`manager-web`文件夹作为项目目录
```
cd main/manager-web/
```

开发使用代码编辑器，导入项目时，选择`manager-web`文件夹作为项目目录

```
npm install
```

### Compiles and hot-reloads for development

```
npm run serve
```

### Compiles and minifies for production

```
npm run build
```

### Customize configuration

See [Configuration Reference](https://cli.vuejs.org/config/).

### 前端登录：http://localhost:8001/
#### 用户名： admin
#### 密码： Admin1234

### 注意：如果忘记密码，将sys_user表中对应的用户数据删除，重新刷新登录页面即可重新添加用户
请认真测试下 D:\javaWorkSpace\xiaozhi-esp32-server\main\xiaozhi-server\core\providers\asr\aliyunbl_funAsr_stream.py、D:\javaWorkSpace\xiaozhi-esp32-server\main\xiaozhi-server\core\providers\tts\qwen_audio_tts_stream.py功能，目前这2个功能在一起使用的时候存在报错：[core.providers.tts.qwen_audio_tts_stream]-WARNING-TTS合成器不存在，正在重建会话后继续发送文本,261013 11:40:58[0.9.2-00000000000000][core.providers.tts.qwen_audio_tts_stream]-ERROR-语音合成出现异常: {"header":{"task_id":"6e0872a626f44eb2b098c2042a4b7e2c","event":"task-failed","error_code":"InvalidParameter","error_message":"request timeout after 23           
seconds."},"payload":{}}