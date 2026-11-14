"""短信链路诊断工具。

用法：
    python tools/sms_diagnose.py 13800138000
    python tools/sms_diagnose.py 13800138000 --check-send

行为：
- 登录短信后台，读取该号码最新 5 条短信；
- 打印每条短信的服务器/设备收到时间、发送方、收件人、内容
  以及是否通过「螃蟹账号 + 5 分钟」过滤；
- --check-send 会调用一次螃蟹发送短信接口（不带 ydToken），
  用于确认接口对易盾 Token 的强制要求；该调用不会发送短信，除非接口放行。
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.services.login_service import sms_rejection_reason
from app.services.phone_parser import mask_phone
from app.services.pxb7_client import Pxb7Client, Pxb7Error
from app.services.sms_admin_client import SmsAdminClient, SmsAdminError
from app.services.sms_code import extract_code
from app.settings import SettingsError, load_settings

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def main() -> int:
    parser = argparse.ArgumentParser(description="AutoIFQ 短信链路诊断")
    parser.add_argument("phone", help="要诊断的 11 位手机号")
    parser.add_argument(
        "--check-send",
        action="store_true",
        help="额外调用螃蟹发送短信接口（不带 ydToken），确认接口要求",
    )
    args = parser.parse_args()

    try:
        settings = load_settings()
    except SettingsError as exc:
        print(f"[配置错误] {exc}")
        return 2

    config = settings.login
    masked = mask_phone(args.phone)

    print(f"手机号：{masked}")
    print(
        f"规则：最新 {config.sms_latest_count} 条 · 内容含「{config.sms_keyword}」 · "
        f"服务器收到时间 ≤ {config.sms_max_age_seconds / 60:.0f} 分钟 · "
        f"刷新等待 {config.sms_wait_timeout:.0f}s"
    )

    try:
        admin = SmsAdminClient(settings.sms_admin)
        admin.login()
        messages = admin.latest_messages(args.phone, page_size=20)
        latest = messages[: config.sms_latest_count]
    except SmsAdminError as exc:
        print(f"[短信后台错误] {exc}")
        return 2

    print(f"\n短信后台返回：{len(messages)} 条（仅检查最新 {len(latest)} 条）")
    if not latest:
        print("  → 短信后台没有该收件号码的短信。")
        print("    请确认该手机号的短信已进入短信后台设备（而不是只到了手机本身）。")

    now = time.time()
    valid_found = False
    for index, message in enumerate(latest, start=1):
        reason = sms_rejection_reason(message, config, now=now)
        server_parsed = message.server_timestamp
        age = int(now - server_parsed) if server_parsed > 0 else None
        code = extract_code(message.content)

        print(f"\n[{index}] {reason or '符合条件'}")
        print(f"    服务器收到：{message.created_at or '-'}")
        print(f"    设备收到：  {message.received_at or '-'}")
        print(f"    发送方号码：{message.sender or '-'}")
        print(
            "    收件人："
            f"to_number={message.raw.get('to_number') or '-'} "
            f"device_phone={message.raw.get('device_phone') or '-'}"
        )
        print(
            "    接收设备："
            f"device_id={message.raw.get('device_id') or '-'} "
            f"SIM={message.raw.get('sim_slot') or '-'} "
            f"推送状态={message.raw.get('push_status') or '-'}"
        )
        if age is None:
            print("    服务器时间解析：失败")
        else:
            print(f"    服务器时间解析：成功（年龄 {age}s）")
        print(
            f"    关键字「{config.sms_keyword}」："
            f"{'有' if config.sms_keyword in message.content else '无'} · "
            f"可提取验证码：{'有' if code else '无'}"
        )
        print(f"    内容：{message.content[:160]}")
        if reason is None:
            valid_found = True

    print("\n结论：", "存在符合条件的验证码短信" if valid_found else "暂无符合条件的验证码短信")

    if args.check_send:
        print("\n—— 螃蟹发送短信接口自检（不带 ydToken）——")
        try:
            Pxb7Client(settings.pxb7, args.phone).send_login_code(args.phone)
            print("接口调用成功（接口未拦截；请确认是否实际发送了短信）")
        except Pxb7Error as exc:
            print(f"接口返回：{exc}")
            print("说明：该接口要求易盾 ydToken，纯协议无法直接触发短信。")

    return 0 if valid_found else 3


if __name__ == "__main__":
    raise SystemExit(main())
