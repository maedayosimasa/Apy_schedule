"""Box Driveの共有フォルダを監視し、DB更新を検知するQThreadベースのウォッチャー。"""
from __future__ import annotations
from pathlib import Path
import time

from PyQt5.QtCore import QThread, pyqtSignal

try:
    from watchdog.observers import Observer
    from watchdog.events import FileSystemEventHandler
    _WATCHDOG_AVAILABLE = True
except ImportError:
    _WATCHDOG_AVAILABLE = False


if _WATCHDOG_AVAILABLE:
    class _DbEventHandler(FileSystemEventHandler):
        """*.dbファイルの変更イベントをデバウンスして収集する。"""
        _DEBOUNCE_SEC = 0.8   # Box書き込み完了を待つバッファ時間

        def __init__(self):
            self._pending: dict[str, float] = {}   # path -> 最終イベント時刻

        def on_modified(self, event):
            if not event.is_directory and event.src_path.lower().endswith(".db"):
                self._pending[event.src_path] = time.monotonic()

        on_created = on_modified   # 新規DBファイルも監視対象に

        def drain(self) -> list[str]:
            """デバウンス経過済みのパスを返し、pendingから削除する。"""
            now   = time.monotonic()
            ready = [p for p, t in self._pending.items()
                     if now - t >= self._DEBOUNCE_SEC]
            for p in ready:
                del self._pending[p]
            return ready


class DbWatcherThread(QThread):
    """共有フォルダを監視し、*.db変更時にシグナルを発火するスレッド。"""

    db_updated = pyqtSignal(str)   # 変更されたDBファイルのフルパスを通知

    def __init__(self, watch_dir: Path, parent=None):
        super().__init__(parent)
        self._watch_dir = watch_dir
        self._running   = True

    def run(self):
        if not _WATCHDOG_AVAILABLE:
            return   # watchdog未インストール時はポーリングなし（graceful degradation）

        handler  = _DbEventHandler()
        observer = Observer()
        observer.schedule(handler, str(self._watch_dir), recursive=False)
        observer.start()
        try:
            while self._running:
                time.sleep(0.2)
                for path in handler.drain():
                    self.db_updated.emit(path)
        finally:
            observer.stop()
            observer.join()

    def stop(self):
        self._running = False
        self.wait(3000)   # 最大3秒待機してスレッドを終了
