"""WeChat File Transfer HTTPS adapter; no browser, hooks or injected code.

Protocol references: zzzzls/WXFileHelper and littlecodersh/ItChat (MIT).
See THIRD_PARTY_NOTICES.md. Login credentials exist only in memory.
SPDX-License-Identifier: AGPL-3.0-only
"""
from __future__ import annotations

import hashlib
import html
import json
import mimetypes
import os
import re
import secrets
import stat
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit
from xml.etree.ElementTree import Element, SubElement, tostring

import requests
from defusedxml.ElementTree import fromstring

ROOT = "/cgi-bin/mmwebwx-bin/"
REGIONS = {
    "filehelper.weixin.qq.com": ("login.wx.qq.com", "file.wx.qq.com"),
    "szfilehelper.weixin.qq.com": ("login.wx2.qq.com", "file.wx2.qq.com"),
    "cmfilehelper.weixin.qq.com": ("login.wx8.qq.com", "file.wx8.qq.com"),
}
ALLOWED_HOSTS = frozenset(REGIONS) | frozenset(h for pair in REGIONS.values() for h in pair)
CHUNK_SIZE = 512 * 1024
MAX_FILE_SIZE = 25 * 1024 * 1024


class ProtocolError(Exception):
    """Safe displayable error: never contains request URLs or credentials."""


class SessionExpired(ProtocolError):
    pass


class Cancelled(ProtocolError):
    pass


def safe_url(url: str, *, login: bool = False) -> str:
    p = urlsplit(url)
    if (p.scheme != "https" or p.hostname not in ALLOWED_HOSTS or p.username
            or p.password or p.port not in (None, 443) or p.fragment):
        raise ProtocolError("Rejected an untrusted service address / 已拒绝不可信服务地址")
    if login and (p.hostname not in REGIONS or p.path != ROOT + "webwxnewloginpage"):
        raise ProtocolError("Unexpected login destination / 登录返回地址异常")
    return url


def safe_filename(name: str) -> str:
    name = re.split(r"[/\\]", name)[-1]
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).strip(" .")[:180]
    if not name:
        name = "download"
    if name.split(".")[0].upper() in {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}:
        name = "_" + name
    return name


def plain_text(value: str) -> str:
    return html.unescape(re.sub(r"<br\s*/?>", "\n", value, flags=re.I))


@dataclass
class Message:
    id: str
    kind: str
    text: str
    outgoing: bool = False
    timestamp: int = field(default_factory=lambda: int(time.time()))
    size: int = 0
    media_id: str = ""
    sender: str = ""
    local_path: str = ""


def parse_message(raw: dict, username: str) -> Message | None:
    if "filehelper" not in (raw.get("FromUserName"), raw.get("ToUserName")):
        return None
    msg_id = str(raw.get("NewMsgId") or raw.get("MsgId") or "")
    if not msg_id:
        return None
    kind = int(raw.get("MsgType", 0))
    content = str(raw.get("Content", ""))
    # Both phone and desktop use the same account username. Only a locally
    # acknowledged send is marked outgoing; sync alone cannot identify the device.
    message = Message(msg_id, "text", plain_text(content), False,
                      int(raw.get("CreateTime") or time.time()),
                      sender=str(raw.get("FromUserName", "")))
    if kind == 1:
        return message
    if kind in (3, 43, 62, 34, 47):
        message.kind = {3: "image", 43: "video", 62: "video", 34: "voice", 47: "unsupported"}[kind]
        extension = {3: "jpg", 43: "mp4", 62: "mp4", 34: "silk", 47: "txt"}[kind]
        message.text = f"{message.kind}-{msg_id}.{extension}"
        return message
    if kind == 49:
        try:
            # Some servers HTML-escape the entire XML, others send literal XML.
            xml = content if content.lstrip().startswith("<") else html.unescape(content)
            root = fromstring(xml)
            app = root if root.tag == "appmsg" else root.find("appmsg")
            if app is None:
                raise ValueError("missing appmsg")
            title = app.findtext("title") or raw.get("FileName") or "file"
            if app.findtext("type") == "6":
                message.kind = "file"
                message.text = safe_filename(title)
                message.media_id = app.findtext("appattach/attachid") or str(raw.get("MediaId", ""))
                message.size = max(0, int(app.findtext("appattach/totallen") or raw.get("FileSize") or 0))
            else:
                message.text = title + "\n" + (app.findtext("des") or "")
            return message
        except Exception:
            message.kind = "unsupported"
            message.text = "无法解析此消息，请在手机微信查看 / Open this message on your phone"
            return message
    if kind in (51, 10000, 10002):
        return None
    message.kind = "unsupported"
    message.text = "暂不支持此消息类型，请在手机微信查看 / View this message on your phone"
    return message


