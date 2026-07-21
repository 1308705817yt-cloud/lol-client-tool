# LoL 客户端工具

一个运行在 Windows 上的英雄联盟客户端辅助工具。程序通过本地 League Client API 读取选人和对局数据，提供战绩展示、自动接受、自动 BP、玩家备注和预设快捷发送功能。

## 功能

- 查询队友近期战绩和单双排、灵活排位信息。
- 在加载或对局阶段展示双方英雄及近期数据。
- 自动接受对局，并按配置执行禁用或选择英雄。
- 根据客户端提供的位置填入双方英雄；位置缺失时按队伍顺序补齐。
- 保存玩家备注，并在后续对局中提醒。
- 使用小键盘发送自定义的固定语句或随机语句。

自定义对局的数据可能比普通匹配更晚就绪。程序会在选人阶段尝试读取，并在进入游戏后短暂重试。

## 环境要求

- Windows 10 或更高版本
- Python 3.11
- 已安装并运行英雄联盟客户端

建议使用独立虚拟环境：

```powershell
py -3.11 -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python main.py
```

首次运行时程序会请求管理员权限，用于监听全局小键盘状态并向游戏窗口发送按键。

## 配置

配置保存在程序目录下的 `config.json`。该文件已加入 `.gitignore`，不会提交到仓库。需要手动准备配置时，可以复制示例：

```powershell
Copy-Item config.example.json config.json
```

快捷键：

| 按键 | 操作 |
| --- | --- |
| 小键盘 `0` | 发送固定语句 |
| 小键盘 `.` | 从句子库随机发送 |
| 小键盘 `1` 至 `5` | 依次选择上单、打野、中单、AD、辅助 |
| 小键盘 `6` | 切换队伍频道和所有人频道 |

所有快捷发送功能默认关闭。

## 测试

```powershell
python -m py_compile main.py shared.py utils.py match_utils.py game_input.py quick_chat.py lcu_core.py gui.py
python -m unittest discover -v
```

## 打包

使用包含 Tcl/Tk 组件的官方 Python 安装包，然后执行：

```powershell
python -m pip install -r requirements-build.txt
pyinstaller --noconfirm --onefile --windowed --name LoL助手 main.py
```

输出文件位于 `dist` 目录。`config.json` 与程序放在同一目录即可。

## 隐私与使用说明

- 程序只连接本机的英雄联盟客户端接口，不提供远程服务。
- `config.json` 可能包含玩家名称、个人备注和自定义语句，请勿公开上传。
- 分享日志前请移除玩家名称、PUUID、召唤师 ID 等信息。
- 本项目并非 Riot Games 官方产品，也未获得 Riot Games 认可或赞助。
- 自动化和聊天功能可能受到游戏服务条款或地区规则限制，使用者应自行确认并承担相应责任。

## 参与开发

提交问题或代码前请阅读 [CONTRIBUTING.md](CONTRIBUTING.md)。

## 许可证

本项目使用 [MIT License](LICENSE)。
