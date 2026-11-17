"""螃蟹询价后台任务：先构建表格，再按线程数展开工作线程。"""

from __future__ import annotations

import queue
import random
import shutil
import threading
import time
from pathlib import Path

from PyQt6.QtCore import QThread, pyqtSignal

from .constants import StepStatus
from .models import RunParams
from .services.accounts import Account
from .services.consult_history import (
    ConsultHistoryStore,
    ConsultHistoryStoreError,
)
from .services.excel_table import (
    ExcelTableError,
    add_quote_columns,
    build_result_table,
    write_quote,
)
from .services.feishu_table import (
    FeishuLoginRequired,
    FeishuRecord,
    FeishuTableClient,
    FeishuTableError,
)
from .services.phone_parser import mask_phone
from .services.proxy_provider import (
    ProxyEndpoint,
    ProxyPool,
    ProxySettings,
    ProxyStore,
    ProxyStoreError,
)
from .services.pxb7_chat import (
    PhoneSession,
    Pxb7ChatCancelled,
    Pxb7ChatError,
    Pxb7ChatLoginRequired,
    Pxb7ChatService,
)
from .services.pxb7_client import Pxb7Client, Pxb7Error, Pxb7LoginError
from .services.pxb7_yd_token import Pxb7BrowserYdTokenProvider
from .settings import AppSettings


