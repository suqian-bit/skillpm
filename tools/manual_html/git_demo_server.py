#!/usr/bin/env python3
"""录「接入自己的仓库」截图用的本机 git 服务：真的 git 智能 HTTP 协议（git http-backend），
当作「别的团队的 GitLab」。git 通过 http.<url>.proxy 把 gitlab.example.com 的请求发到这里，
所以截图里显示的是文档里一直用的示例地址。

- <根>/ops/skills.git   公开仓库
- <根>/ops/private.git  私有仓库：要带「oauth2:<令牌>」的 Basic 认证（和 GitLab 一样），否则 401

用法：python3 git_demo_server.py <仓库根目录> <端口> <令牌>
"""
import base64
import os
import subprocess
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

ROOT, PORT, TOKEN = sys.argv[1], int(sys.argv[2]), sys.argv[3]
PRIVATE = "/ops/private.git"


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _serve(self):
        u = urlsplit(self.path)                      # 代理请求是绝对地址 http://gitlab.example.com/...
        path = u.path
        if path.startswith(PRIVATE):
            want = "Basic " + base64.b64encode(f"oauth2:{TOKEN}".encode()).decode()
            if self.headers.get("Authorization") != want:
                self.send_response(401)
                self.send_header("WWW-Authenticate", 'Basic realm="GitLab"')
                self.end_headers()
                return
        repo_dir = path.split(".git", 1)[0] + ".git"
        if not os.path.isdir(ROOT + repo_dir):
            self.send_response(404)
            self.end_headers()
            return
        body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        env = {**os.environ, "GIT_PROJECT_ROOT": ROOT, "GIT_HTTP_EXPORT_ALL": "1",
               "PATH_INFO": path, "QUERY_STRING": u.query, "REQUEST_METHOD": self.command,
               "CONTENT_TYPE": self.headers.get("Content-Type", ""), "CONTENT_LENGTH": str(len(body)),
               "REMOTE_USER": "demo", "REMOTE_ADDR": "127.0.0.1"}
        out = subprocess.run(["git", "http-backend"], input=body, env=env, capture_output=True).stdout
        head, _, payload = out.partition(b"\r\n\r\n")
        status = 200
        headers = []
        for line in head.decode("latin-1").split("\r\n"):
            k, _, v = line.partition(":")
            if k.lower() == "status":
                status = int(v.strip().split()[0])
            elif k:
                headers.append((k, v.strip()))
        self.send_response(status)
        for k, v in headers:
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    do_GET = do_POST = _serve


if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
