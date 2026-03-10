# astrbot-plugin-ctf-push
astrbot插件，定期推送CTF比赛信息到QQ群内

## 功能
- 每天固定时间（后台可配置）定时推送
- /比赛 指令查询当日比赛
- /查询比赛 关键词、/比赛查询 关键词 模糊查询历史入库比赛
- 使用接口数据清洗后的比赛信息
- 自动过滤已结束比赛
- 每次手动 /比赛 和每日定时推送时，会把“全部比赛数据”（含 description）更新到 SQLite

## 配置（AstrBot 后台）
插件配置项见 _conf_schema.json：

- enabled: 是否启用定时推送
- push_time: 每日推送时间，格式 HH:MM，可写多个（逗号分隔），如 09:00,21:30
- timezone: 时区，默认 Asia/Shanghai
- group_whitelist: 推送白名单
- 可填 unified_msg_origin 也可填群号字符串，但该群需要先执行一次 /比赛 让插件记录映射
- api_url: 比赛接口地址
- request_timeout: 请求超时秒数
