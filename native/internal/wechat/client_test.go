// SPDX-License-Identifier: AGPL-3.0-only
package wechat

import (
	"bytes"
	"context"
	"crypto/md5"
	"encoding/json"
	"errors"
	"fmt"
	"html"
	"io"
	"net/http"
	"net/url"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"testing"
	"time"
)

type transportFunc func(*http.Request) (*http.Response, error)

func (f transportFunc) RoundTrip(r *http.Request) (*http.Response, error) { return f(r) }
func respond(body string) *http.Response {
	return &http.Response{StatusCode: 200, Header: make(http.Header), Body: io.NopCloser(strings.NewReader(body)), ContentLength: int64(len(body))}
}
func online(t *testing.T) *Client {
	t.Helper()
	c := New()
	c.s = &session{host: initialHost, username: "@one", nickname: "Test", uin: "123", number: 123, sid: "sid", skey: "key", ticket: "ticket", device: c.device}
	c.key = syncKey{1, []syncPair{{1, 2}}}
	c.checkKey = c.key
	c.jar.SetCookies(serviceURL(initialHost, root, ""), []*http.Cookie{{Name: "webwx_data_ticket", Value: "data", Domain: ".qq.com", Path: "/", Secure: true}})
	t.Cleanup(c.Close)
	return c
}

func TestQRAndRegionalLogin(t *testing.T) {
	c := New()
	defer c.Close()
	var polls int
	c.http.Transport = transportFunc(func(r *http.Request) (*http.Response, error) {
		q := r.URL.Query()
		switch r.URL.Path {
		case "/jslogin":
			dest, err := url.QueryUnescape(q.Get("redirect_uri"))
			if err != nil || dest != "https://"+initialHost+root+"webwxnewloginpage" || q.Get("appid") != "wx_webfilehelper" {
				t.Fatal(q)
			}
			return respond(`window.QRLogin.uuid = "qr-id";`), nil
		case "/qrcode/qr-id":
			return respond("QR"), nil
		case root + "login":
			polls++
			if r.URL.Host != regions[initialHost].login || q.Get("uuid") != "qr-id" {
				t.Fatal(r.URL.Host, q)
			}
			if polls > 2 && q.Get("tip") != "0" {
				t.Fatal("lost scanned state")
			}
			switch polls {
			case 1:
				return respond("window.code=408;"), nil
			case 2:
				return respond("window.code=201;"), nil
			default:
				return respond(`window.code=200; window.redirect_uri="https://cmfilehelper.weixin.qq.com/cgi-bin/mmwebwx-bin/webwxnewloginpage?ticket=t&amp;n=1";`), nil
			}
		case root + "webwxnewloginpage":
			if q.Get("n") != "1" || q.Get("version") != "v2" || r.URL.Host != "cmfilehelper.weixin.qq.com" {
				t.Fatal("wrong redirect")
			}
			resp := respond("<error><ret>0</ret><skey>key</skey><wxsid>sid</wxsid><wxuin>123</wxuin><pass_ticket>x+y</pass_ticket></error>")
			resp.Header.Add("Set-Cookie", "webwx_data_ticket=test; Domain=.qq.com; Path=/; Secure")
			return resp, nil
		case root + "webwxinit":
			if q.Get("pass_ticket") != "x+y" || r.URL.Host != "cmfilehelper.weixin.qq.com" {
				t.Fatal("wrong init")
			}
			return respond(`{"BaseResponse":{"Ret":0},"User":{"UserName":"@me","NickName":"A &amp; B"},"SyncKey":{"Count":1,"List":[{"Key":1,"Val":3}]}}`), nil
		}
		t.Fatalf("unexpected endpoint %s", r.URL.Path)
		return nil, nil
	})
	qr, err := c.CreateQR(t.Context())
	if err != nil || string(qr) != "QR" {
		t.Fatal(err)
	}
	for _, want := range []string{"waiting", "scanned", "confirmed"} {
		state, err := c.PollLogin(t.Context())
		if state != want || err != nil {
			t.Fatal(state, err)
		}
	}
	if id, name := c.Identity(); id != "123" || name != "A & B" {
		t.Fatal(id, name)
	}
	if ticket := c.dataTicket(c.s); ticket != "test" {
		t.Fatal(ticket)
	}
	c.Close()
	if id, _ := c.Identity(); id != "" {
		t.Fatal("account survived close")
	}
	if got := c.jar.Cookies(serviceURL("cmfilehelper.weixin.qq.com", root, "")); len(got) > 0 {
		t.Fatal("cookies survived close")
	}
}