class LoginRunner(QThread):
    """先构建表格，再启动固定数量的工作线程处理账号队列。"""

    log_message = pyqtSignal(str, str)
    build_status = pyqtSignal(str, str)  # running/done/error, detail
    build_result = pyqtSignal(bool, str)  # success, output path or error
    thread_added = pyqtSignal(int, str)  # slot id, masked phone label
    thread_step = pyqtSignal(int, int, float, str, str)  # slot, step, progress, status, detail
    thread_finished = pyqtSignal(int, bool, str)  # slot, success, detail
    summary = pyqtSignal(int, int, bool)  # success, total, cancelled
    inquiry_summary = pyqtSignal(int, int)  # quoted tasks, total tasks
    pxb7_expired = pyqtSignal()

    def __init__(
        self,
        accounts: list[Account],
        threads: int,
        settings: AppSettings,
        params: RunParams,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._accounts = list(accounts)
        self._threads = max(1, min(int(threads), max(1, len(self._accounts))))
        self._settings = settings
        self._params = params
        self._cancel = threading.Event()
        self._pause = threading.Event()
        self._token_provider = Pxb7BrowserYdTokenProvider(
            settings.pxb7, settings.login, self._log
        )
        self._feishu_records: list[FeishuRecord] = []
        self._feishu_temp_dir: Path | None = None
        self._output_path: Path | None = None
        self._inquiry_quoted = 0
        self._inquiry_total = 0
        self._phone_sessions: dict[str, PhoneSession] = {}
        self._phone_sessions_lock = threading.Lock()
        self._history_store = ConsultHistoryStore()
        self._proxy_settings = ProxySettings()
        self._proxy_store_error: str | None = None
        try:
            self._proxy_settings = ProxyStore().load()
        except ProxyStoreError as exc:
            self._proxy_store_error = str(exc)
            self._proxy_settings = ProxySettings(
                enabled=True, api_url="", fetch_count=5, timeout_sec=20.0
            )
        self._proxy_pool: ProxyPool | None = None
        if self._proxy_settings.enabled:
            self._proxy_pool = ProxyPool(
                self._proxy_settings, self._log
            )

    # ------------------------------------------------------------------
    # 控制
    # ------------------------------------------------------------------

    def cancel(self) -> None:
        self._cancel.set()
        self._pause.clear()

    def pause(self) -> None:
        self._pause.set()

    def resume(self) -> None:
        self._pause.clear()

    # ------------------------------------------------------------------
    # 执行
    # ------------------------------------------------------------------

    def run(self) -> None:
        total = len(self._accounts)
        if total == 0:
            self.summary.emit(0, 0, False)
            return

        default_count = sum(
            account.password_is_default for account in self._accounts
        )
        self._log(
            f"开始任务：{total} 个账号 · 线程数 {self._threads} · "
            f"账号密码登录（{default_count} 个使用默认密码）",
            "accent",
        )
        self._log(
            "流程：先构建表格，构建成功后按线程数展开工作线程。", "info"
        )
        if self._proxy_store_error:
            self._log(
                f"代理设置读取失败：{self._proxy_store_error}", "error"
            )
        if self._proxy_settings.enabled:
            self._log(
                "子线程代理已启用；飞书和右上角螃蟹商家登录保持直连。",
                "warn",
            )
        else:
            self._log("子线程代理未启用，子线程将直连。", "muted")
        if self._settings.login.browser_headless:
            self._log(
                "将通过无头 Playwright 获取易盾 token，登录请求由协议发送。",
                "warn",
            )
        else:
            self._log(
                "将通过 Playwright 获取易盾 token，登录请求由协议发送；"
                "如出现滑块，请在浏览器窗口中手动完成。",
                "warn",
            )

        if self._cancel.is_set():
            self.summary.emit(0, total, True)
            return

        # 第一步：构建表格（全局，先于线程执行）
        if not self._build_table():
            self.summary.emit(0, total, self._cancel.is_set())
            return

        if self._cancel.is_set():
            self._log("已停止：构建表格完成后未展开线程。", "warn")
            self.summary.emit(0, total, True)
            return

        # 第二步：按线程数启动固定工作线程，从账号队列取数据
        worker_count = min(self._threads, total)
        work_queue: queue.Queue = queue.Queue()
        for account in self._accounts:
            work_queue.put(account)

        results: list[bool] = []
        results_lock = threading.Lock()
        self._log(
            f"构建表格完成，展开 {worker_count} 个线程 "
            f"（并发 {worker_count}）处理 {total} 个账号…",
            "accent",
        )

        workers = [
            threading.Thread(
                target=self._worker,
                args=(slot, work_queue, results, results_lock),
                name=f"autoifq-worker-{slot}",
                daemon=True,
            )
            for slot in range(1, worker_count + 1)
        ]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join()

        cancelled = self._cancel.is_set()
        success = sum(1 for ok in results if ok)
        done = len(results)
        if cancelled:
            self._log(
                f"已停止：完成 {done}/{total}，成功 {success}", "warn"
            )
        else:
            if success:
                self._log(
                    f"螃蟹上号完成：成功 {success}/{total} 个账号",
                    "success",
                )
            else:
                self._log(
                    f"螃蟹上号结束：{total} 个账号均未登录成功", "warn"
                )
            self._run_inquiry()

        cancelled = self._cancel.is_set()
        self._cleanup_feishu_temp()
        self.summary.emit(success, total, cancelled)

    # ------------------------------------------------------------------
    # 构建表格
    # ------------------------------------------------------------------

    def _build_table(self) -> bool:
        self.build_status.emit("running", "正在读取飞书多维表格…")
        self._log(
            "开始构建表格：从飞书多维表格读取数据…", "info"
        )
        limit = self._settings.excel.copy_limit
        if limit > 0:
            self._log(
                f"测试阶段：只摘录前 {limit} 条记录。", "warn"
            )
        try:
            source = FeishuTableClient(
                self._settings.feishu, self._log
            ).fetch_records(limit=limit)
            self._feishu_records = list(source.records)
            self._feishu_temp_dir = source.temp_dir
            self._log(
                f"数据源读取完成：{source.source_name}，"
                f"源表 {source.total_records} 条，"
                f"摘录 {len(source.rows)} 条。",
                "success",
            )
            result = build_result_table(
                source.rows,
                source.source_name,
                limit=limit,
                output_dir=self._settings.excel.output_dir or None,
            )
            self._output_path = result.output_path
            if self._params.merchants:
                try:
                    add_quote_columns(
                        result.output_path, self._params.merchants
                    )
                    self._log(
                        "已为询价表格追加商家名称 / 报价列。",
                        "muted",
                    )
                except ExcelTableError as exc:
                    self._log(
                        f"追加商家报价列失败：{exc}", "error"
                    )
        except FeishuLoginRequired as exc:
            message = str(exc)
            self.build_status.emit("error", message)
            self.build_result.emit(False, message)
            self._log(f"构建表格失败：{message}", "error")
            self._cleanup_feishu_temp()
            return False
        except (FeishuTableError, ExcelTableError) as exc:
            message = str(exc)
            self.build_status.emit("error", message)
            self.build_result.emit(False, message)
            self._log(f"构建表格失败：{message}", "error")
            self._cleanup_feishu_temp()
            return False
        except Exception as exc:  # 防御性兜底
            message = f"构建表格异常：{exc}"
            self.build_status.emit("error", message)
            self.build_result.emit(False, message)
            self._log(message, "error")
            self._cleanup_feishu_temp()
            return False

        detail = (
            f"飞书 · 已摘录 {result.copied_records} 条 / "
            f"源表 {source.total_records} 条 · "
            f"{result.output_path.name}"
        )
        self.build_status.emit("done", detail)
        self.build_result.emit(True, str(result.output_path))
        self._log(
            f"构建表格完成：从「{result.source_sheet}」摘录 "
            f"{result.copied_records} 条（源表 {source.total_records} 条）。",
            "success",
        )
        self._log(f"新表格已保存：{result.output_path}", "success")
        if source.total_records > result.copied_records:
            self._log(
                f"测试阶段只摘录前 {result.copied_records} 条；"
                "将 config.json 的 excel.copy_limit 设为 0 可摘录更多。",
                "muted",
            )
        return True

    # ------------------------------------------------------------------
    # 对话聊天 / 完成询价 / 填入表格
    # ------------------------------------------------------------------

    def _run_inquiry(self) -> None:
        all_records = self._feishu_records
        merchants = list(self._params.merchants)
        if not all_records or not merchants:
            self._log(
                "没有可询价的账号或商家，跳过对话询价阶段。", "muted"
            )
            return
        if self._output_path is None:
            self._log("询价表格不存在，跳过对话询价阶段。", "error")
            return

        eligible: list[tuple[int, FeishuRecord]] = []
        skipped_for_images = 0
        for index, record in enumerate(all_records):
            if not record.screenshots:
                skipped_for_images += 1
                self._log(
                    f"跳过账号 {record.account}（第 {index + 1} 条）："
                    "账号内容图片为空，未执行聊天询价。",
                    "error",
                )
                continue
            eligible.append((index, record))

        if skipped_for_images:
            self._log(
                f"共跳过 {skipped_for_images} 条缺少账号内容图片的数据。",
                "warn",
            )
        if not eligible:
            self._log(
                "所有摘录账号都没有账号内容图片，对话询价已全部跳过。",
                "warn",
            )
            self.inquiry_summary.emit(0, 0)
            return

        with self._phone_sessions_lock:
            sessions = dict(self._phone_sessions)
        phones: list[str] = []
        for account in self._accounts:
            if account.phone in sessions and account.phone not in phones:
                phones.append(account.phone)
        if not phones:
            self._log(
                "没有成功登录的手机号聊天会话，跳过对话询价阶段。",
                "warn",
            )
            for record_index, record in eligible:
                for merchant_index, merchant in enumerate(merchants):
                    self._inquiry_total += 1
                    self._write_quote(
                        record_index,
                        merchant_index,
                        merchant,
                        None,
                    )
            self.inquiry_summary.emit(0, self._inquiry_total)
            return

        phrases = list(self._params.phrases)
        self._log(
            f"开始对话询价：{len(eligible)} 个账号 × "
            f"{len(merchants)} 个商家；可用手机号 {len(phones)} 个。",
            "accent",
        )
        if phrases:
            self._log(
                f"每次从 {len(phrases)} 条询问话术中随机选择一句。",
                "muted",
            )
        else:
            self._log("询问话术为空，将使用默认话术。", "warn")

        try:
            history = self._history_store.load()
        except ConsultHistoryStoreError as exc:
            self._log(
                f"咨询历史读取失败：{exc}；本次按空历史执行。",
                "warn",
            )
            history = {}

        assignments: dict[str, list[tuple[int, int, FeishuRecord, str]]] = {
            phone: [] for phone in phones
        }
        skipped: list[tuple[int, int, FeishuRecord, str]] = []
        for record_index, record in eligible:
            for merchant_index, merchant in enumerate(merchants):
                chosen = None
                for phone in phones:
                    if merchant not in history.get(phone, set()):
                        chosen = phone
                        break
                if chosen is None:
                    skipped.append(
                        (record_index, merchant_index, record, merchant)
                    )
                    continue
                history.setdefault(chosen, set()).add(merchant)
                assignments[chosen].append(
                    (record_index, merchant_index, record, merchant)
                )
        self._save_history(history)

        for record_index, merchant_index, record, merchant in skipped:
            self._inquiry_total += 1
            self._write_quote(
                record_index, merchant_index, merchant, None
            )
            self._log(
                f"所有手机号都已咨询过「{merchant}」，"
                f"跳过账号 {self._mask_account(record.account)}。",
                "warn",
            )

        slot = 1000
        try:
            for phone in phones:
                tasks = assignments.get(phone) or []
                if not tasks:
                    continue
                if self._cancel.is_set():
                    return
                self._log(
                    f"手机号 {mask_phone(phone)}："
                    f"分配 {len(tasks)} 个商家咨询任务。",
                    "info",
                )
                service = Pxb7ChatService(
                    self._settings,
                    self._log,
                    session=sessions[phone],
                )
                try:
                    service.__enter__()
                except Pxb7ChatCancelled:
                    raise
                except Exception as exc:
                    self._log(
                        f"手机号 {mask_phone(phone)} 聊天会话启动失败："
                        f"{exc}；该手机号任务全部跳过。",
                        "warn",
                    )
                    for (
                        record_index,
                        merchant_index,
                        record,
                        merchant,
                    ) in tasks:
                        self._inquiry_total += 1
                        self._write_quote(
                            record_index,
                            merchant_index,
                            merchant,
                            None,
                        )
                    continue

                try:
                    for (
                        record_index,
                        merchant_index,
                        record,
                        merchant,
                    ) in tasks:
                        if self._cancel.is_set():
                            return
                        current_slot = slot
                        slot += 1
                        self._inquiry_total += 1
                        label = (
                            f"{mask_phone(phone)} · "
                            f"{self._mask_account(record.account)} · "
                            f"{merchant}"
                        )
                        self.thread_added.emit(current_slot, label)
                        self.thread_step.emit(
                            current_slot,
                            0,
                            100.0,
                            StepStatus.DONE,
                            "手机号聊天会话已就绪",
                        )
                        self.thread_step.emit(
                            current_slot,
                            1,
                            10.0,
                            StepStatus.RUNNING,
                            "正在进入商家聊天坑位…",
                        )

                        phrase = (
                            random.choice(phrases) if phrases else ""
                        )
                        try:
                            result = service.inquire(
                                merchant,
                                record.screenshots,
                                phrase,
                                float(self._params.timeout_sec),
                                self._cancel,
                            )
                        except Pxb7ChatCancelled:
                            self.thread_finished.emit(
                                current_slot, False, "已取消"
                            )
                            raise
                        except Exception as exc:
                            message = str(exc)
                            self._log(
                                f"手机号 {mask_phone(phone)} · "
                                f"账号 {self._mask_account(record.account)}"
                                f" · {merchant} 询价异常，跳过：{message}",
                                "warn",
                            )
                            self.thread_step.emit(
                                current_slot,
                                1,
                                100.0,
                                StepStatus.ERROR,
                                message,
                            )
                            self._write_quote(
                                record_index,
                                merchant_index,
                                merchant,
                                None,
                            )
                            self.thread_step.emit(
                                current_slot,
                                2,
                                100.0,
                                StepStatus.ERROR,
                                "未获取到报价",
                            )
                            self.thread_step.emit(
                                current_slot,
                                3,
                                100.0,
                                StepStatus.DONE,
                                "已记录未报价",
                            )
                            self.thread_finished.emit(
                                current_slot, False, message
                            )
                        else:
                            self.thread_step.emit(
                                current_slot,
                                1,
                                100.0,
                                StepStatus.DONE,
                                "已发送账号内容图片与话术",
                            )
                            if result.price is not None:
                                self._inquiry_quoted += 1
                                self.thread_step.emit(
                                    current_slot,
                                    2,
                                    100.0,
                                    StepStatus.DONE,
                                    f"商家报价 {result.price:g}",
                                )
                            else:
                                self.thread_step.emit(
                                    current_slot,
                                    2,
                                    100.0,
                                    StepStatus.ERROR,
                                    "超时或未识别到报价",
                                )
                            self._write_quote(
                                record_index,
                                merchant_index,
                                merchant,
                                result.price,
                            )
                            self.thread_step.emit(
                                current_slot,
                                3,
                                100.0,
                                StepStatus.DONE,
                                "已填入表格",
                            )
                            detail = (
                                f"报价 {result.price:g}"
                                if result.price is not None
                                else "未报价"
                            )
                            self.thread_finished.emit(
                                current_slot,
                                result.price is not None,
                                detail,
                            )

                        if not self._sleep_interval():
                            return
                finally:
                    try:
                        service.__exit__(None, None, None)
                    except Exception:
                        pass
        except Pxb7ChatCancelled:
            self._log("询价已停止。", "warn")
        except Exception as exc:  # 防御性兜底
            self._log(f"询价阶段异常：{exc}", "error")
        finally:
            self.inquiry_summary.emit(
                self._inquiry_quoted, self._inquiry_total
            )

    def _save_history(self, history: dict[str, set[str]]) -> None:
        try:
            self._history_store.save(history)
        except ConsultHistoryStoreError as exc:
            self._log(
                f"咨询历史保存失败：{exc}；本次运行仍会避免重复。",
                "warn",
            )

    def _write_quote(
        self,
        record_index: int,
        merchant_index: int,
        merchant: str,
        price: object | None,
    ) -> None:
        if self._output_path is None:
            return
        try:
            write_quote(
                self._output_path,
                record_index,
                merchant_index,
                merchant,
                price,
            )
        except ExcelTableError as exc:
            self._log(f"写入报价失败：{exc}", "error")

    def _sleep_interval(self) -> bool:
        seconds = max(0.0, float(self._params.interval_sec))
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            if self._cancel.is_set():
                return False
            time.sleep(min(0.2, end - time.monotonic()))
        return not self._cancel.is_set()

    @staticmethod
    def _mask_account(account: str) -> str:
        text = str(account or "").strip()
        if not text:
            return "未知账号"
        if len(text) <= 4:
            return "*" * len(text)
        if len(text) <= 8:
            return text[:2] + "*" * (len(text) - 4) + text[-2:]
        return text[:3] + "*" * (len(text) - 6) + text[-3:]

    def _cleanup_feishu_temp(self) -> None:
        if self._feishu_temp_dir is None:
            return
        shutil.rmtree(self._feishu_temp_dir, ignore_errors=True)
        self._feishu_temp_dir = None

    # ------------------------------------------------------------------
    # 工作线程
    # ------------------------------------------------------------------

    def _worker(
        self,
        slot: int,
        work_queue: queue.Queue,
        results: list[bool],
        results_lock: threading.Lock,
    ) -> None:
        while True:
            if self._cancel.is_set():
                return
            try:
                account = work_queue.get_nowait()
            except queue.Empty:
                return

            while self._pause.is_set():
                if self._cancel.is_set():
                    return
                time.sleep(0.2)
            if self._cancel.is_set():
                return

            masked = mask_phone(account.phone)
            password_type = (
                "默认密码" if account.password_is_default else "自定义密码"
            )
            self.thread_added.emit(slot, masked)
            self._log(
                f"线程 {slot} 开始处理 {masked}（{password_type}）", "info"
            )

            proxy: ProxyEndpoint | None = None
            if self._proxy_settings.enabled:
                self._log(
                    f"线程 {slot} · {masked} 正在获取随机代理…",
                    "info",
                )
                try:
                    if self._proxy_pool is None:
                        raise RuntimeError("代理池未初始化")
                    proxy = self._proxy_pool.acquire()
                except Exception as exc:
                    message = f"代理获取失败：{exc}"
                    self._log(
                        f"线程 {slot} · {masked} {message}，"
                        "跳过该账号，不使用直连。",
                        "error",
                    )
                    with results_lock:
                        results.append(False)
                    self.thread_finished.emit(slot, False, message)
                    continue
                self._log(
                    f"线程 {slot} · {masked} 使用代理："
                    f"{proxy.display()}",
                    "info",
                )

            ok, detail, session = self._login_one(
                slot, account, proxy
            )
            with results_lock:
                results.append(ok)
            if ok and session is not None:
                with self._phone_sessions_lock:
                    self._phone_sessions[session.phone] = session
            self.thread_finished.emit(slot, ok, detail)

    def _login_one(
        self,
        slot: int,
        account: Account,
        proxy: ProxyEndpoint | None = None,
    ) -> tuple[bool, str, PhoneSession | None]:
        masked = mask_phone(account.phone)

        self.thread_step.emit(
            slot, 0, 5.0, StepStatus.RUNNING, "正在获取易盾 token…"
        )
        try:
            token, cookies = self._token_provider.capture(
                account.phone,
                account.password,
                self._cancel,
                proxy=proxy,
            )
            self.thread_step.emit(
                slot, 0, 55.0, StepStatus.RUNNING, "正在协议密码登录…"
            )
            client = Pxb7Client(
                self._settings.pxb7,
                account.phone,
                proxy=proxy,
            )
            client.load_cookies(cookies)
            result = client.login_with_password(
                account.phone, account.password, token
            )
        except Pxb7LoginError as exc:
            message = str(exc)
            self.thread_step.emit(
                slot, 0, 100.0, StepStatus.ERROR, message
            )
            self._log(f"线程 {slot} · {masked} 登录失败：{message}", "error")
            return False, message, None
        except Pxb7Error as exc:
            message = str(exc)
            if self._cancel.is_set():
                self._log(f"线程 {slot} · {masked} 已取消", "warn")
            else:
                self._log(
                    f"线程 {slot} · {masked} 登录异常：{message}", "error"
                )
            self.thread_step.emit(
                slot, 0, 100.0, StepStatus.ERROR, message
            )
            return False, message, None
        except Exception as exc:  # 防御性兜底
            message = f"未处理异常：{exc}"
            self.thread_step.emit(
                slot, 0, 100.0, StepStatus.ERROR, message
            )
            self._log(f"线程 {slot} · {masked} {message}", "error")
            return False, message, None

        username = result.username.strip()
        if not username:
            username = (
                f"用户{result.user_id}" if result.user_id else "未知用户"
            )
        detail = f"用户名：{username}"
        if result.user_id:
            detail += f" · 用户ID：{result.user_id}"

        self.thread_step.emit(
            slot, 0, 100.0, StepStatus.DONE, detail
        )
        self._log(
            f"线程 {slot} · {masked} 登录成功 · {detail}", "success"
        )
        if result.warning:
            self._log(f"线程 {slot} · {masked} {result.warning}", "warn")

        session = self._build_phone_session(
            account.phone,
            result.token,
            result.user_id,
            cookies,
            client,
            proxy,
        )
        if session is None:
            self._log(
                f"线程 {slot} · {masked} 未取得官网聊天会话，"
                "该手机号将不参与对话询价。",
                "warn",
            )
        else:
            self._log(
                f"线程 {slot} · {masked} 手机号聊天会话已准备。",
                "muted",
            )
        return True, detail, session

    @staticmethod
    def _build_phone_session(
        phone: str,
        token: str,
        user_id: str,
        browser_cookies: list[dict],
        client: Pxb7Client,
        proxy: ProxyEndpoint | None = None,
    ) -> PhoneSession | None:
        if not token:
            return None
        cookies: list[dict[str, str]] = []
        for cookie in browser_cookies:
            domain = str(cookie.get("domain") or "")
            name = str(cookie.get("name") or "")
            if "pxb7.com" not in domain or not name:
                continue
            cookies.append(
                {
                    "name": name,
                    "value": str(cookie.get("value") or ""),
                    "domain": domain,
                    "path": str(cookie.get("path") or "/"),
                }
            )
        cookies.extend(client.session_cookies())
        return PhoneSession(
            phone=phone,
            token=token,
            user_id=user_id,
            cookies=tuple(cookies),
            proxy=proxy,
        )

    def _log(self, message: str, level: str = "info") -> None:
        self.log_message.emit(message, level)
