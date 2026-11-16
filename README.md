# AutoIFQ · 自动询价助手

基于 PyQt6 的自动询价工具。当前已接入业务流程：**先从飞书多维表格读取数据并构建表格，再按线程数展开工作线程执行螃蟹上号**（账号密码登录）。

## 已实现

- 上传账号 TXT 清单，格式：`手机号----密码`；只有手机号时使用默认密码。
- **飞书扫码登录**：点击右上角「飞书未登录」，在打开的浏览器中使用飞书 App 扫码；
  登录成功后保存会话，并自动进入指定租户 / 多维表格。
- **飞书多维表格作为数据源**：开始运行时自动读取《三角洲成品号--小新》，
  提取 6 个必要列并生成本地 Excel 询价表；不再需要手动上传 Excel。
- 「手动测试」按钮：打开独立的“手动测试”窗口（当前内容暂定）。
- **协议密码登录**：密码使用页面同款 RSA 公钥加密后，通过 `twiceLogin` 接口提交。
- **Playwright 仅用于获取易盾 token**：打开登录页、填写账号密码、触发登录请求，
  截取请求中的 `ydToken` 后**中止浏览器自己的登录请求**；真正的登录由协议客户端发送。
- 如出现易盾滑块，需要在可见浏览器中人工完成；工具不破解验证码。
- 捕获协议登录响应；需要身份选择时自动通过 `sign2token` / `queryMerchantToken` 换取 token。
- 调用 `detailInfo` 读取用户信息，日志输出用户名 / 用户 ID。
- 支持线程数、暂停/继续、停止；网络与浏览器操作在后台线程执行。
- **询问话术本地持久化**：保存到 `data/phrases.json`，启动自动加载。
- **运行参数本地持久化**：保存到 `data/parameters.json`，启动自动恢复。

> 平台密码登录接口强制校验易盾 token：不带 token 的纯协议请求会返回「易盾token为空」。
> 因此无法在完全不获取易盾 token 的情况下完成登录；本工具将浏览器限定为 token 获取环节。

> 线程列表中的后续步骤（对话聊天、完成询价、填入表格）尚未接入。

## 运行

推荐使用项目自带虚拟环境（Windows）：

```bash
venv\Scripts\python -m pip install -r requirements.txt
venv\Scripts\python main.py
```

也可以直接使用系统 Python，但请确保安装依赖和运行程序使用**同一个解释器**：

```bash
python -m pip install -r requirements.txt
python main.py
```

首次运行前，把 `config.example.json` 复制为 `config.json`。

> 如果启动时报 `No module named 'openpyxl'`、`No module named 'PyQt6'` 等错误，
> 说明当前 IDE/终端选择的 Python 没有安装依赖。请在该解释器执行
> `python -m pip install -r requirements.txt`，或在 VS Code 中选择
> `venv\Scripts\python.exe` 作为解释器。

### Playwright 浏览器

默认使用系统已安装的 **Microsoft Edge**（`browser_channel: "msedge"`）。
如果本机没有 Edge，可将 `browser_channel` 设为空字符串并安装 Chromium：

```bash
python -m pip install playwright
python -m playwright install chromium
```

`browser_headless` 当前配置为 `true`：螃蟹登录的易盾 token 获取为无头运行。
实测账号的易盾为无感知验证，未出现人工滑块；如果某些账号出现滑块，请改为 `false` 后重试。

飞书扫码登录始终使用可见浏览器（需要人工扫码）；
读取飞书表格时默认先尝试无头，失败后自动改用可见浏览器。两者都使用
`feishu.browser_channel`（默认 `msedge`）。

## 打包为 EXE

双击或在项目目录运行：

```bat
build_exe.bat
```

脚本会安装依赖、安装 PyInstaller、执行单文件打包，并复制 `config.json`、`config.example.json` 和 `data/` 到 `dist/`。

输出：

```text
dist/AutoIFQ.exe
dist/config.json          # 实际配置（包含短信后台凭证，请勿外发）
dist/config.example.json
dist/data/                # 已保存的询问话术、运行参数、飞书登录状态
```

> `dist/data/feishu_state.json` 包含飞书会话信息。分发 EXE 前请删除该文件，
> 让使用者自行扫码登录。

- 打包结果已通过内置冒烟测试：

  ```bat
  dist\AutoIFQ.exe --smoke-test
  ```

  该测试会构建主窗口、加载 Excel 依赖并启动一次无头 Edge，验证 Playwright 驱动可用。
- Playwright 使用系统已安装的 **Microsoft Edge**（`browser_channel: "msedge"`）。目标电脑没有 Edge 时无法获取易盾 token；可改为 Chromium 并自行安装浏览器。
- 单文件 EXE 启动时会解压到临时目录，首次打开会比源码运行稍慢。
- EXE 与 `config.json`、`data/` 必须放在同一目录，运行后生成的表格在 `dist/output/`。
- `build/`、`dist/`、`*.spec` 已加入 `.gitignore`。

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

## 任务流程

1. 启动程序，点击右上角「飞书未登录」，在浏览器中使用飞书 App 扫码登录。
   登录成功状态会保存；如果会话过期，重新点击右上角登录即可。