func TestLoginDestinationAndRedactedErrors(t *testing.T) {
	for _, raw := range []string{
		"http://" + initialHost + root + "webwxnewloginpage", "https://evil.test" + root + "webwxnewloginpage",
		"https://" + initialHost + ".evil.test" + root + "webwxnewloginpage", "https://a@" + initialHost + root + "webwxnewloginpage",
		"https://" + initialHost + ":80" + root + "webwxnewloginpage", "https://" + initialHost + root + "%77ebwxnewloginpage",
		"https://" + initialHost + root + "webwxnewloginpage#fragment", "https://file.wx2.qq.com" + root + "webwxnewloginpage",
	} {
		u, err := url.Parse(raw)
		if err == nil && validateURL(u, true) {
			t.Fatal(raw)
		}
	}
	c := online(t)
	c.http.Transport = transportFunc(func(r *http.Request) (*http.Response, error) { return nil, errors.New("fake ticket: super-secret") })
	if _, err := c.SendText(t.Context(), "test"); err == nil || strings.Contains(err.Error(), "super-secret") || strings.Contains(err.Error(), "https:") {
		t.Fatal(err)
	}
	count := 0
	c.http.Transport = transportFunc(func(r *http.Request) (*http.Response, error) {
		count++
		res := respond("")
		res.StatusCode = 302
		res.Header.Set("Location", "https://evil.test")
		return res, nil
	})
	_, err := c.SendText(t.Context(), "test")
	if err == nil || count != 1 {
		t.Fatal(err, count)
	}
}

func TestSyncCursorRollbackAndMessageParsing(t *testing.T) {
	c := online(t)
	var failSecond = true
	seen := 0
	c.http.Transport = transportFunc(func(r *http.Request) (*http.Response, error) {
		if strings.HasSuffix(r.URL.Path, "synccheck") {
			if r.URL.Query().Get("synckey") != "1_2" {
				t.Fatal("should replay uncommitted pages")
			}
			return respond(`window.synccheck={retcode:"0",selector:"2"}`), nil
		}
		seen++
		var payload struct{ SyncKey syncKey }
		if err := json.NewDecoder(r.Body).Decode(&payload); err != nil {
			t.Fatal(err)
		}
		if seen%2 == 1 {
			if payload.SyncKey.encode() != "1_2" {
				t.Fatal("wrong first cursor")
			}
			return respond(`{"BaseResponse":{"Ret":0},"ContinueFlag":1,"SyncKey":{"Count":1,"List":[{"Key":1,"Val":3}]},"AddMsgList":[{"MsgId":9007199254740993,"MsgType":1,"Content":"中文 &amp; English<br/>line","FromUserName":"@me","ToUserName":"filehelper"},{"MsgId":"2","MsgType":1,"FromUserName":"friend","ToUserName":"@me"}]}`), nil
		}
		if payload.SyncKey.encode() != "1_3" {
			t.Fatal("wrong second cursor")
		}
		if failSecond {
			return respond(`{"BaseResponse":{"Ret":1}}`), nil
		}
		return respond(`{"BaseResponse":{"Ret":0},"SyncKey":{"Count":1,"List":[{"Key":1,"Val":4}]},"SyncCheckKey":{"Count":1,"List":[{"Key":2,"Val":7}]},"AddMsgList":[{"MsgId":"2","MsgType":43,"FromUserName":"filehelper"}]}`), nil
	})
	if _, err := c.Sync(t.Context()); err == nil {
		t.Fatal("accepted failed sync")
	}
	failSecond = false
	msgs, err := c.Sync(t.Context())
	if err != nil || len(msgs) != 2 || msgs[0].Text != "中文 & English\nline" || msgs[0].ID != "9007199254740993" || msgs[0].Outgoing || msgs[1].Kind != "video" {
		t.Fatal(msgs, err)
	}
	if c.key.encode() != "1_4" || c.checkKey.encode() != "2_7" {
		t.Fatal("did not commit")
	}
	for _, sample := range []string{`<appmsg><type>6</type><title>../../a &amp; b.txt</title><appattach><totallen>12</totallen><attachid>file</attachid></appattach></appmsg>`} {
		for _, body := range []string{sample, "<msg>" + sample + "</msg>", html.EscapeString(sample)} {
			msg, ok := (rawMessage{MsgID: "1", MsgType: 49, Content: body, FromUserName: "filehelper"}).message()
			if !ok || msg.MediaID != "file" || msg.Size != 12 || msg.Text != "a & b.txt" || msg.Kind != "file" {
				t.Fatal(msg)
			}
		}
	}
	for _, p := range []struct{ in, out string }{{"../CON.txt", "_CON.txt"}, {`C:\a\file.txt`, "file.txt"}, {". .", "download"}, {"测试:?.zip", "测试__.zip"}} {
		if name := SafeFilename(p.in); name != p.out {
			t.Error(name)
		}
	}
}

