# AutoIFQ · 自动询价助手

基于 PyQt6 的自动询价工具。当前已接入业务流程第 1 步：**螃蟹上号**（账号密码登录）。

## 已实现

- 上传账号 TXT 清单，格式：`手机号----密码`；只有手机号时使用默认密码。
- **协议密码登录**：密码使用页面同款 RSA 公钥加密后，通过 `twiceLogin` 接口提交。
- **Playwright 仅用于获取易盾 token**：打开登录页、填写账号密码、触发登录请求，
  截取请求中的 `ydToken` 后**中止浏览器自己的登录请求**；真正的登录由协议客户端发送。
- 如出现易盾滑块，需要在可见浏览器中人工完成；工具不破解验证码。
- 捕获协议登录响应；需要身份选择时自动通过 `sign2token` / `queryMerchantToken` 换取 token。
- 调用 `detailInfo` 读取用户信息，日志输出用户名 / 用户 ID。
- 支持线程数、暂停/继续、停止；网络与浏览器操作在后台线程执行。

> 平台密码登录接口强制校验易盾 token：不带 token 的纯协议请求会返回「易盾token为空」。
> 因此无法在完全不获取易盾 token 的情况下完成登录；本工具将浏览器限定为 token 获取环节。

> 后续步骤（表格写入、对话聊天、完成询价、填入表格）尚未接入。

## 运行

```bash
python -m pip install -r requirements.txt
python main.py
```

首次运行前，把 `config.example.json` 复制为 `config.json`。

### Playwright 浏览器

默认使用系统已安装的 **Microsoft Edge**（`browser_channel: "msedge"`）。
如果本机没有 Edge，可将 `browser_channel` 设为空字符串并安装 Chromium：

```bash
python -m pip install playwright
python -m playwright install chromium
```

`browser_headless` 当前配置为 `true`：无头运行，不显示浏览器窗口。
实测账号的易盾为无感知验证，未出现人工滑块；如果某些账号出现滑块，请改为 `false` 后重试。

## 账号清单格式

```text
13800138000----自定义密码
13900139000
13700137000----AnotherPass!2026
```

- `手机号----密码`：使用指定密码。
- 只有手机号：使用 `config.json` 中 `login.default_password`（默认 `Aa123456`）。
- 同一号码重复出现时，显式密码优先于仅手机号。
- TXT 支持 UTF-8 / GBK 等常见编码。

## 登录流程

1. 上传账号 TXT。
2. 点击「开始询价」。
3. 对每个账号：
   - Playwright（无头）打开螃蟹密码登录页，填写账号密码并勾选协议；
   - 如出现滑块，将 `browser_headless` 设为 false 后人工完成；
   - 截取页面即将提交的 `twiceLogin` 请求中的易盾 `ydToken`，并中止该浏览器请求；
   - 关闭浏览器；
   - 协议客户端使用同一密码做 RSA 加密，携带 `ydToken` 调用 `twiceLogin`；
   - 需要身份选择时自动换取 token；
   - 读取用户信息，日志打印用户名。
4. 失败记录错误并自动继续下一个账号。

> 登录请求由 Python 协议客户端发出；浏览器只负责通过易盾验证。
> 若账号密码错误，接口返回「账号或密码错误」，不会消耗浏览器的登录状态。

### 能否完全去掉浏览器？

不能。密码登录接口强制校验易盾 token，纯协议不带 token 会返回「易盾token为空」。
当前的无头 Playwright 只用于取得该 token，实际登录请求已经完全协议化。
如果拥有其他合法的易盾 token 获取渠道，可以将其替换为纯协议 token 来源；
否则必须保留这个无头 token 获取步骤。

## 配置说明

```jsonc
{
  "pxb7": {
    "base_url": "https://api-pc.pxb7.com/api",
    "website": "https://www.pxb7.com",
    "country_code": "86",
    "request_timeout": 30
  },
  "login": {
    "default_password": "Aa123456",  // 只有手机号时使用的默认密码
    "browser_headless": true,        // 无头获取易盾 token；出现滑块时改 false
    "browser_timeout": 180,          // 等待易盾 token 的最长秒数
    "browser_channel": "msedge"      // msedge / chrome / 空字符串=Chromium
  }
}
```

`sms_admin` 与 `sms_*` 配置属于旧版短信验证码流程，密码登录不再使用，可保留用于诊断。

## 排查

- **账号或密码错误**：检查 TXT 中密码是否正确；测试账号默认密码 `Aa123456` 不一定适用。
- **未获取到易盾 token**：若账号出现滑块，将 `browser_headless` 设为 `false` 后人工完成。
- **无需人工滑块**：实测账号的易盾为无感知验证，无头模式即可自动取得 token。
- **易盾token为空**：说明协议请求没有携带 token，检查 token 获取步骤。
- **浏览器没有弹出**：确认已安装 Playwright 与 Edge；或改用 Chromium 并安装浏览器。
- 旧版短信链路诊断：
  ```bash
  python tools/sms_diagnose.py 13800138000
  ```

## 目录结构

```text
main.py                      # 程序入口
app/
  application.py             # QApplication + 主窗口启动
  constants.py               # 流程步骤、参数定义、尺寸等常量
  models.py                  # RunState / RunParams
  runner.py                  # LoginRunner：后台线程执行协议密码登录
  settings.py                # config.json 加载与校验
  theme.py                   # 深色主题 QSS
  utils.py                   # 通用工具
  services/
    accounts.py              # 手机号----密码 清单解析（默认密码）
    phone_parser.py          # 手机号解析与脱敏（旧短信流程/通用）
    pxb7_client.py           # 螃蟹协议客户端（RSA 密码、token、用户信息）
    pxb7_yd_token.py         # Playwright 获取易盾 token（会中止浏览器登录请求）
    sms_code.py              # 旧版：短信验证码提取
    sms_admin_client.py      # 旧版：短信后台协议客户端
    pxb7_sms_trigger.py      # 旧版：Playwright 触发登录短信
    login_service.py         # 旧版：短信验证码登录编排
  ui/
    main_window.py           # 主窗口：组合面板、驱动任务
    header_bar.py            # 顶部标题栏
    card.py                  # 通用卡片容器
    click_outside.py         # 全局「点击外部确认」过滤器
    upload_panel.py          # 账号清单上传卡片
    drop_zone.py             # 点击 / 拖拽导入区域
    progress_panel.py        # 询价进度卡片
    segmented_progress.py    # 五段式进度可视化组件
    parameter_panel.py       # 运行参数卡片（失焦/点击外部确认）
    phrase_panel.py          # 询问话术列表卡片
    phrase_row.py            # 单条话术输入行（失焦/点击外部确认）
    action_panel.py          # 运行控制卡片
    log_panel.py             # 日志卡片
    elided_label.py          # 自动省略文本标签
tools/
  sms_diagnose.py            # 旧版短信链路诊断
```

## 安全说明

- 账号密码来自本地上传的 TXT；日志不会输出密码或易盾 token。
- Playwright 使用普通本地浏览器打开官方页面；工具不包含滑块破解、验证码识别或反检测逻辑，
  出现滑块时需要人工完成。
- 密码加密使用页面公开的 RSA 公钥，不包含任何私钥。
- `config.json` 已加入 `.gitignore`，不会被提交；日志中的手机号做脱敏处理。