2. 上传账号 TXT（不再需要上传 Excel）。
3. 点击「开始询价」后：
   - **先读取飞书多维表格并构建本地 Excel 询价表**（全局前置，不计入线程步骤）；
   - 构建成功后，按线程数展开工作线程；
   - 构建失败则停止，不执行任何账号登录。
4. 每个线程（账号）执行：
   - Playwright（无头）打开螃蟹密码登录页，填写账号密码并勾选协议；
   - 如出现滑块，将 `browser_headless` 设为 false 后人工完成；
   - 截取易盾 `ydToken` 并中止浏览器登录请求；
   - 协议客户端使用 RSA 加密密码并登录，读取用户信息；
   - 失败记录错误，继续后续账号。

> 登录请求由 Python 协议客户端发出；浏览器只负责通过易盾验证。
> 若账号密码错误，接口返回「账号或密码错误」，不会消耗浏览器的登录状态。

## 飞书扫码登录

- 入口：界面右上角状态按钮（`飞书未登录` / `登录中…` / `飞书已登录`）。
- 点击后打开可见的 Microsoft Edge 窗口，使用飞书 App 扫描二维码；
  工具不会代替用户扫码，也不处理验证码。
- 扫码成功后工具会：
  1. 进入配置中的租户（`杭州维音信息科技公司`）；
  2. 打开 `Auto测试库` 中的 `三角洲成品号--小新` 表；
  3. 将登录状态保存到 `data/feishu_state.json`；
  4. 在运行日志中打印登录与目标表结果。
- 登录状态文件包含飞书会话 Cookie，**请勿外发**；`data/` 已加入 `.gitignore`。
- 登录等待时间由 `feishu.login_timeout` 控制（默认 300 秒），超时后需重试。

## 手动测试

- 账号上传卡片右侧的「手动测试」按钮会打开独立窗口，标题为“手动测试”。
- 当前窗口内容为占位，后续手动测试功能在该窗口中扩展。
- 同一时间只保留一个手动测试窗口。

### 能否完全去掉浏览器？

不能。密码登录接口强制校验易盾 token，纯协议不带 token 会返回「易盾token为空」。
当前的无头 Playwright 只用于取得该 token，实际登录请求已经完全协议化。
如果拥有其他合法的易盾 token 获取渠道，可以将其替换为纯协议 token 来源；
否则必须保留这个无头 token 获取步骤。

## 飞书数据源要求

目标多维表格中需要有这 6 个字段名（列顺序可以不同）：

```text
账号、账号内容、收购日期、可不可二次、成本、拉群前报价
```

- 工具会打开配置中的目标表链接，解析页面加载时返回的字段和记录接口，
  再按字段名映射这 6 列。
- 飞书新版多维表格的网格可能使用 canvas 渲染，无法通过复制网页内容取数；
  工具改为直接读取页面的字段 / 记录数据。
- 读取字段名时会忽略空格、换行和 `【】` / `[]`；缺少字段时日志会列出缺少项。
- 飞书表格只读，不会修改原表；只在本地生成新的询价表。
- 如果登录状态过期，构建会失败并提示重新点击右上角登录飞书。

## 构建表格（点击开始后的前置步骤）

1. 使用已保存的飞书登录状态打开目标多维表格；
2. 解析页面接口返回的上述 6 个字段记录；
3. 新建一个本地 Excel 工作簿（工作表名「自动询价」），写入这 6 列；
4. 默认保存到项目 `output/自动询价表格_时间戳.xlsx`，路径会写入日志；
5. 测试阶段只摘录前 5 条；`excel.copy_limit` 控制摘录条数，
   设为 `0` 时使用页面当前已加载的记录（最多约 200 条）；
6. 构建成功后才会展开线程；构建失败时线程不执行。

如果飞书表有 8 条记录、限制为 5，日志会显示：

```text
飞书表格读取成功：Auto测试库 / 三角洲成品号--小新，源表 8 条，已摘录前 5 条。
构建表格完成：从「Auto测试库 / 三角洲成品号--小新」摘录 5 条（源表 8 条）。
新表格已保存：.../output/自动询价表格_20261116_093405.xlsx
```

> 飞书网页版可能随版本调整页面结构。工具会先尝试无头浏览器读取；
> 若读取失败，会自动改用可见浏览器重试，并在日志中提示。
> 如仍失败，可尝试重新登录飞书后再运行。

## 线程进度展示

- 进度区顶部只有一行「构建表格」状态，不再占用线程步骤。
- 构建成功后，按【线程数】创建对应数量的工作线程；线程进度以**列表行**形式展示，不使用卡片。
- 每行显示：线程号 / 脱敏手机号 / 四个步骤的状态点 / 线程总进度。
- 每个线程从账号队列取一条数据处理；该条数据完成或失败后，**该列表行立即移除**，线程继续取下一条数据。
- 测试阶段完成现有登录逻辑即视为该条数据处理完成。
- 活跃列表行数不超过线程数；全部数据完成后列表清空，日志和状态栏给出成功数量汇总。
- 线程之间独立更新，互不覆盖。

## 询问话术持久化