func TestChunkUploadAndAcknowledgement(t *testing.T) {
	for _, mode := range []string{"ok", "missing final id", "changed", "rejected acknowledgement"} {
		t.Run(mode, func(t *testing.T) {
			c := online(t)
			content := bytes.Repeat([]byte("x"), chunkSize+7)
			target := filepath.Join(t.TempDir(), "课件 &.txt")
			if err := os.WriteFile(target, content, 0600); err != nil {
				t.Fatal(err)
			}
			uploads, acks := 0, 0
			c.http.Transport = transportFunc(func(r *http.Request) (*http.Response, error) {
				switch r.URL.Path {
				case root + "webwxuploadmedia":
					if r.URL.Host != regions[initialHost].file {
						t.Fatal("upload host")
					}
					if err := r.ParseMultipartForm(2 * chunkSize); err != nil {
						t.Fatal(err)
					}
					if r.FormValue("chunk") != fmt.Sprint(uploads) || r.FormValue("chunks") != "2" || r.FormValue("webwx_data_ticket") != "data" {
						t.Fatal("wrong multipart metadata")
					}
					var meta struct {
						FileMd5, ToUserName string
						TotalLen            int64
					}
					if err := json.Unmarshal([]byte(r.FormValue("uploadmediarequest")), &meta); err != nil {
						t.Fatal(err)
					}
					if meta.FileMd5 != fmt.Sprintf("%x", md5.Sum(content)) || meta.ToUserName != "filehelper" || meta.TotalLen != int64(len(content)) {
						t.Fatal(meta)
					}
					f, h, err := r.FormFile("filename")
					if err != nil {
						t.Fatal(err)
					}
					data, err := io.ReadAll(f)
					f.Close()
					if err != nil || h.Filename != filepath.Base(target) || !bytes.Equal(data, content[uploads*chunkSize:min(len(content), (uploads+1)*chunkSize)]) {
						t.Fatal("wrong part")
					}
					uploads++
					if mode == "changed" && uploads == 1 {
						if err := os.WriteFile(target, []byte("changed"), 0600); err != nil {
							t.Fatal(err)
						}
					}
					if mode == "missing final id" && uploads == 2 {
						return respond(`{"BaseResponse":{"Ret":0}}`), nil
					}
					return respond(`{"BaseResponse":{"Ret":0},"MediaId":"media"}`), nil
				case root + "webwxsendappmsg":
					acks++
					var p struct {
						Msg struct{ Content, ToUserName string }
					}
					if err := json.NewDecoder(r.Body).Decode(&p); err != nil {
						t.Fatal(err)
					}
					if p.Msg.ToUserName != "filehelper" || !strings.Contains(p.Msg.Content, "课件 &amp;.txt") {
						t.Fatal(p)
					}
					if mode == "rejected acknowledgement" {
						return respond(`{"BaseResponse":{"Ret":1101}}`), nil
					}
					return respond(`{"BaseResponse":{"Ret":0},"MsgId":"42"}`), nil
				}
				t.Fatal("unexpected request")
				return nil, nil
			})
			completed := false
			msg, err := c.SendFile(t.Context(), target, func(sent, total int64) {
				if sent == total {
					completed = true
				}
			})
			if mode == "ok" {
				if err != nil || !completed || msg.ID != "42" || msg.MediaID != "media" || !msg.Outgoing || acks != 1 || uploads != 2 {
					t.Fatal(msg, err, acks, uploads)
				}
				return
			}
			if err == nil || completed {
				t.Fatal("failed file acknowledged")
			}
			if mode == "rejected acknowledgement" {
				if !errors.Is(err, ErrSessionExpired) {
					t.Fatal(err)
				}
			} else if acks != 0 {
				t.Fatal("sent incomplete upload")
			}
		})
	}
}