def file_message_xml(name: str, size: int, media_id: str) -> str:
    root = Element("appmsg", {"appid": "wxeb7ec651dd0aefa9", "sdkver": ""})
    for key, value in (("title", name), ("des", ""), ("action", ""), ("type", "6"),
                       ("content", ""), ("url", ""), ("lowurl", "")):
        SubElement(root, key).text = value
    attach = SubElement(root, "appattach")
    for key, value in (("totallen", str(size)), ("attachid", media_id),
                       ("fileext", Path(name).suffix.lstrip("."))):
        SubElement(attach, key).text = value
    SubElement(root, "extinfo")
    return tostring(root, encoding="unicode")


class FileHelperClient:
    def __init__(self, entry_host: str = "szfilehelper.weixin.qq.com"):
        if entry_host not in REGIONS:
            raise ValueError("Unsupported region")
        self.entry_host = entry_host
        self.login_host, self.file_host = REGIONS[entry_host]
        self.device = "e" + "".join(str(secrets.randbelow(10)) for _ in range(15))
        self.uuid = ""
        self.sid = self.skey = self.uin = self.ticket = self.username = self.nickname = ""
        self.sync_key: dict = {"Count": 0, "List": []}
        self.check_key: dict = self.sync_key
        self._local = threading.local()
        self._cookies = requests.cookies.RequestsCookieJar()
        self._sessions: list[requests.Session] = []
        self._session_lock = threading.Lock()
        self.cancel = threading.Event()
        self.logged_in = False

    def _http(self) -> requests.Session:
        if not hasattr(self._local, "session"):
            session = requests.Session()
            session.headers.update({
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131.0.0.0 Safari/537.36",
                "Accept": "*/*", "mmweb_appid": "wx_webfilehelper",
                "Referer": f"https://{self.entry_host}/", "Origin": f"https://{self.entry_host}",
            })
            session.cookies.update(self._cookies)
            self._local.session = session
            with self._session_lock:
                self._sessions.append(session)
        return self._local.session

    def _request(self, method: str, url: str, **kwargs):
        if self.cancel.is_set():
            raise Cancelled("Cancelled / 已取消")
        safe_url(url)
        try:
            response = self._http().request(method, url, timeout=kwargs.pop("timeout", (10, 40)),
                                            allow_redirects=False, **kwargs)
            if response.status_code not in (200, 206):
                response.close()
                raise ProtocolError(f"Service HTTP {response.status_code} / 服务请求失败，请稍后重试")
            return response
        except requests.Timeout:
            raise ProtocolError("Network timeout; try again / 网络超时，请重试") from None
        except requests.RequestException:
            raise ProtocolError("Cannot reach WeChat; check your network / 无法连接微信，请检查网络") from None

    @property
    def base(self) -> dict:
        return {"Uin": int(self.uin), "Sid": self.sid, "Skey": self.skey, "DeviceID": self.device}

    def _api(self, endpoint: str, data: dict, **params) -> dict:
        with self._request("POST", f"https://{self.entry_host}{ROOT}{endpoint}",
                           params={"lang": "zh_CN", "pass_ticket": self.ticket, **params},
                           data=json.dumps(data, ensure_ascii=False).encode("utf-8"),
                           headers={"Content-Type": "application/json; charset=UTF-8"}) as response:
            try:
                result = json.loads(response.content.decode("utf-8"))
            except (ValueError, UnicodeError):
                raise ProtocolError("Unexpected service response / 服务返回格式异常") from None
        self._check(result)
        return result

    @staticmethod
    def _check(result: dict):
        code = result.get("BaseResponse", {}).get("Ret", -1)
        if code in (1100, 1101, 1102, 1205):
            raise SessionExpired("Session expired; scan again / 登录已失效，请重新扫码")
        if code != 0:
            raise ProtocolError(f"WeChat rejected request ({code}) / 微信未接受请求，请稍后重试")

    def create_qr(self) -> bytes:
        redirect = quote(f"https://{self.entry_host}{ROOT}webwxnewloginpage", safe="")
        with self._request("GET", f"https://{self.login_host}/jslogin", params={
                "appid": "wx_webfilehelper", "redirect_uri": redirect,
                "fun": "new", "lang": "zh_CN", "_": int(time.time() * 1000)}) as response:
            match = re.search(r'window\.QRLogin\.uuid\s*=\s*"([\w=-]+)"', response.text)
        if not match:
            raise ProtocolError("Unable to obtain login code / 无法获取登录二维码")
        self.uuid = match.group(1)
        with self._request("GET", f"https://{self.login_host}/qrcode/{self.uuid}") as response:
            if len(response.content) > 2 * 1024 * 1024:
                raise ProtocolError("Invalid QR image / 二维码异常")
            return response.content

    def poll_login(self, scanned: bool = False) -> str:
        with self._request("GET", f"https://{self.login_host}{ROOT}login", params={
                "loginicon": "true", "uuid": self.uuid, "tip": 0 if scanned else 1,
                "appid": "wx_webfilehelper", "_": int(time.time() * 1000)}) as response:
            body = response.text
        match = re.search(r"window\.code\s*=\s*(\d+)", body)
        if not match:
            raise ProtocolError("Unexpected login response / 登录响应异常")
        code = int(match.group(1))
        if code == 200:
            match = re.search(r'window\.redirect_uri\s*=\s*"([^"]+)"', body)
            if not match:
                raise ProtocolError("Missing login destination / 缺少登录返回地址")
            self._finish_login(html.unescape(match.group(1)))
            return "online"
        if code == 201:
            return "confirm"
        if code == 408:
            return "waiting"
        if code in (400, 500):
            return "expired"
        raise ProtocolError(f"Login unavailable ({code}) / 当前无法登录")

    def _finish_login(self, redirect: str):
        safe_url(redirect, login=True)
        p = urlsplit(redirect)
        self.entry_host = p.hostname
        self.login_host, self.file_host = REGIONS[self.entry_host]
        query = dict(parse_qsl(p.query))
        query.update(fun="new", version="v2")
        url = urlunsplit((p.scheme, p.netloc, p.path, urlencode(query), ""))
        with self._request("GET", url) as response:
            try:
                root = fromstring(response.content)
            except Exception:
                raise ProtocolError("Invalid login response / 登录响应无效") from None
        if root.findtext("ret") not in (None, "0"):
            raise ProtocolError("Login not accepted / 微信未接受本次登录")
        self.skey, self.sid, self.uin, self.ticket = (root.findtext(k) or "" for k in ("skey", "wxsid", "wxuin", "pass_ticket"))
        if not all((self.skey, self.sid, self.uin, self.ticket)) or not self.uin.isdigit():
            raise ProtocolError("Incomplete login response / 登录信息不完整")
        self._http().headers.update(Referer=f"https://{self.entry_host}/", Origin=f"https://{self.entry_host}")
        self._cookies = self._http().cookies.copy()
        result = self._api("webwxinit", {"BaseRequest": self.base}, r=int(time.time()))
        self.username = result.get("User", {}).get("UserName", "")
        self.nickname = plain_text(result.get("User", {}).get("NickName", ""))
        self.sync_key = result.get("SyncKey") or {"Count": 0, "List": []}
        self.check_key = result.get("SyncCheckKey") or self.sync_key
        if not self.username or not self.sync_key.get("List"):
            raise ProtocolError("Session initialization failed / 会话初始化失败")
        self._cookies = self._http().cookies.copy()
        self.logged_in = True

    def receive(self) -> list[Message]:
        key = "|".join(f"{item['Key']}_{item['Val']}" for item in self.check_key["List"])
        with self._request("GET", f"https://{self.entry_host}{ROOT}synccheck", params={
                "r": int(time.time() * 1000), "skey": self.skey, "sid": self.sid,
                "uin": self.uin, "deviceid": self.device, "synckey": key,
                "mmweb_appid": "wx_webfilehelper"}) as response:
            match = re.search(r'retcode\s*:\s*"(\d+)"\s*,\s*selector\s*:\s*"(\d+)"', response.text)
        if not match:
            raise ProtocolError("Unexpected sync response / 同步响应异常")
        code, selector = match.groups()
        self._check({"BaseResponse": {"Ret": int(code)}})
        if selector == "0":
            return []
        messages = []
        for _ in range(20):  # Drain ContinueFlag without an unbounded tight loop.
            result = self._api("webwxsync", {"BaseRequest": self.base, "SyncKey": self.sync_key,
                                            "rr": ~int(time.time())}, sid=self.sid, skey=self.skey)
            if result.get("SyncKey", {}).get("List"):
                self.sync_key = result["SyncKey"]
            self.check_key = result.get("SyncCheckKey") or self.sync_key
            for raw in result.get("AddMsgList", []):
                msg = parse_message(raw, self.username)
                if msg is not None:
                    messages.append(msg)
            if not result.get("ContinueFlag"):
                break
        return messages

    def _send(self, kind: int, content: str = "", media: str = "") -> str:
        if not self.logged_in:
            raise SessionExpired("Scan to sign in first / 请先扫码登录")
        local_id = str(time.time_ns() // 1000) + f"{secrets.randbelow(1000):03d}"
        message = {"Type": kind, "Content": content, "FromUserName": self.username,
                   "ToUserName": "filehelper", "LocalID": local_id, "ClientMsgId": local_id}
        if media:
            message["MediaId"] = media
        endpoint = {1: "webwxsendmsg", 3: "webwxsendmsgimg", 6: "webwxsendappmsg"}[kind]
        result = self._api(endpoint, {"BaseRequest": self.base, "Msg": message, "Scene": 0}, fun="async", f="json")
        return str(result.get("MsgID") or result.get("MsgId") or local_id)

    def send_text(self, text: str) -> Message:
        if not text.strip() or len(text) > 10000:
            raise ProtocolError("Text must contain 1–10000 characters / 文字长度需为 1–10000 字符")
        return Message(self._send(1, text), "text", text, outgoing=True)

    def send_file(self, path: Path, progress=lambda value: None, *, image: bool = False) -> Message:
        path = Path(path)
        if not path.is_file():
            raise ProtocolError("File is unavailable / 文件不存在或不可读取")
        if not self.logged_in:
            raise SessionExpired("Scan to sign in first / 请先扫码登录")
        data_ticket = next((c.value for c in self._cookies if c.name == "webwx_data_ticket"), "")
        if not data_ticket:
            raise SessionExpired("Missing upload authorization; scan again / 上传授权失效，请重新扫码")
        mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        image = image and mime in ("image/png", "image/jpeg", "image/bmp")
        media_id = ""
        with path.open("rb") as source:
            info = os.fstat(source.fileno())
            size = info.st_size
            if not stat.S_ISREG(info.st_mode) or not 0 < size <= MAX_FILE_SIZE:
                raise ProtocolError("This version supports files from 1 byte to 25 MiB / 本版支持 1 字节至 25 MiB 文件")
            chunks = (size + CHUNK_SIZE - 1) // CHUNK_SIZE
            changed = "File changed while sending; save it and try again / 文件在发送时发生变化，请保存后重试"
            digest = hashlib.md5(usedforsecurity=False)
            for index in range(chunks):
                if self.cancel.is_set():
                    raise Cancelled("Cancelled / 已取消")
                count = min(CHUNK_SIZE, size - index * CHUNK_SIZE)
                data = source.read(count)
                if len(data) != count:
                    raise ProtocolError(changed)
                digest.update(data)
            source.seek(0)
            request = {"UploadType": 2, "BaseRequest": self.base, "ClientMediaId": int(time.time() * 1000),
                       "TotalLen": size, "StartPos": 0, "DataLen": size, "MediaType": 4,
                       "FromUserName": self.username, "ToUserName": "filehelper", "FileMd5": digest.hexdigest()}
            modified = time.strftime("%a %b %d %Y %H:%M:%S GMT+0000", time.gmtime(info.st_mtime))
            for index in range(chunks):
                count = min(CHUNK_SIZE, size - index * CHUNK_SIZE)
                data = source.read(count)
                current = os.fstat(source.fileno())
                if len(data) != count or (current.st_size, current.st_mtime_ns) != (size, info.st_mtime_ns):
                    raise ProtocolError(changed)
                fields = {"id": "WU_FILE_0", "name": path.name, "type": mime,
                          "lastModifiedDate": modified,
                          "size": str(size), "mediatype": "pic" if image else "doc",
                          "uploadmediarequest": json.dumps(request, ensure_ascii=False),
                          "webwx_data_ticket": data_ticket, "pass_ticket": self.ticket}
                if chunks > 1:
                    fields.update(chunks=str(chunks), chunk=str(index))
                multipart = {key: (None, value) for key, value in fields.items()}
                multipart["filename"] = (path.name, data, mime)
                with self._request("POST", f"https://{self.file_host}{ROOT}webwxuploadmedia",
                                   params={"f": "json"}, files=multipart) as response:
                    try:
                        result = response.json()
                    except ValueError:
                        raise ProtocolError("Invalid upload response / 上传响应异常") from None
                self._check(result)
                media_id = result.get("MediaId")
                progress(min(95, int((index + 1) / chunks * 95)))
            current = os.fstat(source.fileno())
            if (current.st_size, current.st_mtime_ns) != (size, info.st_mtime_ns):
                raise ProtocolError(changed)
        if not media_id:
            raise ProtocolError("Upload did not return a file ID / 上传未返回文件标识")
        msg_id = self._send(3, media=media_id) if image else self._send(6, file_message_xml(path.name, size, media_id))
        progress(100)
        return Message(msg_id, "image" if image else "file", path.name, outgoing=True,
                       size=size, media_id=media_id, local_path=str(path.resolve()))

    def download(self, message: Message, target: Path, progress=lambda value: None) -> Path:
        params = {"skey": self.skey, "pass_ticket": self.ticket}
        host = self.entry_host
        if message.kind == "file":
            if not message.media_id:
                raise ProtocolError("File is no longer available; resend it from your phone / 文件已不可用，请从手机重新发送")
            host = self.file_host
            endpoint = "webwxgetmedia"
            params.update(sender=message.sender, mediaid=message.media_id,
                          filename=message.text, fromuser=self.uin,
                          webwx_data_ticket=next((c.value for c in self._cookies if c.name == "webwx_data_ticket"), ""))
        elif message.kind in ("image", "video", "voice"):
            endpoint = {"image": "webwxgetmsgimg", "video": "webwxgetvideo", "voice": "webwxgetvoice"}[message.kind]
            params.update(MsgID=message.id)
        else:
            raise ProtocolError("This message cannot be downloaded / 此消息不支持下载")
        target = Path(target)
        temporary = target.with_name(target.name + "." + secrets.token_hex(6) + ".part")
        headers = {"Accept-Encoding": "identity"}
        if message.kind == "video":
            headers["Range"] = "bytes=0-"
        try:
            with self._request("GET", f"https://{host}{ROOT}{endpoint}", params=params,
                               stream=True, headers=headers) as response:
                total = int(response.headers.get("Content-Length", 0)) if response.headers.get(
                    "Content-Encoding", "identity") == "identity" else 0
                if response.status_code == 206:
                    content_range = re.fullmatch(r"bytes 0-(\d+)/(\d+)", response.headers.get("Content-Range", ""))
                    if not content_range or int(content_range[1]) + 1 != int(content_range[2]):
                        raise ProtocolError("Incomplete download / 下载不完整，请重试")
                    total = int(content_range[2])
                received = 0
                with temporary.open("xb") as output:
                    for block in response.iter_content(64 * 1024):
                        if self.cancel.is_set():
                            raise Cancelled("Cancelled / 已取消")
                        if received == 0 and self._download_error(block):
                            raise ProtocolError("File expired or service rejected download / 文件已过期或服务拒绝下载")
                        output.write(block)
                        received += len(block)
                        if total:
                            progress(min(99, int(received / total * 100)))
                if total and received != total:
                    raise ProtocolError("Incomplete download / 下载不完整，请重试")
                if received == 0:
                    raise ProtocolError("Empty download response / 下载内容为空")
            temporary.replace(target)
            progress(100)
            return target
        finally:
            temporary.unlink(missing_ok=True)

    @staticmethod
    def _download_error(block: bytes) -> bool:
        """Detect protocol errors without rejecting legitimate HTML/XML/JSON files."""
        head = block.lstrip()
        if head.startswith(b"{"):
            try:
                data = json.loads(head)
                return isinstance(data, dict) and "BaseResponse" in data and data["BaseResponse"].get("Ret", 0) != 0
            except (ValueError, AttributeError):
                return False
        if head.startswith((b"<error>", b"<?xml")):
            try:
                root = fromstring(head)
                return root.tag == "error" and root.findtext("ret") not in (None, "0")
            except Exception:
                return False
        return False

    def close(self):
        self.cancel.set()
        self.logged_in = False
        with self._session_lock:
            for session in self._sessions:
                session.close()
            self._sessions.clear()
        self._cookies.clear()
        self.sid = self.skey = self.uin = self.ticket = self.username = self.nickname = self.uuid = ""
