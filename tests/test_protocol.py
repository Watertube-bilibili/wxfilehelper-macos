import json
import threading
from pathlib import Path

import pytest
import requests
from defusedxml.ElementTree import fromstring

from wxfilehelper.protocol import (FileHelperClient, Message, ProtocolError, SessionExpired,
    Cancelled, safe_url, safe_filename, parse_message, file_message_xml, CHUNK_SIZE, MAX_FILE_SIZE)


class Response:
    def __init__(self, data=b"", payload=None, headers=None, status=200):
        self.content = data if payload is None else json.dumps(payload, ensure_ascii=False).encode()
        self.text = self.content.decode("utf-8", errors="replace")
        self.headers = headers or {}
        self.status_code = status
        self.closed = False

    def json(self):
        return json.loads(self.content)

    def iter_content(self, size):
        for offset in range(0, len(self.content), size):
            yield self.content[offset:offset + size]

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def close(self):
        self.closed = True


@pytest.fixture
def client():
    c = FileHelperClient()
    c.sid, c.skey, c.uin, c.ticket = "test-session", "test-key", "123", "test-ticket"
    c.username = "@me"
    c.logged_in = True
    c._cookies.set("webwx_data_ticket", "test-data-ticket", domain=".qq.com")
    yield c
    c.close()


@pytest.mark.parametrize("url", [
    "http://szfilehelper.weixin.qq.com/", "https://szfilehelper.weixin.qq.com.evil.test/",
    "https://evil.test/", "https://127.0.0.1/", "file:///etc/passwd",
    "https://user:pass@szfilehelper.weixin.qq.com/", "https://szfilehelper.weixin.qq.com:444/",
    "https://szfilehelper.weixin.qq.com/#secret",
])
def test_rejects_untrusted_destinations(url):
    with pytest.raises(ProtocolError):
        safe_url(url)


def test_login_destination_is_exact():
    safe_url("https://szfilehelper.weixin.qq.com/cgi-bin/mmwebwx-bin/webwxnewloginpage?ticket=test", login=True)
    with pytest.raises(ProtocolError):
        safe_url("https://file.wx2.qq.com/cgi-bin/mmwebwx-bin/webwxnewloginpage", login=True)
    with pytest.raises(ProtocolError):
        safe_url("https://szfilehelper.weixin.qq.com/wrong", login=True)


@pytest.mark.parametrize("name, expected", [
    ("../../report.pdf", "report.pdf"), (r"C:\a\report.pdf", "report.pdf"),
    ("CON.txt", "_CON.txt"), ("....", "download"), ("文件:?.pdf", "文件__.pdf"),
])
def test_safe_names(name, expected):
    assert safe_filename(name) == expected


def test_file_xml_escapes_names_and_identifiers():
    root = fromstring(file_message_xml('hello <世界> & "test".txt', 42, "id<&"))
    assert root.findtext("title") == 'hello <世界> & "test".txt'
    assert root.findtext("appattach/attachid") == "id<&"
    assert root.findtext("type") == "6"


def test_message_filter_and_unicode():
    assert parse_message({"FromUserName": "friend", "ToUserName": "@me", "MsgId": "1"}, "@me") is None
    msg = parse_message({"FromUserName": "filehelper", "ToUserName": "@me", "MsgId": "2", "MsgType": 1,
                         "Content": "中文 &amp; English<br/>next"}, "@me")
    assert msg.text == "中文 & English\nnext"
    assert not msg.outgoing


def test_attachment_parse_and_traversal_name():
    msg = parse_message({"FromUserName": "filehelper", "MsgId": "9", "MsgType": 49,
                         "Content": "<msg>" + file_message_xml("../../文件.zip", 123, "media-1") + "</msg>"}, "@me")
    assert (msg.kind, msg.text, msg.size, msg.media_id) == ("file", "文件.zip", 123, "media-1")


def test_malicious_xml_is_not_expanded():
    msg = parse_message({"FromUserName": "filehelper", "MsgId": "1", "MsgType": 49,
                         "Content": '<!DOCTYPE x [<!ENTITY a SYSTEM "file:///etc/passwd">]><msg>&a;</msg>'}, "@me")
    assert msg.kind == "unsupported"