func TestDownloadCommitsCompleteFiles(t *testing.T) {
	for _, tc := range []struct {
		name, data, rng string
		length          int64
		ok              bool
	}{
		{"normal", `{"lesson":"hello"}`, "", -1, true}, {"XML", "<?xml version=\"1.0\"?><worksheet/>", "", -1, true},
		{"complete range", "video", "bytes 0-4/5", 5, true}, {"partial range", "video", "bytes 0-4/10", 5, false},
		{"truncated", "x", "", 10, false}, {"empty", "", "", 0, false}, {"XML error", "<error><ret>1205</ret></error>", "", -1, false},
		{"JSON error", `{"BaseResponse":{"Ret":1101}}`, "", -1, false},
	} {
		t.Run(tc.name, func(t *testing.T) {
			c := online(t)
			c.http.Transport = transportFunc(func(r *http.Request) (*http.Response, error) {
				res := respond(tc.data)
				res.ContentLength = tc.length
				if tc.rng != "" {
					res.StatusCode = 206
					res.Header.Set("Content-Range", tc.rng)
				}
				return res, nil
			})
			dir := t.TempDir()
			dst := filepath.Join(dir, "课件")
			if err := os.WriteFile(dst, []byte("existing"), 0600); err != nil {
				t.Fatal(err)
			}
			err := c.Download(t.Context(), Message{ID: "one", Kind: "video"}, dst)
			got, e := os.ReadFile(dst)
			if e != nil {
				t.Fatal(e)
			}
			if tc.ok {
				if err != nil || string(got) != tc.data {
					t.Fatal(err)
				}
			} else if err == nil || string(got) != "existing" {
				t.Fatal("overwrote target", err)
			}
			entries, e := os.ReadDir(dir)
			if e != nil || len(entries) != 1 {
				t.Fatal("leaked partial file", entries, e)
			}
		})
	}
}

func TestCloseInterruptsSyncWhileTextCanSend(t *testing.T) {
	c := online(t)
	started := make(chan struct{})
	c.http.Transport = transportFunc(func(r *http.Request) (*http.Response, error) {
		if strings.HasSuffix(r.URL.Path, "synccheck") {
			close(started)
			<-r.Context().Done()
			return nil, r.Context().Err()
		}
		if r.URL.Path != root+"webwxsendmsg" {
			return nil, fmt.Errorf("unexpected endpoint")
		}
		var p struct {
			Msg struct{ Content, ToUserName, ClientMsgId, LocalID string }
		}
		if err := json.NewDecoder(r.Body).Decode(&p); err != nil {
			return nil, err
		}
		if p.Msg.ToUserName != "filehelper" || p.Msg.Content != "hi" || p.Msg.LocalID != p.Msg.ClientMsgId {
			return nil, errors.New("invalid message")
		}
		return respond(`{"BaseResponse":{"Ret":0},"MsgID":9007199254740997}`), nil
	})
	done := make(chan error, 1)
	go func() { _, err := c.Sync(t.Context()); done <- err }()
	<-started
	var wg sync.WaitGroup
	for i := 0; i < 4; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			msg, err := c.SendText(t.Context(), "hi")
			if err != nil || msg.ID != "9007199254740997" {
				t.Errorf("text: %v %v", msg, err)
			}
		}()
	}
	wg.Wait()
	c.Close()
	select {
	case err := <-done:
		if !errors.Is(err, context.Canceled) {
			t.Fatal(err)
		}
	case <-time.After(time.Second):
		t.Fatal("sync did not stop")
	}
}