- 保存位置：项目目录 `data/phrases.json`。
- 自动保存时机：新建/删除话术、输入框失焦或点击外部确认内容、关闭窗口。
- 启动时自动加载；文件损坏或格式不正确时在日志中提示，并以空列表启动。
- `data/` 已加入 `.gitignore`，不会被提交。
- 文件内容为 JSON 字符串数组，例如：

  ```json
  [
    "您好，请问【{商品}】目前有货吗？",
    "我们计划采购 {数量} 件，麻烦报一下含税单价。"
  ]
  ```

## 运行参数持久化

- 保存位置：项目目录 `data/parameters.json`。
- 自动保存时机：参数值变更、输入框失焦确认、关闭窗口。
- 启动时自动加载；缺失或非法的字段会回退到默认值。
- 文件内容示例：

  ```json
  {
    "threads": 1,
    "interval_sec": 3.0,
    "merchant_count": 20,
    "timeout_sec": 90,
    "retries": 2
  }
  ```

- 参数持久化与询问话术持久化共用 `data/` 目录，该目录已加入 `.gitignore`。

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
  },
  "excel": {
    "copy_limit": 5,                 // 摘录条数；0 = 使用页面当前加载的记录
    "output_dir": ""                 // 空 = 项目 output/ 目录
  },
  "feishu": {
    "login_url": "https://accounts.feishu.cn/...",  // 扫码登录地址
    "table_url": "https://mcnd1pwpmqfu.feishu.cn/base/...", // 目标表链接
    "tenant_name": "杭州维音信息科技公司",
    "base_name": "Auto测试库",
    "table_name": "三角洲成品号--小新",
    "state_path": "data/feishu_state.json", // 登录状态文件
    "browser_channel": "msedge",
    "login_timeout": 300,            // 扫码等待秒数
    "fetch_headless": true           // 读取表格时先尝试无头；失败自动用可见浏览器重试
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
- **`No module named 'openpyxl'`**：运行程序的 Python 未安装依赖；在该解释器执行 `python -m pip install -r requirements.txt`，或改用项目 venv。
- **飞书未登录 / 会话失效**：点击右上角「飞书未登录」重新扫码；成功后会重新保存登录状态。
- **飞书表缺少必要字段**：日志会列出缺少的字段名与当前字段列表，补全后重新运行。
- **飞书表格读取失败**：查看日志中的字段缺失或接口错误提示；可尝试重新点击右上角登录飞书后重试。
- **没有生成新表格**：检查飞书登录状态、目标表链接和必要字段；失败时查看日志中的表格错误。
- **点击开始没有反应**：确认已导入账号 TXT、飞书已登录，且没有正在进行的扫码登录。
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
  feishu_login.py            # 飞书二维码登录 QThread、保存会话
  runner.py                  # LoginRunner：先读取飞书表构建表格，再启动线程
  settings.py                # config.json 加载与校验
  theme.py                   # 深色主题 QSS
  utils.py                   # 通用工具
  services/
    accounts.py              # 手机号----密码 清单解析（默认密码）
    phrase_store.py          # 询问话术本地 JSON 持久化
    parameter_store.py       # 运行参数本地 JSON 持久化
    feishu_common.py         # 飞书登录状态路径等公共工具
    feishu_table.py          # 读取飞书多维表格并解析必要字段
    phone_parser.py          # 手机号解析与脱敏（旧短信流程/通用）
    pxb7_client.py           # 螃蟹协议客户端（RSA 密码、token、用户信息）
    pxb7_yd_token.py         # Playwright 获取易盾 token（会中止浏览器登录请求）
    excel_table.py           # 根据数据源记录生成新询价表
    sms_code.py              # 旧版：短信验证码提取
    sms_admin_client.py      # 旧版：短信后台协议客户端
    pxb7_sms_trigger.py      # 旧版：Playwright 触发登录短信
    login_service.py         # 旧版：短信验证码登录编排
  ui/
    main_window.py           # 主窗口：组合面板、驱动任务、飞书登录
    header_bar.py            # 顶部标题栏 + 飞书登录状态
    card.py                  # 通用卡片容器
    click_outside.py         # 全局「点击外部确认」过滤器
    upload_panel.py          # 账号清单上传卡片 + 手动测试入口
    manual_test_window.py    # “手动测试”独立窗口（内容暂定）
    drop_zone.py             # 点击 / 拖拽导入区域
    progress_panel.py        # 构建表格状态 + 动态线程列表
    thread_progress_row.py   # 线程列表中的单行（完成/失败后移除）
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
- 飞书二维码由用户本人在官方页面扫码完成；工具不保存飞书账号密码，也不处理验证码。
- 飞书登录状态保存在 `data/feishu_state.json`，包含会话 Cookie，属于敏感信息，请勿外发。
- Playwright 使用普通本地浏览器打开官方页面；工具不包含滑块破解、验证码识别或反检测逻辑，
  出现滑块时需要人工完成。
- 密码加密使用页面公开的 RSA 公钥，不包含任何私钥。
- `config.json`、`data/` 已加入 `.gitignore`，不会被提交；日志中的手机号做脱敏处理。