def test_sync_updates_keys_even_without_messages(client, monkeypatch):
    client.sync_key = {"Count": 1, "List": [{"Key": 1, "Val": 2}]}
    client.check_key = client.sync_key
    captured = []
    def request(method, url, **kwargs):
        captured.append(kwargs)
        return Response(b'window.synccheck={retcode:"0",selector:"2"}')
    monkeypatch.setattr(client, "_request", request)
    monkeypatch.setattr(client, "_api", lambda *a, **k: {"SyncKey": {"Count": 1, "List": [{"Key": 1, "Val": 3}]}, "AddMsgList": []})
    assert client.receive() == []
    assert captured[0]["params"]["synckey"] == "1_2"
    assert client.sync_key["List"][0]["Val"] == 3


def test_session_expiry_is_distinct(client, monkeypatch):
    client.check_key = {"List": []}
    monkeypatch.setattr(client, "_request", lambda *a, **k: Response(b'window.synccheck={retcode:"1101",selector:"0"}'))
    with pytest.raises(SessionExpired):
        client.receive()


def test_text_post_targets_only_filehelper(client, monkeypatch):
    calls = []
    def request(method, url, **kwargs):
        calls.append((url, json.loads(kwargs["data"])))
        return Response(payload={"BaseResponse": {"Ret": 0}, "MsgID": "100"})
    monkeypatch.setattr(client, "_request", request)
    message = client.send_text("你好\nHello")
    assert message.id == "100" and message.outgoing
    assert calls[0][1]["Msg"]["ToUserName"] == "filehelper"
    assert calls[0][1]["Msg"]["Content"] == "你好\nHello"
    assert calls[0][1]["Msg"]["ClientMsgId"] == calls[0][1]["Msg"]["LocalID"]


def test_rejected_send_is_not_reported_as_success(client, monkeypatch):
    count = 0
    def request(*a, **k):
        nonlocal count
        count += 1
        return Response(payload={"BaseResponse": {"Ret": 1204}})
    monkeypatch.setattr(client, "_request", request)
    with pytest.raises(ProtocolError):
        client.send_text("one attempt only")
    assert count == 1


def test_chunk_upload_and_file_ack(client, monkeypatch, tmp_path):
    path = tmp_path / "文件 & report.txt"
    path.write_bytes(b"x" * (CHUNK_SIZE + 7))
    uploaded = []
    sent = []
    def request(method, url, **kwargs):
        uploaded.append(kwargs["files"])
        return Response(payload={"BaseResponse": {"Ret": 0}, "MediaId": "media-42" if len(uploaded) == 2 else ""})
    monkeypatch.setattr(client, "_request", request)
    monkeypatch.setattr(client, "_send", lambda *a, **k: sent.append(a) or "42")
    progress = []
    message = client.send_file(path, progress.append)
    assert len(uploaded) == 2
    assert len(uploaded[0]["filename"][1]) == CHUNK_SIZE
    assert len(uploaded[1]["filename"][1]) == 7
    assert uploaded[1]["chunk"] == (None, "1")
    assert json.loads(uploaded[0]["uploadmediarequest"][1])["ToUserName"] == "filehelper"
    assert sent[0][0] == 6
    assert fromstring(sent[0][1]).findtext("title") == path.name
    assert message.id == "42" and progress[-1] == 100


def test_failed_chunk_never_sends_message(client, monkeypatch, tmp_path):
    path = tmp_path / "report.txt"
    path.write_bytes(b"test")
    monkeypatch.setattr(client, "_request", lambda *a, **k: Response(payload={"BaseResponse": {"Ret": 1}}))
    monkeypatch.setattr(client, "_send", lambda *a, **k: pytest.fail("must not send"))
    with pytest.raises(ProtocolError):
        client.send_file(path)

