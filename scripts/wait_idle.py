#!/usr/bin/env python
"""
Draw Things 空闲检测器

原理
----
Draw Things 是单任务串行的：正在生成时不接受新连接。
实测行为分两层：

- **TCP 层**：`create_connection` 永远秒通 —— **不能用来判断空闲**
  （内核 accept backlog 缓冲，不代表应用层有空）
- **TLS 层**：`wrap_socket` 握手需要应用主线程参与。
  空闲时 <100ms 完成；忙时挂起直到超时。

所以：**TLS 握手能否在短超时内完成 = 空闲的可靠判据**。

这个探测极轻量（只做 TLS 握手，不发任何 RPC），
不会给正在生成的任务增加负担，可安全高频调用。

用法
----
    # 轮询直到空闲（默认最长等5 分钟）
    python scripts/wait_idle.py

    # 只查一次
    python scripts/wait_idle.py --once

    # 自定义超时与轮询间隔
    python scripts/wait_idle.py --timeout 120 --interval 5

    # 持续监控（Ctrl+C 退出）
    python scripts/wait_idle.py --watch
"""

import argparse
import os
import socket
import ssl
import sys
import time

# 空闲判据：TLS 握手在这个时间内完成即视为空闲
IDLE_HANDSHAKE_SEC = 1.5


def probe(host, port, timeout=IDLE_HANDSHAKE_SEC):
    """探测 Draw Things 是否空闲

    Args:
        host (str): 主机地址
        port (int): 端口
        timeout (float): TLS 握手超时（秒），超时即视为忙

    Returns:
        tuple: (is_idle, status_text)
    """
    # TCP 层：只能说明端口在监听，不能说明空闲
    try:
        probe_sock = socket.create_connection((host, port), timeout=1.0)
        probe_sock.close()
    except Exception as e:
        return False, f"TCP 不通 ({type(e).__name__})"

    # TLS 层：真正的空闲判据
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

    try:
        raw = socket.create_connection((host, port), timeout=timeout)
    except Exception as e:
        return False, f"TCP 超时 ({type(e).__name__})"

    try:
        t0 = time.time()
        tls = ctx.wrap_socket(raw, server_hostname="localhost")
        elapsed = time.time() - t0
        version = tls.version()
        tls.close()

        if elapsed < 0.5:
            return True, f"空闲 (握手 {elapsed*1000:.0f}ms, {version})"
        return True, f"空闲 (握手 {elapsed:.2f}s, {version})"
    except ssl.SSLError as e:
        return False, f"忙/状态异常 ({type(e).__name__})"
    except socket.timeout:
        return False, "忙 (TLS 握手超时)"
    except Exception as e:
        return False, f"忙 ({type(e).__name__})"


def wait_until_idle(host, port, max_wait=300, interval=4, verbose=True):
    """轮询直到空闲

    Args:
        host (str): 主机
        port (int): 端口
        max_wait (int): 最长等待秒数
        interval (int): 轮询间隔
        verbose (bool): 是否打印进度

    Returns:
        bool: 空闲返回 True，超时返回 False
    """
    start = time.time()
    attempt = 0

    while time.time() - start < max_wait:
        attempt += 1
        is_idle, status = probe(host, port)

        if is_idle:
            if verbose:
                print(f"[{attempt}] ✓ 空闲 — {status}")
            return True

        if verbose:
            elapsed = int(time.time() - start)
            print(f"[{attempt}] … {status}  ({elapsed}s/{max_wait}s)")

        time.sleep(interval)

    if verbose:
        print(f"\n等待超时（{max_wait}s）仍未空闲。")
        print("Draw Things 可能已卡死，建议强制退出重启（Cmd+Q 或 Cmd+Option+Esc）。")
    return False


def watch(host, port, interval=5):
    """持续监控空闲状态"""
    print(f"监控 {host}:{port} 的空闲状态（Ctrl+C 退出）\n")
    idle_since = None
    try:
        while True:
            is_idle, status = probe(host, port)
            mark = "✓ 空闲" if is_idle else "… 忙"
            now = time.strftime("%H:%M:%S")
            print(f"[{now}] {mark}  {status}")

            if is_idle and idle_since is None:
                idle_since = time.time()
                print("        ↑ 开始空闲")
            elif not is_idle and idle_since is not None:
                idle_since = None
                print("        ↓ 进入忙碌")

            time.sleep(interval)
    except KeyboardInterrupt:
        print("\n已退出监控")


def main():
    parser = argparse.ArgumentParser(
        description="检测 Draw Things 是否空闲",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""判据说明：
  TCP 能连 ≠ 空闲（内核缓冲，应用层可能正忙）
  TLS 握手完成 = 空闲（需要应用主线程参与）

示例：
  python scripts/wait_idle.py                # 等到空闲（最长 5 分钟）
  python scripts/wait_idle.py --once          # 只查一次
  python scripts/wait_idle.py --watch         # 持续监控
  python scripts/wait_idle.py --port 7859     # 指定端口
""")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=7888)
    parser.add_argument("--once", action="store_true", help="只检测一次")
    parser.add_argument("--watch", action="store_true", help="持续监控")
    parser.add_argument("--max-wait", type=int, default=300, help="最长等待秒数")
    parser.add_argument("--interval", type=int, default=4, help="轮询间隔秒数")
    parser.add_argument("--timeout", type=float, default=IDLE_HANDSHAKE_SEC,
                        help="TLS 握手超时（超过即视为忙）")
    args = parser.parse_args()

    if args.once:
        is_idle, status = probe(args.host, args.port, args.timeout)
        print(f"{'✓ 空闲' if is_idle else '✗ 忙'} — {status}")
        return 0 if is_idle else 1

    if args.watch:
        watch(args.host, args.port, args.interval)
        return 0

    ok = wait_until_idle(
        args.host, args.port,
        max_wait=args.max_wait,
        interval=args.interval,
    )
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())