#!/usr/bin/env python
"""
Draw Things gRPC 诊断工具

只发轻量请求（Echo），不发生图，不会给服务端造成压力。

用法：
    # 1. 只检查服务是否可用（推荐，最安全）
    python scripts/grpc_doctor.py

    # 2. 检查并打印详细信息
    python scripts/grpc_doctor.py --verbose

    # 3. 指定端口
    python scripts/grpc_doctor.py --port 7859

在 Draw Things 完全空闲时运行。若显示"可用"，再进行生图联调。
"""

import argparse
import os
import socket
import ssl
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def check_tcp(host, port, timeout=3):
    """TCP 层探测"""
    try:
        s = socket.create_connection((host, port), timeout=timeout)
        s.close()
        return True, "可连接"
    except Exception as e:
        return False, f"{type(e).__name__}"


def check_tls(host, port, timeout=5):
    """TLS 握手探测（用服务端证书，不校验）"""
    try:
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        raw = socket.create_connection((host, port), timeout=timeout)
        t0 = time.time()
        tls = ctx.wrap_socket(raw, server_hostname="localhost")
        elapsed = time.time() - t0
        version = tls.version()
        tls.close()
        return True, f"{version}, 耗时 {elapsed:.2f}s"
    except Exception as e:
        return False, type(e).__name__


def check_grpc(host, port, timeout=15):
    """真实 gRPC Echo 调用"""
    try:
        import grpc

        from src.grpc_gen import imageService_pb2 as pb2
        from src.grpc_gen import imageService_pb2_grpc as pb2_grpc
        from src.drawthings_ca import _cert, SSL_TARGET_NAME

        opts = [
            ("grpc.enable_http_proxy", 0),
            ("grpc.ssl_target_name_override", SSL_TARGET_NAME),
        ]
        creds = grpc.ssl_channel_credentials(root_certificates=_cert)
        channel = grpc.secure_channel(f"{host}:{port}", creds, options=opts)
        stub = pb2_grpc.ImageGenerationServiceStub(channel)

        t0 = time.time()
        resp = stub.Echo(pb2.EchoRequest(name="doctor"), timeout=timeout)
        elapsed = time.time() - t0

        secret_missing = resp.sharedSecretMissing

        # 解析资产清单（若服务端启用了 Model Browser 才有内容）
        assets = {"models": [], "loras": [], "control_nets": [],
                  "textual_inversions": [], "upscalers": []}
        if resp.HasField("override"):
            from src.grpc_client import _decode_asset_list
            ov = resp.override
            for proto_field, key in [
                ("models", "models"),
                ("loras", "loras"),
                ("controlNets", "control_nets"),
                ("textualInversions", "textual_inversions"),
                ("upscalers", "upscalers"),
            ]:
                raw = getattr(ov, proto_field, b"")
                if raw:
                    assets[key] = _decode_asset_list(raw)

        channel.close()
        return True, {
            "message": resp.message,
            "files": len(resp.files),
            "elapsed": elapsed,
            "secret_missing": secret_missing,
            "assets": assets,
            "file_names": list(resp.files),
        }
    except Exception as e:
        code = ""
        if hasattr(e, "code"):
            try:
                code = e.code().name
            except Exception:
                pass
        return False, f"{code or type(e).__name__}"


def main():
    parser = argparse.ArgumentParser(description="Draw Things gRPC 诊断")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=7888)
    parser.add_argument("--verbose", action="store_true", help="打印详细信息")
    parser.add_argument("--timeout", type=int, default=15)
    args = parser.parse_args()

    print(f"诊断 Draw Things gRPC: {args.host}:{args.port}\n")

    # TCP
    ok, msg = check_tcp(args.host, args.port)
    print(f"[1/3] TCP      {'✓' if ok else '✗'} {msg}")
    if not ok:
        print("\n诊断：端口不通。确认 Draw Things 已启动且 API Server 已开启。")
        return 1

    # TLS
    ok, msg = check_tls(args.host, args.port)
    print(f"[2/3] TLS      {'✓' if ok else '✗'} {msg}")
    if not ok:
        print("\n诊断：TCP 通但 TLS 失败。")
        print("      · 若 Draw Things 正在生成，界面会有响应但握手会卡住 -> 等它空闲")
        print("      · 若一直失败，检查 Protocol 是否设为 gRPC")
        return 1

    # gRPC
    ok, msg = check_grpc(args.host, args.port, timeout=args.timeout)
    if ok:
        print(f"[3/3] gRPC Echo ✓ {msg['message']}")
        print(f"      耗时 {msg['elapsed']:.2f}s | 可用模型 {msg['files']} 个")
        if msg["secret_missing"]:
            print("\n⚠️  服务端提示缺少 Shared Secret！")
            print("    需要在 Draw Things 设置里查看密钥，配置到 client 的 shared_secret。")

        assets = msg.get("assets", {})
        total_assets = sum(len(v) for v in assets.values())
        if total_assets:
            print("\n      资产清单（MetadataOverride）：")
            for key in ("models", "loras", "control_nets",
                        "textual_inversions", "upscalers"):
                items = assets.get(key) or []
                if items:
                    label = key.replace("_", " ")
                    preview = ", ".join(items[:4])
                    more = f" ...共 {len(items)} 个" if len(items) > 4 else ""
                    print(f"        {label:20} {len(items):3}个: {preview}{more}")
            print("      注：需要开启 Model Browser 才有这些分类清单")
        else:
            print("      （MetadataOverride 为空，服务端未开启 Model Browser）")

        if args.verbose:
            print(f"\n      全部文件（{len(msg['file_names'])} 个）：")
            for name in msg["file_names"]:
                print(f"        - {name}")

        print("\n结论：gRPC 可用，可以进行生图联调。")
        return 0
    else:
        print(f"[3/3] gRPC Echo ✗ {msg}")
        print("\n诊断：TLS 正常但 gRPC 无响应。")
        print("      · 服务端可能正忙（单任务串行），等空闲后重试")
        print("      · 若需要 Shared Secret，配置后再试")
        print("      · 建议加长 --timeout（如 --timeout 30）")
        return 1


if __name__ == "__main__":
    sys.exit(main())