def test_only_final_upload_chunk_can_authorize_send(client, monkeypatch, tmp_path):
    path = tmp_path / "multipart.txt"
    path.write_bytes(b"x" * (CHUNK_SIZE + 1))
    responses = iter([
        Response(payload={"BaseResponse": {"Ret": 0}, "MediaId": "partial"}),
        Response(payload={"BaseResponse": {"Ret": 0}}),
    ])
    monkeypatch.setattr(client, "_request", lambda *a, **kw: next(responses))
    monkeypatch.setattr(client, "_send", lambda *a, **kw: pytest.fail("must not send a partial file"))
    with pytest.raises(ProtocolError, match="file ID"):
        client.send_file(path)


def test_partial_download_preserves_existing_file(client, monkeypatch, tmp_path):
    target = tmp_path / "test.txt"
    target.write_text("original")
    monkeypatch.setattr(client, "_request", lambda *a, **k: Response(b"short", headers={"Content-Length": "100"}))
    with pytest.raises(ProtocolError):
        client.download(Message("1", "image", "test.jpg"), target)
    assert target.read_text() == "original"
    assert not list(tmp_path.glob("*.part"))

def test_partial_video_range_is_never_saved_as_complete(client, monkeypatch, tmp_path):
    target = tmp_path / "clip.mp4"
    response = Response(b"first", status=206, headers={"Content-Length": "5", "Content-Range": "bytes 0-4/100"})
    monkeypatch.setattr(client, "_request", lambda *a, **kw: response)
    with pytest.raises(ProtocolError, match="Incomplete download"):
        client.download(Message("1", "video", target.name), target)
    assert not target.exists()


@pytest.mark.parametrize("data,content_type", [(b"real-file", "application/octet-stream"), (b"<html>my file</html>", "text/html"), (b'{"hello":1}', "application/json")])
def test_download_saves_real_files(client, monkeypatch, tmp_path, data, content_type):
    target = tmp_path / "download"
    monkeypatch.setattr(client, "_request", lambda *a, **k: Response(data, headers={"Content-Length": str(len(data)), "Content-Type": content_type}))
    client.download(Message("1", "file", "name", media_id="media", sender="filehelper"), target)
    assert target.read_bytes() == data


def test_server_error_not_saved_as_file(client, monkeypatch, tmp_path):
    monkeypatch.setattr(client, "_request", lambda *a, **k: Response(b"<error><ret>1101</ret></error>"))
    target = tmp_path / "download"
    with pytest.raises(ProtocolError):
        client.download(Message("1", "image", "image.jpg"), target)
    assert not target.exists()


def test_no_auto_redirect_and_no_secret_in_network_error(client, monkeypatch):
    def request(*a, **kwargs):
        assert kwargs["allow_redirects"] is False
        raise requests.ConnectionError("secret-url?ticket=private")
    monkeypatch.setattr(client._http(), "request", request)
    with pytest.raises(ProtocolError) as exc:
        client._request("GET", "https://file.wx2.qq.com/test")
    assert "private" not in str(exc.value)


def test_normal_qr_and_confirmation_flow(client, monkeypatch):
    responses = iter([Response(b'window.QRLogin.code = 200; window.QRLogin.uuid = "test-id";'),
                      Response(b"image-bytes"), Response(b'window.code=201;'),
                      Response(b'window.code=200;window.redirect_uri="https://szfilehelper.weixin.qq.com/cgi-bin/mmwebwx-bin/webwxnewloginpage?ticket=test";'),
                      Response(b"<error><ret>0</ret><skey>key</skey><wxsid>sid</wxsid><wxuin>123</wxuin><pass_ticket>ticket</pass_ticket></error>"),
                      Response(payload={"BaseResponse": {"Ret": 0}, "User": {"UserName": "@me", "NickName": "Test"},
                                        "SyncKey": {"Count": 1, "List": [{"Key": 1, "Val": 2}]}})])
    monkeypatch.setattr(client, "_request", lambda *a, **k: next(responses))
    assert client.create_qr() == b"image-bytes"
    assert client.poll_login() == "confirm"
    assert client.poll_login(True) == "online"
    assert client.logged_in and client.nickname == "Test"


def test_cancel_prevents_network(client, monkeypatch):
    client.cancel.set()
    monkeypatch.setattr(client, "_http", lambda: pytest.fail("network must not be called"))
    with pytest.raises(Cancelled):
        client._request("GET", "https://file.wx2.qq.com/test")
